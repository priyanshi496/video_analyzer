"""
Moment Detection Service

Uses LLM to analyze podcast transcripts and identify important moments
that deserve zoom effects - key insights, emotional peaks, statistics, etc.
"""

import logging
import json
import re
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from openai import OpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class ImportantMoment:
    """Represents an important moment detected by LLM"""
    start_time: float
    end_time: float
    text: str
    reason: str
    intensity: str  # "low", "medium", "high"
    keywords: List[str]

class MomentDetectionService:
    """Detects important moments in podcast transcripts using LLM analysis"""
    
    def __init__(self):
        self.nvidia_client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=settings.NVIDIA_API_KEY,
        )
        self.model = "openai/gpt-oss-120b"

    async def find_key_moments(
        self, 
        transcript_text: str, 
        words_with_timestamps: List[Dict]
    ) -> List[Dict]:
        """
        Analyze transcript to find important moments for zoom effects
        
        Args:
            transcript_text: Full transcript text
            words_with_timestamps: Words with timing data
            
        Returns:
            List of important moments with timing and metadata
        """
        logger.info("Analyzing transcript for important moments...")
        
        try:
            # Step 1: Use LLM to identify important text segments
            important_segments = await self._analyze_with_llm(transcript_text)
            
            # Step 2: Map text segments to precise timestamps
            moments_with_timing = await self._map_to_timestamps(
                important_segments, 
                words_with_timestamps
            )
            
            # Step 3: Filter and optimize moments
            optimized_moments = self._optimize_moments(moments_with_timing)
            
            logger.info(f"Found {len(optimized_moments)} important moments")
            return optimized_moments
            
        except Exception as e:
            logger.error(f"Failed to detect important moments: {str(e)}")
            # Return empty list on error - video will still work without zooms
            return []

    async def _analyze_with_llm(self, transcript_text: str) -> List[Dict]:
        """Use NVIDIA's gpt-oss-120b to identify important text segments."""
        prompt = self._build_analysis_prompt(transcript_text)

        loop = asyncio.get_running_loop()
        try:
            response_text = await loop.run_in_executor(
                None, self._call_nvidia, prompt
            )
            segments = self._parse_llm_response(response_text)
            if segments:
                logger.info(f"NVIDIA LLM found {len(segments)} important moments")
                return segments
            logger.warning("NVIDIA LLM returned no parseable segments")
        except Exception as e:
            logger.warning(f"NVIDIA LLM moment detection failed: {e}")

        return []

    def _call_nvidia(self, prompt: str) -> str:
        """Synchronous NVIDIA API call — run via run_in_executor."""
        completion = self.nvidia_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            top_p=1,
            max_tokens=1024,
            stream=False,
        )
        msg = completion.choices[0].message
        # gpt-oss-120b is a reasoning model — final answer may be in
        # content OR reasoning_content depending on the response
        content = msg.content
        reasoning = getattr(msg, "reasoning_content", None)
        # Prefer content if non-empty, otherwise fall back to reasoning_content
        return content if content and content.strip() else (reasoning or "")

    def _build_analysis_prompt(self, transcript_text: str) -> str:
        return f"""You are a video editor. Analyze this podcast transcript and find the 2-3 MOST engaging moments that deserve a zoom-in effect.

IMPORTANT: Be very selective. Choose only the absolute BEST moments. Quality over quantity.

Look for:
- Strong opinions or controversial statements
- Key insights or revelations  
- Statistics or impressive numbers
- Emotional peaks (excitement, frustration, passion)
- Definitive conclusions or call-to-actions

TRANSCRIPT:
{transcript_text}

CRITICAL JSON FORMATTING RULES:
- Return ONLY a valid JSON array. No markdown, no backticks, no explanation.
- The "text" field must NOT contain any double-quote characters. If the quote naturally has quotes, paraphrase it instead of quoting verbatim.
- Keep each "text" value under 15 words.
- Do not use apostrophes with special characters — use plain ASCII only.

Example format:
[
  {{"text": "exact quote from transcript", "reason": "key_insight", "intensity": "high", "keywords": ["word1", "word2"]}},
  {{"text": "another quote", "reason": "statistics", "intensity": "medium", "keywords": ["word1"]}}
]

Valid reason values: key_insight, statistics, strong_opinion, emotional_peak, conclusion, call_to_action
Valid intensity values: low, medium, high

JSON array only:"""

    def _parse_llm_response(self, response_text: str) -> List[Dict]:
        """Parse LLM response — tries multiple strategies to extract valid JSON."""
        if not response_text:
            return []

        # Strategy 1: clean JSON array block
        for pattern in [r'\[\s*\{.*?\}\s*\]', r'\[.*?\]']:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                try:
                    segments = json.loads(match.group())
                    valid = [s for s in segments if "text" in s and "reason" in s]
                    if valid:
                        return self._normalize_segments(valid)
                except json.JSONDecodeError:
                    pass

        # Strategy 2: trailing comma / truncation fix
        try:
            cleaned = re.sub(r',\s*([}\]])', r'\1', response_text)
            cleaned = cleaned.strip()
            if cleaned.count('[') > cleaned.count(']'):
                cleaned = re.sub(r',?\s*\{[^}]*$', '', cleaned)
                cleaned = cleaned.rstrip(',').rstrip() + ']'
            match = re.search(r'\[.*?\]', cleaned, re.DOTALL)
            if match:
                segments = json.loads(match.group())
                valid = [s for s in segments if "text" in s and "reason" in s]
                if valid:
                    return self._normalize_segments(valid)
        except Exception:
            pass

        # Strategy 3: extract individual objects when array is malformed
        try:
            objects = re.findall(r'\{[^{}]*\}', response_text, re.DOTALL)
            recovered = []
            for obj_str in objects:
                try:
                    recovered.append(json.loads(obj_str))
                    continue
                except json.JSONDecodeError:
                    pass
                text_m = re.search(r'"text"\s*:\s*"(.*?)"\s*,\s*"reason"', obj_str, re.DOTALL)
                reason_m = re.search(r'"reason"\s*:\s*"([^"]*)"', obj_str)
                intensity_m = re.search(r'"intensity"\s*:\s*"([^"]*)"', obj_str)
                if text_m and reason_m:
                    recovered.append({
                        "text": text_m.group(1),
                        "reason": reason_m.group(1),
                        "intensity": intensity_m.group(1) if intensity_m else "medium",
                        "keywords": [],
                    })
            if recovered:
                valid = [s for s in recovered if "text" in s and "reason" in s]
                if valid:
                    return self._normalize_segments(valid)
        except Exception:
            pass

        logger.warning("Failed to parse LLM JSON response after all strategies")
        return []

    def _normalize_segments(self, valid: List[Dict]) -> List[Dict]:
        for s in valid:
            raw = s.get("intensity", "medium")
            if isinstance(raw, (int, float)):
                s["intensity"] = "high" if raw >= 7 else ("medium" if raw >= 4 else "low")
            if "keywords" not in s:
                s["keywords"] = []
        return valid

    async def _map_to_timestamps(
        self, 
        segments: List[Dict], 
        words_with_timestamps: List[Dict]
    ) -> List[Dict]:
        """Map text segments to precise timestamps using word data"""
        moments_with_timing = []
        
        for segment in segments:
            quote_text = segment["text"].lower().strip()
            
            # Find this quote in the word timestamps
            timing = self._find_quote_timing(quote_text, words_with_timestamps)
            
            if timing:
                moment = {
                    "start_time": timing["start"],
                    "end_time": timing["end"],
                    "text": segment["text"],
                    "reason": segment["reason"],
                    "intensity": segment["intensity"], 
                    "keywords": segment.get("keywords", []),
                    "matched_words": timing["matched_words"]
                }
                moments_with_timing.append(moment)
            else:
                logger.warning(f"Could not find timing for quote: {quote_text[:50]}...")
        
        return moments_with_timing

    def _find_quote_timing(
        self, 
        quote_text: str, 
        words_with_timestamps: List[Dict]
    ) -> Optional[Dict]:
        """Find start/end timestamps for a text quote"""
        quote_words = quote_text.split()
        if len(quote_words) < 2:
            return None
        
        # Look for sequence of words matching the quote
        for i in range(len(words_with_timestamps) - len(quote_words) + 1):
            window_words = words_with_timestamps[i:i + len(quote_words)]
            
            # Check if this window matches the quote (fuzzy matching)
            if self._words_match_quote(window_words, quote_words):
                return {
                    "start": window_words[0]["start"],
                    "end": window_words[-1]["end"],
                    "matched_words": window_words
                }
        
        # If exact match fails, try partial matching
        return self._find_partial_match(quote_text, words_with_timestamps)

    def _words_match_quote(self, window_words: List[Dict], quote_words: List[str]) -> bool:
        """Check if window of words matches quote (with fuzzy matching)"""
        if len(window_words) != len(quote_words):
            return False
        
        matches = 0
        for word_data, quote_word in zip(window_words, quote_words):
            spoken_word = word_data["word"].lower().strip('.,!?;:"')
            quote_word = quote_word.lower().strip('.,!?;:"')
            
            if spoken_word == quote_word or abs(len(spoken_word) - len(quote_word)) <= 2:
                matches += 1
        
        # Allow some fuzzy matching (80% of words must match)
        return matches >= len(quote_words) * 0.8

    def _find_partial_match(
        self, 
        quote_text: str, 
        words_with_timestamps: List[Dict]
    ) -> Optional[Dict]:
        """Find partial match using key words from quote"""
        quote_words = quote_text.split()
        key_words = [w for w in quote_words if len(w) > 3]  # Focus on longer words
        
        if len(key_words) < 2:
            return None
        
        # Find windows containing most key words
        best_match = None
        best_score = 0
        
        window_size = min(len(quote_words) + 3, 10)  # Flexible window
        
        for i in range(len(words_with_timestamps) - window_size + 1):
            window = words_with_timestamps[i:i + window_size]
            window_text = " ".join([w["word"] for w in window]).lower()
            
            # Count key word matches
            matches = sum(1 for kw in key_words if kw.lower() in window_text)
            score = matches / len(key_words)
            
            if score > best_score and score >= 0.6:  # At least 60% key words match
                best_score = score
                best_match = {
                    "start": window[0]["start"],
                    "end": window[-1]["end"],
                    "matched_words": window
                }
        
        return best_match

    def _optimize_moments(self, moments: List[Dict]) -> List[Dict]:
        """Filter and optimize moments for best zoom effects"""
        if not moments:
            return []
        
        # Sort by start time
        moments.sort(key=lambda m: m["start_time"])
        
        optimized = []
        
        for moment in moments:
            # Skip very short moments (< 1.5 seconds)
            if moment["end_time"] - moment["start_time"] < 1.5:
                continue
            
            # Extend short moments to minimum 2.5 seconds for smooth zoom
            if moment["end_time"] - moment["start_time"] < 2.5:
                center = (moment["start_time"] + moment["end_time"]) / 2
                moment["start_time"] = max(0, center - 1.25)
                moment["end_time"] = center + 1.25
            
            # Skip if too close to previous moment (< 4 second gap for smoother separation)
            if optimized:
                last_end = optimized[-1]["end_time"]
                if moment["start_time"] - last_end < 4.0:
                    continue
            
            optimized.append(moment)
        
        # Limit to max 3 moments per video for quality over quantity
        return optimized[:3]