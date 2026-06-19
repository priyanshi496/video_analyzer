import logging
"""
pipeline.py — Main video analysis pipeline.

  1. Analyzes all videos in parallel threads (quality + LLM calls).
  2. Handles chunking for long videos.
  3. Merges adjacent segments with a configurable max_duration cap.
  4. Enforces story ordering via a text-only LLM call.
  5. Returns final ordered best_segments list ready for the editor UI.
"""

import time
import json
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core.config import settings
from app.services.frames_service import extract_representative_frames, pick_frame_count, is_likely_black_clip
from app.services.llm_service import call_openrouter_multiimage, call_openrouter_text
from app.services.prompts_service import (
    build_timeline_prompt,
    build_story_order_prompt,
    parse_json_response,
    clamp_segments,
)
from app.services.logger_service import (
    init_run_log_dir,
    log_vision_call,
    log_story_order_call,
    write_run_summary,
    write_beat_sync_log,
)

CONFIG = {
    "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "fallback_models": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "google/gemma-4-31b-it:free",
    ],
    "max_tokens_vision": 4096,
    "max_tokens_text":   1000,
    "story_order_model":    "openai/gpt-oss-120b:free",
    "story_order_fallback": "meta-llama/llama-3-8b-instruct:free",
    "max_parallel_vision_calls": 3,
    "image_limit_per_request": 8,
    "max_reference_images": None,
    "chunk_window_sec":  45,
    "chunk_overlap_sec":  2,
    "min_request_gap_sec": 2.0,
    "max_retries":         3,
    "base_retry_sleep":    3.0,
    "quality_downsample_width": 360,
    "max_reel_sec": 60,
}
import threading

CACHE_FILE = Path("logs/analysis_cache.json")
CACHE_LOCK = threading.Lock()

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logging.warning(f"Failed to save cache: {e}")


# ── Video Metadata ─────────────────────────────────────────────────────────────

def get_video_info(path: str) -> Optional[dict]:
    is_image = Path(path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    if is_image:
        import cv2
        img = cv2.imread(path)
        if img is not None:
            height, width = img.shape[:2]
        else:
            width, height = 1080, 1920
        return {
            "path":         path,
            "duration_sec": 3.0,  # Fabricate 3.0s duration for static photo
            "width":        width,
            "height":       height,
            "fps":          30.0,
            "total_frames": 1,
            "is_image":     True,
        }

    try:
        cmd = ["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
        meta = json.loads(out)
    except Exception as e:
        logging.info(f"  ✗ ffprobe failed for {path}: {e} — skipping.")
        return None

    import cv2
    vs = next((s for s in meta["streams"] if s.get("codec_type") == "video"), None)
    if vs is None:
        logging.info(f"  ✗ No video stream in {path} — skipping.")
        return None

    duration = float(meta["format"].get("duration", 0) or 0)
    if duration < 0.5:
        logging.info(f"  ✗ duration={duration:.2f}s too short: {path} — skipping.")
        return None

    r_frame_rate = vs.get("r_frame_rate", "30/1")
    try:
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    except Exception:
        fps = 30.0

    cap = cv2.VideoCapture(path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    return {
        "path":         path,
        "duration_sec": duration,
        "width":        int(vs.get("width", 0)),
        "height":       int(vs.get("height", 0)),
        "fps":          fps,
        "total_frames": total_frames,
    }


# ── Fallback Analysis ──────────────────────────────────────────────────────────

def _pick_best_quality_window(
    quality_samples: list,
    offset_sec: float,
    window_sec: float,
    clip_duration: float = 3.0,
) -> tuple:
    """
    When the LLM fails, use pre-computed quality data to find the single
    best short window (lowest shake + highest blur = sharpest steady moment).
    Returns (best_start, best_end) within the window [offset_sec, offset_sec+window_sec].
    """
    window_end = offset_sec + window_sec
    # Filter quality samples to those inside this chunk window
    relevant = [
        s for s in quality_samples
        if offset_sec <= s.get("t", 0) <= window_end
        and s.get("motion_type", "NORMAL") not in ("CHAOTIC", "WHIP_PAN")
    ]
    if not relevant:
        # No quality data — default to middle of window
        mid = offset_sec + window_sec / 2
        start = max(offset_sec, mid - clip_duration / 2)
        end   = min(window_end, start + clip_duration)
        return round(start, 2), round(end, 2)

    # Score each sample: reward sharpness (blur_norm), penalise shake
    def score(s):
        return s.get("blur_norm", 5) - s.get("shake_norm", 5) * 0.5

    best = max(relevant, key=score)
    center = best["t"]
    start  = max(offset_sec,  round(center - clip_duration / 2, 2))
    end    = min(window_end,  round(start  + clip_duration,     2))
    return start, end


def make_fallback_analysis(
    info: dict,
    offset_sec: float = 0.0,
    window_sec: float = None,
    video_quality_map: dict = None,
) -> dict:
    """
    Called when the LLM fails for a chunk.
    Tries to pick the BEST quality window using pre-computed optical flow data
    rather than blindly including the full window (which gets dropped later anyway).
    """
    window_sec = window_sec if window_sec is not None else info["duration_sec"]

    # Attempt quality-guided best-window selection
    q_samples = []
    if video_quality_map:
        q_samples = (video_quality_map.get(info["path"], {}) or {}).get("samples", [])

    clip_duration = 3.0
    if q_samples:
        start, end = _pick_best_quality_window(q_samples, offset_sec, window_sec, clip_duration)
        reason = "Quality-guided fallback: best SETTLED window selected from optical flow data (LLM unavailable)."
        summary = "[FALLBACK-QUALITY] LLM unavailable — best quality window auto-selected from shake/blur analysis."
        logging.info(f"  ⚡ Quality-guided fallback: selected {start}s–{end}s as best window in [{offset_sec:.1f}s–{offset_sec+window_sec:.1f}s]")
    else:
        # No quality data — take the first 3s of the window
        start = round(offset_sec, 2)
        end   = round(min(offset_sec + clip_duration, offset_sec + window_sec), 2)
        reason = "Fallback: API timeout, no quality data available."
        summary = "[FALLBACK] Model did not respond. Best-effort 3s window included."

    return {
        "video_summary":     summary,
        "camera_rotation":   0,
        "detected_scenario": "D",
        "overall_mood": "unknown", "overall_vibe": "unknown",
        "key_moments":    [{"timestamp_sec": start, "description": "Quality-guided fallback window"}],
        "segments":       [{"start_sec": start, "end_sec": end, "what_happens": "Quality-guided fallback",
                            "mood": "unknown", "energy": 5, "visual_quality": 7,
                            "instagrammable": 7, "story_value": 5, "keep": True,
                            "reason": reason}],
        "best_segments":  [{"start_sec": start, "end_sec": end,
                            "reason": reason,
                            "priority": 4, "narrative_role": "unknown",
                            "scenario_rule_applied": "Scenario D fallback — quality-guided",
                            "journey_phase": "unknown", "location_tag": "unknown",
                            "scene_category": "mixed", "primary_subjects": []}],
    }


# ── JSON Schema Definition & Repair ───────────────────────────────────────────

VISION_SCHEMA_DESC = """{
  "video_summary": "string describing the video contents",
  "camera_rotation": 0,
  "detected_scenario": "string (A|B|C|D|E|F)",
  "overall_mood": "string",
  "overall_vibe": "string",
  "editor_reasoning": "string",
  "key_moments": [
    {
      "timestamp_sec": float,
      "description": "string"
    }
  ],
  "best_segments": [
    {
      "start_sec": float,
      "end_sec": float,
      "what_happens": "string",
      "mood": "string",
      "energy": integer (1-10),
      "visual_quality": integer (1-10),
      "instagrammable": integer (1-10),
      "story_value": integer (1-10),
      "reason": "string",
      "priority": integer (1-5),
      "narrative_role": "string (setup|action|climax|reaction|payoff)",
      "clip_type_applied": "string",
      "location_tag": "string (snake_case)",
      "journey_phase": "string (approach|arrival|exterior|interior|detail|climax)",
      "time_of_day": "string (dawn|morning|afternoon|golden_hour|dusk|night|unknown)",
      "scene_category": "string (scenery|people|action|food|vehicle|mixed)",
      "primary_subjects": ["string"]
    }
  ]
}"""


def repair_json_output(bad_text: str, schema_desc: str, api_key: str) -> str:
    """
    Triggers a schema repair call to OpenRouter's text model asking it to parse and clean the corrupt payload.
    """
    prompt = f"""You are a JSON repair assistant.
We received a malformed, truncated, or incomplete JSON response from a vision model.
Your task is to parse, repair, and format this content into a strictly valid JSON object matching the target schema.

TARGET SCHEMA:
{schema_desc}

CORRUPT/MALFORMED JSON STRING:
{bad_text}

CRITICAL RULES:
1. Ensure the output is a single, valid JSON object matching the target schema.
2. The root object MUST contain the "best_segments" array. If "best_segments" is empty or missing, extract segment information from other keys (like "segments" or "moments") and map them to "best_segments".
3. Correct any missing closing brackets, brackets mismatch, trailing commas, or quotes.
4. Output ONLY the raw JSON string. Do NOT wrap it in markdown code blocks (like ```json) or add any conversational preamble.
"""
    text_model = CONFIG.get("story_order_model", "openrouter/owl-alpha")
    fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
    try:
        logging.info("  [Repair] Triggering LLM schema repair for malformed response...")
        return call_openrouter_text(prompt, model=text_model, fallbacks=fallbacks)
    except Exception as e:
        logging.warning(f"  ✗ Text-repair call failed: {e}")
        raise e


# ── Analyze One Window ─────────────────────────────────────────────────────────

def analyze_window(
    info: dict,
    offset_sec: float,
    window_sec: float,
    api_key: str,
    video_quality_map: dict,
    chunk_label: str = "",
    reference_paths: list = None,
    directives: str = "",
    audio_analysis: dict = None,
) -> tuple:
    """
    Analyze one time window. Returns (frame_meta, parsed_dict) — never None.
    """
    reference_paths = reference_paths or []
    n_frames   = pick_frame_count(window_sec)
    frame_meta = extract_representative_frames(
        info["path"], window_sec, n_frames,
        offset_sec=offset_sec, chunk_label=chunk_label
    )

    if not frame_meta:
        logging.info(f"  ✗ No frames for {info['path']} [{offset_sec}s–{offset_sec+window_sec:.1f}s] → quality-guided fallback")
        return [], make_fallback_analysis(info, offset_sec, window_sec, video_quality_map)

    limit     = CONFIG["image_limit_per_request"]
    ref_cap   = CONFIG["max_reference_images"]
    ref_slots = limit - len(frame_meta)
    if ref_cap is not None:
        ref_slots = min(ref_slots, ref_cap)
    ref_slots = max(ref_slots, 0)

    payload_images = [f["path"] for f in frame_meta] + reference_paths[:ref_slots]
    window_info    = dict(info, duration_sec=window_sec)
    ref_sent       = reference_paths[:ref_slots]
    prompt         = build_timeline_prompt(window_info, frame_meta, ref_sent, video_quality_map, audio_analysis=audio_analysis, directives=directives)

    parsed = None
    raw = None

    # 1. Vision API Call (Retry max 2 attempts only on API connection/timeout errors)
    for attempt in range(1, 3):
        t0 = time.time()
        try:
            raw = call_openrouter_multiimage(payload_images, prompt, CONFIG["model"])
            duration = time.time() - t0
            # Log successful API call (will update parsed/errors later)
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw or "",
                parsed=None,
                parse_error=None,
                attempt=attempt,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
            break
        except Exception as e:
            duration = time.time() - t0
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw or "",
                parsed=None,
                parse_error=str(e),
                attempt=attempt,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
            if attempt < 2:
                logging.info(f"  ⚠️ Vision API attempt {attempt} failed: {e}. Retrying once...")
                time.sleep(3)
            else:
                logging.error(f"  ✗ Vision API calls failed after 2 attempts: {e}")

    # 2. JSON Parse & Repair (Only if raw response was successfully retrieved)
    if raw:
        t0 = time.time()
        try:
            parsed = parse_json_response(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Parsed JSON is not a dictionary")
            parsed = auto_recover_segments(parsed)
            if not parsed.get("best_segments"):
                raise ValueError("Parsed JSON is missing required 'best_segments' key or the list is empty")
            
            # Log successful parsing
            duration = time.time() - t0
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw,
                parsed=parsed,
                parse_error=None,
                attempt=1,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
        except Exception as parse_err:
            logging.warning(f"  ⚠️ JSON parse/schema validation error: {parse_err}. Attempting schema repair...")
            try:
                repaired_raw = repair_json_output(raw, VISION_SCHEMA_DESC, api_key)
                parsed = parse_json_response(repaired_raw)
                if isinstance(parsed, dict):
                    parsed = auto_recover_segments(parsed)
                if isinstance(parsed, dict) and "best_segments" in parsed:
                    logging.info("  ✓ JSON successfully repaired by text model!")
                    # Log successful repaired parsing
                    duration = time.time() - t0
                    log_vision_call(
                        video_path=info["path"],
                        model=CONFIG["model"],
                        prompt=prompt,
                        raw_response=raw,
                        parsed=parsed,
                        parse_error=None,
                        attempt=1,
                        duration_sec=duration,
                        chunk_label=chunk_label,
                    )
                else:
                    raise ValueError("Repaired response still missing 'best_segments'")
            except Exception as repair_err:
                logging.warning(f"  ✗ JSON repair failed: {repair_err}")
                duration = time.time() - t0
                log_vision_call(
                    video_path=info["path"],
                    model=CONFIG["model"],
                    prompt=prompt,
                    raw_response=raw,
                    parsed=None,
                    parse_error=f"Parse Error: {parse_err} | Repair Error: {repair_err}",
                    attempt=1,
                    duration_sec=duration,
                    chunk_label=chunk_label,
                )

    if parsed is None:
        logging.info(f"  → Quality-guided fallback [{offset_sec}s–{offset_sec+window_sec:.1f}s] (LLM unavailable)")
        return frame_meta, make_fallback_analysis(info, offset_sec, window_sec, video_quality_map)

    return frame_meta, parsed


# ── Focus Directive & Filtering Helpers ────────────────────────────────────────

def parse_focus_directive(directives: str) -> dict:
    """
    Parses natural language focus into structured config.
    Examples:
      "scenery 7/10"        → {"type": "weight",   "category": "scenery", "weight": 0.7}
      "focus on birthday girl" → {"type": "subject",  "subject": "birthday girl"}
      "7/10 people"         → {"type": "weight",   "category": "people",  "weight": 0.7}
    """
    if not directives:
        return {"type": None}
    
    import re
    focus = {"type": None}
    
    # Weight pattern: "scenery 7/10" or "7/10 scenery"
    match = re.search(r'(\d+)/(\d+)\s*([a-zA-Z]+)|([a-zA-Z]+)\s*(\d+)/(\d+)', directives, re.I)
    if match:
        g = match.groups()
        num, den, cat = (g[0], g[1], g[2]) if g[0] else (g[4], g[5], g[3])
        focus = {"type": "weight", "category": cat.lower(), "weight": int(num)/int(den)}
        return focus
    
    # Subject pattern: "focus on X" or "birthday girl" etc.
    match = re.search(r'focus\s+on\s+(.+)', directives, re.I)
    if match:
        focus = {"type": "subject", "subject": match.group(1).strip()}
    
    return focus


def calculate_alignment_score(seg: dict, directives: str) -> int:
    """
    Calculates how accurately a segment followed the user directives (instructions).
    If no directives are specified, scores based on visual quality, priority, and default parameters.
    """
    if not directives:
        # Fallback when there are no instructions:
        # Map visual_quality (1-10) and priority (1-5, where lower is better) to a 75-98 range.
        vq = int(seg.get("visual_quality", 8) or 8)
        inst = int(seg.get("instagrammable", 8) or 8)
        priority = int(seg.get("priority", 3) or 3)
        priority_bonus = (5 - priority) * 2  # up to 8 points
        base_score = 72 + vq * 1.2 + inst * 0.8 + priority_bonus
        return min(98, max(70, int(base_score)))

    # If there are instructions/directives:
    focus = parse_focus_directive(directives)
    score_val = 70  # starting base score for any valid candidate clip
    
    # Simple word overlap matching from directives
    raw_words = [w.lower().strip(",.!?\"'") for w in directives.split()]
    stop_words = {"the", "a", "an", "on", "in", "of", "and", "or", "to", "for", "with", "at", "by", "from", "focus", "mostly", "scene"}
    query_keywords = [w for w in raw_words if len(w) > 2 and w not in stop_words]
    
    subjects_str = " ".join(seg.get("primary_subjects", [])).lower()
    what_happens = str(seg.get("what_happens") or "").lower()
    reason = str(seg.get("reason") or "").lower()
    loc = str(seg.get("location_tag") or "").lower()
    category = str(seg.get("scene_category") or "").lower()
    
    matches = 0
    for kw in query_keywords:
        if kw in subjects_str:
            matches += 3
        if kw in what_happens:
            matches += 2
        if kw in reason:
            matches += 1
        if kw in loc:
            matches += 2
        if kw in category:
            matches += 2
            
    focus_match = False
    if focus.get("type") == "weight":
        cat = focus["category"]
        if category == cat:
            score_val = 90
            focus_match = True
    elif focus.get("type") == "subject":
        sub_kws = [w.lower().strip(",.!?\"'") for w in focus["subject"].split() if len(w) > 2 and w not in stop_words]
        for kw in sub_kws:
            if kw in subjects_str:
                score_val = max(score_val, 92)
                focus_match = True
            elif kw in what_happens or kw in reason:
                score_val = max(score_val, 85)
                focus_match = True
                
    if matches > 0:
        if focus_match:
            score_val += min(6, matches)
        else:
            score_val = 80 + min(12, matches * 2)
    else:
        if not focus_match:
            # Clip doesn't match the focus directive and has no keyword matches.
            # Give it a lower score (65-75 range) to indicate low relevance to instructions.
            vq = int(seg.get("visual_quality", 5) or 5)
            score_val = 65 + vq
            
    return min(98, max(60, int(score_val)))


def apply_focus_filter(clips: list, focus: dict, total_slots: int) -> list:
    """
    Reorders/filters clip candidates to respect focus directive
    before passing to story sequencer.
    """
    if not focus or not focus.get("type"):
        return clips
    
    if focus["type"] == "weight":
        cat = focus["category"]
        weight = focus["weight"]
        
        target_count = round(total_slots * weight)
        remainder = max(0, total_slots - target_count)
        
        priority = [c for c in clips if str(c.get("scene_category")).lower().strip() == cat]
        others   = [c for c in clips if str(c.get("scene_category")).lower().strip() != cat]
        
        # Cap at available, fill remainder from others
        chosen_priority = priority[:target_count]
        chosen_others   = others[:max(0, total_slots - len(chosen_priority))]
        
        return chosen_priority + chosen_others  # sequencer will reorder narratively
    
    elif focus["type"] == "subject":
        subject_keywords = focus["subject"].lower().split()
        
        def subject_score(clip):
            # Check both primary_subjects and what_happens for semantic matching
            subjects = " ".join(clip.get("primary_subjects", [])).lower()
            what_happens = str(clip.get("what_happens") or "").lower()
            reason = str(clip.get("reason") or "").lower()
            score = sum(kw in subjects for kw in subject_keywords) * 2
            score += sum(kw in what_happens for kw in subject_keywords)
            score += sum(kw in reason for kw in subject_keywords)
            return score
        
        # Sort: matching clips first, non-matching as fillers
        return sorted(clips, key=subject_score, reverse=True)
    
    return clips


# ── Helpers ────────────────────────────────────────────────────────────────────

def auto_recover_segments(parsed: dict) -> dict:
    """Robust fallback: if best_segments is empty/missing but segments is populated, auto-recover them."""
    # Force camera_rotation to always be 0 to prevent AI hallucinated rotations.
    # User can still manually rotate clips using the editor UI.
    rotation = 0

    if not isinstance(parsed, dict):
        parsed = {}

    best_segs = parsed.get("best_segments")
    if not isinstance(best_segs, list):
        best_segs = []

    # If best_segments is empty, try to recover from other potential list fields
    if not best_segs:
        # Check 'segments'
        if parsed.get("segments") and isinstance(parsed["segments"], list):
            keep_segs = [s for s in parsed["segments"] if s.get("keep") is True]
            source_segs = keep_segs if keep_segs else parsed["segments"]
            import uuid
            for s in source_segs:
                unique_loc = s.get("location_tag") or f"unknown_{uuid.uuid4().hex[:6]}"
                best_segs.append({
                    "start_sec": s.get("start_sec", 0.0),
                    "end_sec": s.get("end_sec", 3.0),
                    "reason": s.get("reason") or s.get("what_happens") or "Auto-recovered highlight segment",
                    "priority": s.get("priority") or 1,
                    "narrative_role": s.get("narrative_role") or s.get("role") or "unknown",
                    "clip_type_applied": s.get("clip_type_applied") or "Auto-recovered segment fallback",
                    "location_tag": unique_loc,
                    "journey_phase": s.get("journey_phase") or "unknown"
                })
        
        # Check 'key_moments' / 'moments'
        elif parsed.get("key_moments") and isinstance(parsed["key_moments"], list):
            import uuid
            for km in parsed["key_moments"]:
                ts = km.get("timestamp_sec", 0.0)
                best_segs.append({
                    "start_sec": ts,
                    "end_sec": ts + 3.0,
                    "reason": km.get("description") or "Auto-recovered from key moment",
                    "priority": 2,
                    "narrative_role": "action",
                    "clip_type_applied": "Key moment fallback",
                    "location_tag": f"unknown_{uuid.uuid4().hex[:6]}",
                    "journey_phase": "unknown"
                })

        # Absolute fallback: if still empty, create one default segment covering 0.0 to 3.0s
        if not best_segs:
            best_segs.append({
                "start_sec": 0.0,
                "end_sec": 3.0,
                "reason": "Fallback: Default segment auto-created due to empty model output.",
                "priority": 3,
                "narrative_role": "unknown",
                "clip_type_applied": "Default fallback",
                "location_tag": "unknown_fallback",
                "journey_phase": "unknown"
            })

    parsed["best_segments"] = best_segs
    for seg in parsed["best_segments"]:
        seg["camera_rotation"] = rotation
    return parsed


def offset_segments(parsed: dict, offset_sec: float) -> dict:
    if offset_sec == 0.0:
        return parsed
    for key in ("segments", "best_segments"):
        for seg in parsed.get(key, []):
            seg["start_sec"] = round(seg.get("start_sec", 0) + offset_sec, 2)
            seg["end_sec"]   = round(seg.get("end_sec",   0) + offset_sec, 2)
    for km in parsed.get("key_moments", []):
        km["timestamp_sec"] = round(km.get("timestamp_sec", 0) + offset_sec, 2)
    return parsed


def merge_chunk_analyses(chunks: list, full_duration: float) -> dict:
    if len(chunks) == 1:
        return chunks[0]
    merged = {
        "video_summary":     " | ".join(c.get("video_summary", "") for c in chunks),
        "detected_scenario": "B",
        "overall_mood":      chunks[0].get("overall_mood",  "unknown"),
        "overall_vibe":      chunks[0].get("overall_vibe",  "unknown"),
        "key_moments": [], "segments": [], "best_segments": [],
    }
    for c in chunks:
        merged["key_moments"]   += c.get("key_moments",   [])
        merged["segments"]      += c.get("segments",      [])
        merged["best_segments"] += c.get("best_segments", [])
    return merged


def merge_adjacent(segs: list, gap: float = 0.5, max_duration: float = 4.0) -> list:
    """
    Merge adjacent best_segments if they are ≤ gap seconds apart,
    but only if the merged result stays under max_duration.
    """
    if not segs:
        return segs
    segs   = sorted(segs, key=lambda s: s["start_sec"])
    merged = [segs[0].copy()]
    for seg in segs[1:]:
        new_end  = max(merged[-1]["end_sec"], seg["end_sec"])
        new_dur  = new_end - merged[-1]["start_sec"]
        gap_dist = seg["start_sec"] - merged[-1]["end_sec"]
        if gap_dist <= gap and new_dur <= max_duration:
            merged[-1]["end_sec"]  = new_end
            merged[-1]["reason"]  += " + " + seg["reason"]
            merged[-1]["priority"] = min(merged[-1]["priority"], seg.get("priority", 999))
        else:
            merged.append(seg.copy())
    return merged


def early_deduplicate_segments(segments: list) -> list:
    """
    Deduplicates segments within the same video.
    Collapses overlapping segments (overlap ratio > 0.3) or segments sharing the same
    location tag early, keeping the one with higher priority (lower priority number).
    """
    if not segments:
        return []
    
    # Sort by priority (lower value = higher priority), default to 999 if not set
    # If priorities are equal, sort by start_sec
    sorted_segs = sorted(
        segments,
        key=lambda s: (int(s.get("priority", 999) or 999), float(s.get("start_sec", 0.0)))
    )
    
    kept = []
    for seg in sorted_segs:
        is_duplicate = False
        seg_start = float(seg.get("start_sec", 0.0))
        seg_end = float(seg.get("end_sec", 0.0))
        seg_loc = seg.get("location_tag", "unknown").lower().strip()
        
        for k in kept:
            k_start = float(k.get("start_sec", 0.0))
            k_end = float(k.get("end_sec", 0.0))
            k_loc = k.get("location_tag", "unknown").lower().strip()
            
            # 1. Overlap Check
            ov = max(0.0, min(seg_end, k_end) - max(seg_start, k_start))
            sh = min(seg_end - seg_start, k_end - k_start)
            overlap_ratio = (ov / sh) if sh > 0.0 else 0.0
            
            # 2. Location Check (only if not 'unknown')
            same_location = (seg_loc != "unknown" and seg_loc == k_loc)
            
            if overlap_ratio > 0.3 or same_location:
                is_duplicate = True
                logging.info(
                    f"  ✂️ [Early Dedup] Collapsed segment [{seg_start:.1f}s–{seg_end:.1f}s, tag={seg_loc}] "
                    f"due to {'overlap (' + str(round(overlap_ratio,2)) + ')' if overlap_ratio > 0.3 else 'matching tag'} "
                    f"with kept segment [{k_start:.1f}s–{k_end:.1f}s, tag={k_loc}]."
                )
                break
                
        if not is_duplicate:
            kept.append(seg)
            
    # Return the kept segments sorted chronologically by start_sec
    return sorted(kept, key=lambda s: float(s.get("start_sec", 0.0)))


# ── Single Video Pipeline (runs in a thread) ───────────────────────────────────

def process_single_video(
    info: dict,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    audio_analysis: dict = None,
) -> dict:
    # Check cache first thread-safely
    with CACHE_LOCK:
        cache = load_cache()
    
    # Incorporate normalized directives into cache key to avoid cache collisions
    norm_directives = " ".join(directives.lower().split()) if directives else ""
    cache_key = f"{info['path']}_{info['duration_sec']}_{norm_directives}"
    if cache_key in cache:
        cached_val = cache[cache_key]
        # Validate if frame images actually exist on disk
        frames_exist = True
        for frame in cached_val.get("frame_meta", []):
            if not Path(frame.get("path", "")).exists():
                frames_exist = False
                break
        
        if frames_exist:
            logging.info(f"  ✓ [CACHE HIT] Loading cached analysis for {info['path']}")
            return cached_val
        else:
            logging.info(f"  ⚠️  [CACHE HIT] Analysis cached, but timeline frame images are missing on disk for {info['path']}. Regenerating frames...")
            dur          = info["duration_sec"]
            chunk_window = CONFIG["chunk_window_sec"]
            overlap      = CONFIG["chunk_overlap_sec"]
            all_frame_meta = []
            
            if dur <= chunk_window:
                n_frames = pick_frame_count(dur)
                all_frame_meta = extract_representative_frames(
                    info["path"], dur, n_frames, offset_sec=0.0, chunk_label=""
                )
            else:
                starts = []
                t = 0.0
                while t < dur:
                    starts.append(t)
                    t += chunk_window - overlap
                for ci, start in enumerate(starts):
                    window = min(chunk_window, dur - start)
                    if window < 1.0:
                        break
                    label = f"chunk{ci:02d}"
                    n_frames = pick_frame_count(window)
                    fm = extract_representative_frames(
                        info["path"], window, n_frames, offset_sec=start, chunk_label=label
                    )
                    all_frame_meta += fm
            
            # Update frame_meta in cached value and update cache
            cached_val["frame_meta"] = all_frame_meta
            with CACHE_LOCK:
                cache = load_cache()
                cache[cache_key] = cached_val
                save_cache(cache)
            logging.info(f"  ✓ Re-extracted {len(all_frame_meta)} frame(s) successfully for {info['path']}.")
            return cached_val

    dur          = info["duration_sec"]
    chunk_window = CONFIG["chunk_window_sec"]
    overlap      = CONFIG["chunk_overlap_sec"]
    all_frame_meta = []

    logging.info(f"\n▶ {info['path']} ({dur:.1f}s)")

    if dur <= chunk_window:
        fm, parsed     = analyze_window(info, 0.0, dur, api_key, video_quality_map,
                                        reference_paths=reference_paths, audio_analysis=audio_analysis,directives=directives)
        parsed         = auto_recover_segments(parsed)
        all_frame_meta = fm
        chunk_analyses = [parsed]
    else:
        starts = []
        t = 0.0
        while t < dur:
            starts.append(t)
            t += chunk_window - overlap
        logging.info(f"   Chunked into {len(starts)} windows of ~{chunk_window}s")
        chunk_analyses = []
        for ci, start in enumerate(starts):
            window = min(chunk_window, dur - start)
            if window < 1.0:
                break
            label = f"chunk{ci:02d}"
            logging.info(f"   Chunk {ci+1}/{len(starts)}: [{start:.1f}s–{start+window:.1f}s]")
            fm, parsed = analyze_window(info, start, window, api_key, video_quality_map,
                                        chunk_label=label, reference_paths=reference_paths, audio_analysis=audio_analysis,directives=directives)
            parsed = auto_recover_segments(parsed)
            parsed = offset_segments(parsed, start)
            all_frame_meta += fm
            chunk_analyses.append(parsed)
        parsed = merge_chunk_analyses(chunk_analyses, dur)

    # Removed early dedup so that all candidate segments make it to the UI library
    parsed["best_segments"] = merge_adjacent(parsed.get("best_segments", []))
    parsed["best_segments"] = clamp_segments(parsed.get("best_segments", []), dur)
    parsed["segments"]      = clamp_segments(parsed.get("segments",      []), dur)

    # Attach black-frame warning to each best_segment using extracted frames
    for seg in parsed.get("best_segments", []):
        relevant_frames = [
            f for f in all_frame_meta
            if seg["start_sec"] <= f["abs_timestamp"] <= seg["end_sec"]
        ]
        seg["black_frame_warning"] = is_likely_black_clip(relevant_frames)

    is_fb = "[FALLBACK]" in parsed.get("video_summary", "")
    tag   = "⚠️  FALLBACK" if is_fb else "✓ Done"
    logging.info(f"  {tag}: {info['path']}  ({len(parsed.get('best_segments', []))} best segments)")

    res = {
        "video_path":   info["path"],
        "duration_sec": dur,
        "frame_meta":   all_frame_meta,
        "analysis":     parsed,
        "n_chunks":     len(chunk_analyses),
    }

    with CACHE_LOCK:
        cache = load_cache()
        cache[cache_key] = res
        save_cache(cache)

    return res


# ── Full Analysis Orchestrator ─────────────────────────────────────────────────

def run_full_analysis(
    video_infos: list,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    use_uploaded_order: bool = False,
    progress_callback = None,
    audio_analysis: dict = None,
    beat_windows: list = None,
) -> list:
    """
    Run process_single_video for all videos in parallel, then build final
    ordered best_segments list with story ordering.
    """
    pipeline_start_time = time.time()

    logging.info(f"\n{'='*60}")
    logging.info(f"Analyzing {len(video_infos)} video(s) in parallel...")
    logging.info(f"{'='*60}")

    max_workers = min(len(video_infos) or 1, CONFIG.get("max_parallel_vision_calls", 3))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(process_single_video, info, api_key, video_quality_map, reference_paths, audio_analysis,directives)
            for info in video_infos
        ]
        import concurrent.futures
        all_results = []
        for future in concurrent.futures.as_completed(futures):
            all_results.append(future.result())
            if progress_callback:
                progress_callback()

    best_segments = []
    for video_idx, result in enumerate(all_results):
        segs = sorted(result["analysis"].get("best_segments", []),
                      key=lambda s: float(s.get("start_sec", 0)))
        for seg in segs:
            # Programmatic quality guard: Reject segments that are too blurry to prevent AI hallucinations
            q_data = video_quality_map.get(result["video_path"], {})
            samples = q_data.get("samples", [])
            is_blurry_segment = False
            if samples and not result.get("is_image", False):
                seg_samples = [s for s in samples if float(seg.get("start_sec", 0)) <= s["t"] <= float(seg.get("end_sec", 0))]
                if seg_samples:
                    avg_blur = sum(s.get("blur_raw", 1000.0) for s in seg_samples) / len(seg_samples)
                    if avg_blur < 45.0:
                        logging.info(f"  ⏭  Programmatically rejected segment [{seg.get('start_sec')}s–{seg.get('end_sec')}s] "
                                     f"from {Path(result['video_path']).name} due to excessive blur (avg raw blur: {avg_blur:.2f} < 45.0)")
                        is_blurry_segment = True
            
            if is_blurry_segment:
                continue

            constructed_seg = {
                "video_path":         result["video_path"],
                "video_idx":          video_idx,
                "video_duration_sec": result["duration_sec"],
                "video_summary":      result["analysis"].get("video_summary",  ""),
                "overall_mood":       result["analysis"].get("overall_mood",   ""),
                "overall_vibe":       result["analysis"].get("overall_vibe",   ""),
                "editor_reasoning":   result["analysis"].get("editor_reasoning", ""),
                "start_sec":          seg.get("start_sec"),
                "end_sec":            seg.get("end_sec"),
                "reason":             seg.get("reason"),
                "priority":           seg.get("priority"),
                "camera_rotation":    seg.get("camera_rotation", 0),
                "narrative_role":     seg.get("narrative_role",         "unknown"),
                "scenario_rule":      seg.get("scenario_rule_applied",  ""),
                "location_tag":       seg.get("location_tag",           "unknown"),
                "journey_phase":      seg.get("journey_phase",          "unknown"),
                "time_of_day":        seg.get("time_of_day",            "unknown"),
                "black_frame_warning": seg.get("black_frame_warning",   False),
                "is_image":           result.get("is_image", False),
                "scene_category":     seg.get("scene_category", "mixed"),
                "primary_subjects":   seg.get("primary_subjects", []),
                "what_happens":       seg.get("what_happens", ""),
                "mood":               seg.get("mood", ""),
            }
            constructed_seg["ai_score"] = calculate_alignment_score(constructed_seg, directives)
            best_segments.append(constructed_seg)

    # ── Same-video dedup: allow multiple highlights from the same long video if different locations ──
    # If the clips from the same source video do not overlap, have different location tags,
    # and are separated by a sufficient time gap (at least 3.0s), we allow keeping them.
    # We allow up to 3 clips for long videos (> 30s) and up to 2 clips for shorter videos.
    def deduplicate_by_source_video(segments: list) -> list:
        from collections import defaultdict
        by_video = defaultdict(list)
        for seg in segments:
            by_video[seg["video_path"]].append(seg)
        kept = []
        for path, clips in by_video.items():
            if len(clips) <= 1:
                kept.extend(clips)
                continue
            
            # Sort by priority (lower = better)
            sorted_clips = sorted(clips, key=lambda s: int(s.get("priority", 999) or 999))
            
            # Dynamically determine the maximum clips allowed for this video based on duration
            first_clip = sorted_clips[0]
            video_dur = float(first_clip.get("video_duration_sec", 30.0))
            max_clips = 3 if video_dur > 30.0 else 2
            
            video_kept = [first_clip]
            for clip in sorted_clips[1:]:
                is_ok = True
                for k in video_kept:
                    # check overlap
                    ov = max(0, min(clip["end_sec"], k["end_sec"]) - max(clip["start_sec"], k["start_sec"]))
                    sh = min(clip["end_sec"] - clip["start_sec"], k["end_sec"] - k["start_sec"])
                    overlap_ratio = (ov / sh) if sh > 0 else 0
                    
                    # check time gap (distance between segments)
                    clip_start, clip_end = float(clip["start_sec"]), float(clip["end_sec"])
                    k_start, k_end = float(k["start_sec"]), float(k["end_sec"])
                    gap = max(clip_start, k_start) - min(clip_end, k_end)
                    
                    # If they overlap or have a gap smaller than 2.0s, reject
                    if overlap_ratio > 0.3 or gap < 2.0:
                        is_ok = False
                        break

                    # Check semantic/visual similarity to detect near-identical frames/shots
                    clip_loc = clip.get("location_tag", "unknown").lower().strip()
                    k_loc = k.get("location_tag", "unknown").lower().strip()
                    clip_cat = clip.get("scene_category", "mixed").lower().strip()
                    k_cat = k.get("scene_category", "mixed").lower().strip()
                    
                    if clip_loc != "unknown" and clip_loc == k_loc:
                        # Stricter deduplication: If it's the exact same video AND the AI 
                        # gave it the exact same location tag, check if their primary subjects 
                        # are different enough to warrant keeping both.
                        subs_clip = {s.lower().strip() for s in clip.get("primary_subjects", [])}
                        subs_k = {s.lower().strip() for s in k.get("primary_subjects", [])}
                        if subs_clip and subs_k:
                            intersection = subs_clip & subs_k
                            union = subs_clip | subs_k
                            jaccard = len(intersection) / len(union) if union else 0.0
                            # If they share less than 60% of their subjects, keep both
                            if jaccard < 0.6:
                                continue
                        is_ok = False
                        break
                        
                    if clip_cat != "unknown" and clip_cat == k_cat:
                        # Also check description / reason overlap if categories match but location tags differ
                        desc_clip = (clip.get("what_happens", "") or clip.get("reason", "")).lower()
                        desc_k = (k.get("what_happens", "") or k.get("reason", "")).lower()
                        stop_words = {"the", "a", "an", "on", "in", "of", "and", "or", "to", "for", "with", "at", "by", "from"}
                        words_clip = {w.strip(",.!?\"'") for w in desc_clip.split() if len(w) > 2 and w not in stop_words}
                        words_k = {w.strip(",.!?\"'") for w in desc_k.split() if len(w) > 2 and w not in stop_words}
                        
                        desc_overlap = 0.0
                        if words_clip and words_k:
                            desc_overlap = len(words_clip & words_k) / min(len(words_clip), len(words_k))
                            
                        if desc_overlap >= 0.3:
                            is_ok = False
                            break
                if is_ok and len(video_kept) < max_clips:
                    video_kept.append(clip)
            kept.extend(video_kept)
        return kept

    # ── Deduplicate by location tag ─────────────────────────────────────────
    # If different source videos share the same location_tag, they might be showing completely different angles, times of day, or subject interactions (e.g. sunset silhouette vs. regular walk).
    # Therefore, we group by location tag but keep the best clip per unique source video!
    def deduplicate_by_location(segments: list) -> list:
        # We don't want to limit to a single best clip per video path here,
        # as deduplicate_by_source_video already handles filtering within the same video
        # while respecting time gaps, overlaps, and priority.
        return segments

    # ── Overlap Deduplication Helper ─────────────────────────────────────────
    def overlaps(a, b):
        if a["video_path"] != b["video_path"]:
            return False
        ov = max(0, min(a["end_sec"], b["end_sec"]) - max(a["start_sec"], b["start_sec"]))
        sh = min(a["end_sec"] - a["start_sec"], b["end_sec"] - b["start_sec"])
        return sh > 0 and (ov / sh) > 0.5

    # ── Identify selected segments via copy-filtering ─────────────────────────
    survived = list(best_segments)
    survived = deduplicate_by_source_video(survived)
    survived = deduplicate_by_location(survived)

    deduped = []
    for seg in survived:
        dup = False
        for existing in deduped:
            if overlaps(seg, existing):
                if (seg.get("priority") or 999) < (existing.get("priority") or 999):
                    deduped.remove(existing)
                    break
                else:
                    dup = True
                    break
        if not dup:
            deduped.append(seg)
    survived = deduped

    # ── Focus Filtering & Re-ranking ──
    focus = parse_focus_directive(directives)
    if focus.get("type"):
        logging.info(f"  🎯 Focus Weighting / Subject Focus active: {focus}")
        
    def get_focus_sort_key(seg):
        if not focus or not focus.get("type"):
            return 0
        if focus["type"] == "weight":
            cat = focus["category"]
            is_match = str(seg.get("scene_category")).lower().strip() == cat
            return 0 if is_match else 1
        elif focus["type"] == "subject":
            subject_keywords = focus["subject"].lower().split()
            subjects = " ".join(seg.get("primary_subjects", [])).lower()
            what_happens = str(seg.get("what_happens") or "").lower()
            reason = str(seg.get("reason") or "").lower()
            score = sum(kw in subjects for kw in subject_keywords) * 2
            score += sum(kw in what_happens for kw in subject_keywords)
            score += sum(kw in reason for kw in subject_keywords)
            return -score
        return 0

    # ── Duration budget ─────────────────────────────────────────────────────
    MAX_REEL_SEC = CONFIG.get("max_reel_sec", 60)
    total = 0.0
    kept  = []
    for seg in sorted(survived, key=lambda s: (
                        get_focus_sort_key(s),
                        int(s.get("priority", 999) or 999),
                        float(s.get("end_sec", 0)) - float(s.get("start_sec", 0)))):
        dur = float(seg["end_sec"]) - float(seg["start_sec"])
        if total + dur <= MAX_REEL_SEC or not kept:
            kept.append(seg)
            total += dur
        else:
            logging.info(f"  ⏭  Dropped (budget): {seg['video_path']} {seg['start_sec']}s–{seg['end_sec']}s")
    survived = kept
    logging.info(f"Duration budget: {total:.1f}s reel from {len(survived)} survived clips out of {len(best_segments)} total")

    # Mark survived items as is_used = True (others remain False)
    survived_keys = {(s["video_path"], s["start_sec"], s["end_sec"]) for s in survived}
    for seg in best_segments:
        if (seg["video_path"], seg["start_sec"], seg["end_sec"]) in survived_keys:
            seg["is_used"] = True
        else:
            seg["is_used"] = False

    # ── Temporal Pre-sorting or Uploaded Order Sorting ────────────────────────
    if use_uploaded_order:
        logging.info("  📂 Sorting clips strictly by uploaded file order...")
        survived = sorted(
            survived,
            key=lambda s: (int(s.get("video_idx", 0)), float(s.get("start_sec", 0.0)))
        )
    else:
        TIME_ORDER = {
            "dawn": 0, "morning": 1, "afternoon": 2, "day": 2, "midday": 2,
            "golden_hour": 3, "sunset": 3, "dusk": 4, "evening": 4, "night": 5, "unknown": 6
        }
        def sort_by_temporal_flow(segments):
            return sorted(
                segments,
                key=lambda s: (
                    TIME_ORDER.get(s.get("time_of_day", "unknown"), 6),
                    int(s.get("priority", 999) or 999)
                )
            )
        survived = sort_by_temporal_flow(survived)

    # ── Story ordering (run only on survived clips) ─────────────────────────
    story_order = list(range(len(survived)))
    story_roles = ["clip"] * len(survived)
    story_reasoning = ""
    story_transitions = []
    story_transition_durations = []
    parsed_order = None

    if len(survived) >= 2 and not use_uploaded_order:
        logging.info("\nRequesting story order from model...")
        story_prompt = build_story_order_prompt(survived, all_results, directives, focus, audio_analysis, beat_windows)
        t0 = time.time()
        raw_order = None
        story_model = CONFIG.get("story_order_model", CONFIG["model"])
        try:
            raw_order    = call_openrouter_text(
                story_prompt,
                story_model,
                fallbacks=[CONFIG.get("story_order_fallback")] if "story_order_fallback" in CONFIG else None
            )
            duration = time.time() - t0
            parsed_order = parse_json_response(raw_order)
            log_story_order_call(
                model=story_model,
                prompt=story_prompt,
                raw_response=raw_order or "",
                parsed=parsed_order,
                parse_error=None,
                duration_sec=duration,
            )
            # ── Handle Beat Assignments (if present) ──
            if parsed_order and "beat_assignments" in parsed_order and beat_windows:
                logging.info(f"  [Pipeline] Applying {len(parsed_order['beat_assignments'])} beat window assignments from LLM...")
                clean_order = []
                clean_roles = []
                seen = set()
                
                # We sort the beat assignments by window_index to ensure chronological flow
                assignments = sorted(parsed_order["beat_assignments"], key=lambda x: x.get("window_index", 0))
                
                for assignment in assignments:
                    idx = assignment.get("clip_index")
                    w_idx = assignment.get("window_index")
                    
                    if isinstance(idx, int) and 0 <= idx < len(survived) and idx not in seen:
                        window = next((w for w in beat_windows if w["window_index"] == w_idx), None)
                        if window:
                            clean_order.append(idx)
                            clean_roles.append("assigned")
                            seen.add(idx)
                            
                            # Trim the original segment strictly to match the assigned window duration
                            seg = survived[idx]
                            orig_start = float(seg.get("start_sec", 0.0))
                            win_dur = float(window["duration"])
                            
                            seg["end_sec"] = orig_start + win_dur
                            seg["story_role"] = assignment.get("reason", "assigned")
                            seg["_beat_window_start"] = window["start_sec"]
                            seg["_beat_window_end"] = window["end_sec"]
                            seg["_beat_snapped"] = True
                            
                # Append any remaining clips that the LLM missed but we want to keep
                missing = [i for i in range(len(survived)) if i not in seen]
                if missing:
                    logging.info(f"  ⚠️  Story order: LLM missed indices {missing} — appending them at end")
                    for idx in missing:
                        clean_order.append(idx)
                        clean_roles.append("build")

                if clean_order:
                    story_order = clean_order
                    story_roles = clean_roles
                    story_reasoning = parsed_order.get('reasoning', '')
                    logging.info(f"Beat assignments processed. Resulting order: {story_order}")
                else:
                    logging.info("Beat assignments resulted in no usable clips. Keeping original.")
                    
            else:
                # ── Handle traditional Order ──
                order = parsed_order.get("order", [])
                roles = parsed_order.get("roles", [])
            llm_transitions = parsed_order.get("transitions", [])
            llm_durations = parsed_order.get("transition_durations", [])

                n = len(survived)
                seen = set()
                clean_order = []
                clean_roles = []
                for pos, idx in enumerate(order):
                    if isinstance(idx, int) and 0 <= idx < n and idx not in seen:
                        clean_order.append(idx)
                        clean_roles.append(roles[pos] if pos < len(roles) else "build")
                        seen.add(idx)
                    else:
                        logging.info(f"  ⚠️  Story order: dropping invalid/duplicate index {idx}")

                missing = [i for i in range(n) if i not in seen]
                if missing:
                    logging.info(f"  ⚠️  Story order: LLM missed indices {missing} — appending them at end")
                    for idx in missing:
                        clean_order.append(idx)
                        clean_roles.append("build")

                if clean_order:
                    story_order = clean_order
                    story_roles = clean_roles
                    story_reasoning = parsed_order.get('reasoning', '')
                story_transitions = llm_transitions
                story_transition_durations = llm_durations
                    logging.info(f"Story order: {story_order}")
                    logging.info(f"Roles:       {story_roles}")
                    logging.info(f"Reasoning:   {story_reasoning}")
                if story_transitions:
                    logging.info(f"LLM Transitions: {story_transitions}")
                else:
                    logging.info(f"Story order: LLM returned no usable indices — keeping original.")
        except Exception as e:
            duration = time.time() - t0
            log_story_order_call(
                model=story_model,
                prompt=story_prompt,
                raw_response=raw_order or "",
                parsed=None,
                parse_error=str(e),
                duration_sec=duration,
            )
            logging.info(f"Story ordering failed ({e}), keeping original order.")

    # ── Apply story ordering to survived clips ───────────────────────────────
    ordered_survived = []
    actually_used_keys = set()
    for position, seg_idx in enumerate(story_order):
        seg = survived[seg_idx].copy()
        seg["is_used"]        = True
        seg["story_position"] = position
        
        # Adjust segment timings for professional pacing and visual storytelling
        loc_lower = str(seg.get("location_tag", "")).lower()
        desc_lower = str(seg.get("what_happens", "")).lower()
        subjs_lower = " ".join([str(s).lower() for s in seg.get("primary_subjects", [])])
        combined_text = f"{loc_lower} {desc_lower} {subjs_lower}"

        start = float(seg["start_sec"])
        end = float(seg["end_sec"])
        duration = end - start
        video_dur = float(seg.get("video_duration_sec", 999.0))

        # Check if the segment is high-energy action
        is_action = any(kw in combined_text for kw in ["pool", "swim", "water", "action", "ping", "pong", "tennis", "play", "jump", "active", "splash", "game"])
        # Check if it is a slow/atmospheric beauty shot (temple, candles, sunset, reflection)
        is_slow = any(kw in combined_text for kw in ["sunset", "candle", "temple", "serene", "calm", "reflection", "slow", "beauty", "scenery", "night"])

        if is_action:
            # High-energy active footage: fast, dynamic, exactly 1.5 - 2.0s
            target_dur = min(2.0, max(1.5, duration))
            target_end = min(video_dur, start + target_dur)
            seg["end_sec"] = round(target_end, 2)
        elif is_slow:
            # Slower atmospheric beauty shots: let it linger for 3.0 - 4.0s (up to max available)
            target_dur = max(3.0, min(4.0, duration))
            target_end = min(video_dur, start + target_dur)
            seg["end_sec"] = round(target_end, 2)
        else:
            # Standard clips: capped at 3.0 seconds
            if duration > 3.0:
                seg["end_sec"] = round(start + 3.0, 2)

        if seg["end_sec"] <= seg["start_sec"] + 0.1:
            seg["end_sec"] = round(seg["start_sec"] + 0.1, 2)
        
        # Enforce logical roles based on position: hook at index 0, payoff at the end
        role = story_roles[position] if position < len(story_roles) else "build"
        if position == 0:
            role = "hook"
        elif position == len(story_order) - 1:
            role = "payoff"
        elif role in ("hook", "payoff"):
            role = "build"
            
        seg["story_role"]     = role
        if position == 0 and story_reasoning:
            seg["global_story_reasoning"] = story_reasoning

        # Attach transition metadata if present and within range
        if position < len(story_order) - 1:
            if story_transitions and position < len(story_transitions):
                seg["next_transition"] = story_transitions[position]
            if story_transition_durations and position < len(story_transition_durations):
                try:
                    seg["next_transition_duration"] = float(story_transition_durations[position])
                except (ValueError, TypeError):
                    pass
            
        ordered_survived.append(seg)
        actually_used_keys.add((seg["video_path"], seg["start_sec"], seg["end_sec"]))

    def enforce_no_consecutive_same_source(ordered_segs):
        """Only prevent clips from the exact same source video file appearing back-to-back."""
        segs = list(ordered_segs)
        changed = True
        passes = 0
        while changed and passes < 3:
            changed = False
            passes += 1
            for i in range(1, len(segs)):
                prev_src = segs[i-1].get("video_path", "")
                curr_src = segs[i].get("video_path", "")
                if prev_src == curr_src:
                    # Find a non-adjacent swap partner
                    for j in range(i + 1, len(segs)):
                        if segs[j].get("video_path", "") != prev_src:
                            segs[i], segs[j] = segs[j], segs[i]
                            changed = True
                            break
        return segs

    # Disable the same-source swap post-processing because it scrambles the contiguous scene/location 
    # groupings generated by the LLM (which are key for focus weighting and keeping birthday clips together).
    # ordered_survived = enforce_no_consecutive_same_source(ordered_survived)
    for position, seg in enumerate(ordered_survived):
        seg["story_position"] = position

    # ── Append unused/duplicate clips at the end ─────────────────────────────
    # This includes clips rejected by hard deduplication AND clips rejected by the Story LLM
    unused = []
    for seg in best_segments:
        if (seg["video_path"], seg["start_sec"], seg["end_sec"]) not in actually_used_keys:
            seg_copy = seg.copy()
            seg_copy["is_used"]        = False
            seg_copy["story_position"] = len(ordered_survived) + len(unused)
            seg_copy["story_role"]     = "clip"
            unused.append(seg_copy)

    ordered = ordered_survived + unused

    write_run_summary(
        all_results=all_results,
        final_segments=ordered,
        story_parsed=parsed_order,
        total_duration_sec=time.time() - pipeline_start_time,
    )

    return ordered, all_results


# ── Single Manual Segment Analyzer ────────────────────────────────────────────

def build_single_segment_prompt(video_path: str, start_sec: float, end_sec: float, duration: float) -> str:
    return f"""You are a precise video analyst for a short-form reel editor.

CRITICAL INSTRUCTION FOR REASONING AND THINKING:
Keep your internal thinking process (the reasoning path before outputting JSON) extremely short, concise, and direct (maximum 3-4 sentences total). Do not write long explanations or redundant descriptions. Summarize your thoughts immediately and output the final JSON object.

Analyze this specific video segment from {start_sec}s to {end_sec}s (duration: {duration:.2f}s).

The frames provided are in chronological order from within this segment.

Analyze the visual content of this segment and return ONLY a valid JSON object with the following fields:
{{
  "journey_phase": "string — one of: approach | arrival | exterior | interior | detail | departure | cruise | unknown",
  "location_tag": "string — short canonical name for this physical location, e.g. 'flight_screen', 'airplane_window', 'airport_view'",
  "narrative_role": "string — setup / action / climax / reaction / payoff / establishing_shot",
  "overall_mood": "string — e.g. 'Serene, aspirational'",
  "overall_vibe": "string — e.g. 'Travel, sunset flight'",
  "reason": "string — a compelling 1-sentence description of why this specific moment is visually strong or interesting",
  "scenario_rule": "string — scenario description, e.g. 'Scenario B: Hand reaches for airplane window'",
  "video_summary": "string — a 1-2 sentence descriptive summary of exactly what is happening in this segment"
}}

Rules:
- Do not include markdown, code fences, or any text outside the JSON object.
- Keep the response extremely precise and accurate to the actual frames shown.
"""

def analyze_single_segment(video_path: str, start_sec: float, end_sec: float, api_key: str) -> dict:
    """
    Directly extracts frames for a single timeline clip window,
    sends a focused vision request to the LLM, and returns the analyzed fields.
    """
    duration = max(0.1, end_sec - start_sec)
    
    # Extract 3 representative frames for this precise window
    frame_meta = extract_representative_frames(
        video_path, duration, frames_per_video=3,
        offset_sec=start_sec, chunk_label="manual_analysis"
    )
    
    if not frame_meta:
        raise ValueError("Could not extract frames for the selected segment.")
        
    payload_images = [f["path"] for f in frame_meta]
    prompt = build_single_segment_prompt(video_path, start_sec, end_sec, duration)
    
    raw = call_openrouter_multiimage(payload_images, prompt, CONFIG["model"])
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Parsed JSON is not a dictionary")
    if "journey_phase" not in parsed or "location_tag" not in parsed:
        raise ValueError("Parsed JSON is missing 'journey_phase' or 'location_tag' key")
    
    # Attach safety fields
    parsed["black_frame_warning"] = is_likely_black_clip(frame_meta)
    return parsed

import tempfile
import os
import shutil
import logging
from sqlalchemy.future import select
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.domain import Project, AnalysisJob, AnalyzedClip, JobStatus
from app.services.storage_service import storage_service

@celery_app.task(bind=True)
def analyze_video_project(self, project_id: str, job_id: str, media_assets: list, directives: str = "", vibe: str = "cinematic", music_config: dict = None):
    import uuid
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.core.config import settings

    job_uuid = uuid.UUID(job_id)
    project_uuid = uuid.UUID(project_id)

    # Create engine and loop INSIDE the task to prevent any sharing across forks or loops
    task_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
    TaskSessionLocal = async_sessionmaker(task_engine, expire_on_commit=False)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _update_progress(p: int, status: JobStatus = None, error: str = None):
        async with TaskSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == job_uuid))
            job = result.scalar_one_or_none()
            if job:
                job.progress = p
                if status:
                    job.status = status
                if error:
                    job.error_message = error
                await db.commit()

    def update_progress(p: int, status: JobStatus = None, error: str = None):
        loop.run_until_complete(_update_progress(p, status, error))

    # Query project to check for custom audio file
    async def _get_project_audio():
        async with TaskSessionLocal() as db:
            result = await db.execute(select(Project).filter(Project.id == project_uuid))
            proj = result.scalar_one_or_none()
            if proj:
                return proj.audio_object_key, proj.audio_filename
            return None, None

    audio_object_key, audio_filename = loop.run_until_complete(_get_project_audio())

    try:
        update_progress(5, JobStatus.RUNNING)
        from app.services.logger_service import init_run_log_dir
        init_run_log_dir(project_id, job_id)
        logging.info(f"  🎬 [Pipeline] Starting analysis | vibe={vibe!r} | directives={directives!r}")

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            import requests
            import threading
            video_paths = []
            
            update_progress(10)
            from app.services.storage_service import storage_service
            for idx, asset in enumerate(media_assets):
                ext = asset.get('file_name', '').split('.')[-1]
                if not ext:
                    ext = 'mp4'
                local_path = os.path.join(tmpdir, f"asset_{idx}.{ext}")
                presigned = storage_service.generate_presigned_url(asset["storage_path"])
                r = requests.get(presigned)
                
                if r.status_code != 200:
                    logging.error(f"  ❌ Failed to download {asset.get('file_name', 'unknown')} (status={r.status_code}) from MinIO. Is the file missing?")
                    continue
                    
                with open(local_path, "wb") as f:
                    f.write(r.content)
                
                # DEBUG
                file_size = os.path.getsize(local_path)
                logging.info(f"  📥 Downloaded {asset.get('file_name', 'unknown')} → {local_path} ({file_size} bytes, status={r.status_code})")
                
                video_paths.append(local_path)
                
            video_infos = []
            for vp in video_paths:
                info = get_video_info(vp)
                if info:
                    video_infos.append(info)

            # --- QUALITY ANALYSIS ---
            import sys
            from pathlib import Path
            root_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
            if root_dir not in sys.path:
                sys.path.append(root_dir)
            from quality import analyze_all_videos_quality
            video_quality_map = analyze_all_videos_quality(video_infos)
            # ------------------------

            # --- AUDIO PRE-ANALYSIS ---
            beat_map = None
            audio_analysis = None
            bgm_path_str = None
            
            try:
                # Ensure beat_sync is in search path
                beat_sync_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "beat_sync")
                if beat_sync_dir not in sys.path:
                    sys.path.insert(0, beat_sync_dir)
                if root_dir not in sys.path:
                    sys.path.insert(0, root_dir)
                
                from beat_sync.config import BGM_PATH, VERBOSE_LOGGING
                from beat_sync.audio_analyzer import analyze_bgm, extract_audio_energy_map, analyze_audio_hooks_with_llm, build_beat_windows
                
                if audio_object_key:
                    bgm_ext = audio_filename.split('.')[-1] if audio_filename else 'mp3'
                    bgm_local_path = os.path.join(tmpdir, f"custom_bgm.{bgm_ext}")
                    presigned_bgm = storage_service.generate_presigned_url(audio_object_key)
                    r_bgm = requests.get(presigned_bgm)
                    if r_bgm.status_code == 200:
                        with open(bgm_local_path, "wb") as f_bgm:
                            f_bgm.write(r_bgm.content)
                        bgm_path_str = bgm_local_path
                        logging.info(f"  📥 [BeatSync] Downloaded custom BGM: {audio_filename} ({os.path.getsize(bgm_path_str)} bytes)")
                    else:
                        logging.error(f"  ❌ [BeatSync] Failed to download custom BGM (status={r_bgm.status_code}). Falling back to default.")
                        
                if not bgm_path_str:
                    bgm_path_str = str(Path(BGM_PATH))
                    logging.info(f"  🎵 [BeatSync] Using default BGM: {Path(BGM_PATH).name}")
                
                bgm_start_sec = 0.0
                raw_hook_sec = 0.0
                chosen_hook = None
                all_hooks = []
                energy_map_data = []
                
                if Path(bgm_path_str).exists():
                    logging.info("  🎵 [BeatSync] Pre-analyzing BGM beats...")
                    beat_map = analyze_bgm(bgm_path_str, verbose=VERBOSE_LOGGING)
                    
                    logging.info("  🎵 [BeatSync] Running Nemotron audio energy hook analysis...")
                    energy_map_data = extract_audio_energy_map(bgm_path_str, num_bins=10)
                    audio_analysis = analyze_audio_hooks_with_llm(
                        song_name=Path(bgm_path_str).name,
                        bpm=beat_map.tempo_bpm,
                        duration=beat_map.total_duration_sec,
                        energy_map=energy_map_data
                    )
                    all_hooks = audio_analysis.get("hooks", []) if audio_analysis else []
                    
                    if audio_analysis and "hooks" in audio_analysis and audio_analysis["hooks"]:
                        hooks = audio_analysis["hooks"]
                        best_hook = next((h for h in hooks if h.get("energy_level") == "high"), hooks[0])
                        raw_start_sec = float(best_hook.get("start_sec", 0.0))
                        
                        # Snap the hook start time to the absolute nearest beat
                        if beat_map and beat_map.beat_times:
                            bgm_start_sec = min(beat_map.beat_times, key=lambda b: abs(b - raw_start_sec))
                        else:
                            bgm_start_sec = raw_start_sec
                            
                        logging.info(f"  🎵 [BeatSync] Setting BGM start offset to {bgm_start_sec}s (snapped to nearest beat from hook at {raw_start_sec}s)")
                        
                    logging.info("  🎵 [BeatSync] Audio hooks analysis complete.")
                    
                    # --- Build Beat Windows ---
                    beat_windows = []
                    if beat_map and beat_map.beat_times:
                        total_vid_dur = sum(v.get("duration_sec", 0) for v in video_infos)
                        # We limit the target duration to the total video available or 15s max reel length
                        target_dur = min(total_vid_dur, 15.0) 
                        
                        beat_windows = build_beat_windows(
                            beat_times=beat_map.beat_times,
                            bgm_start_sec=bgm_start_sec,
                            total_target_duration=target_dur,
                            min_dur_sec=1.0,
                            max_dur_sec=2.5,
                            energy_map=energy_map_data
                        )
                        logging.info(f"  🎵 [BeatSync] Computed {len(beat_windows)} beat windows for story ordering.")
                    
                else:
                    logging.warning(f"  ⚠️ [BeatSync] BGM file not found at: {bgm_path_str}")
            except Exception as _bs_init_err:
                logging.warning(f"  ⚠️ [BeatSync] Audio pre-analysis skipped: {_bs_init_err}")

            total = len(video_infos)
            completed = [0]
            lock = threading.Lock()
            def on_video_done():
                with lock:
                    completed[0] += 1
                    p = 10 + int((completed[0] / total) * 70) if total else 80
                    update_progress(p)

            try:
                final_segs, _all_results = run_full_analysis(
                    video_infos,
                    api_key=settings.NVIDIA_API_KEY,
                    video_quality_map=video_quality_map,
                    reference_paths=[],
                    directives=directives,
                    use_uploaded_order=False,
                    progress_callback=on_video_done,
                    audio_analysis=audio_analysis,
                    beat_windows=beat_windows if 'beat_windows' in locals() else None
                )
                
                update_progress(90)
                
                beat_sync_applied = False
                
                if beat_map:
                    try:
                        from beat_sync.config import SNAP_TOLERANCE_SEC, MIN_CLIP_DURATION_SEC, VERBOSE_LOGGING
                        from beat_sync.segment_snapper import snap_segments_to_beats
                        
                        logging.info("  🎵 [BeatSync] Snapping final segments to beats...")
                        snapped_segs = snap_segments_to_beats(
                            segments=final_segs,
                            beat_map=beat_map,
                            snap_tolerance_sec=SNAP_TOLERANCE_SEC,
                            min_clip_duration_sec=MIN_CLIP_DURATION_SEC,
                            verbose=VERBOSE_LOGGING,
                            bgm_offset_sec=bgm_start_sec
                        )
                        final_segs = snapped_segs
                        beat_sync_applied = True
                        
                        # Write detailed beat-sync log
                        try:
                            write_beat_sync_log(
                                bgm_path=bgm_path_str or "",
                                bgm_start_sec=bgm_start_sec,
                                raw_hook_sec=raw_hook_sec,
                                chosen_hook=chosen_hook,
                                all_hooks=all_hooks,
                                energy_map=energy_map_data,
                                tempo_bpm=beat_map.tempo_bpm,
                                beat_times=beat_map.beat_times,
                                snapped_segments=snapped_segs,
                            )
                        except Exception as _log_err:
                            logging.warning(f"  ⚠️ [BeatSync] Could not write beat sync log: {_log_err}")
                    except Exception as _snap_err:
                        logging.warning(f"  ⚠️ [BeatSync] Beat snapping skipped: {_snap_err}")
                
                async def _save_results(segs):
                    async with TaskSessionLocal() as db:
                        for idx, seg in enumerate(segs):
                            v_idx = int(seg.get("video_idx", 0))
                            m_asset = media_assets[v_idx] if v_idx < len(media_assets) else media_assets[0]
                            
                            clip = AnalyzedClip(
                                job_id=job_uuid,
                                media_asset_id=uuid.UUID(str(m_asset["id"])),
                                start_sec=float(seg.get("start_sec", 0.0)),
                                end_sec=float(seg.get("end_sec", 0.0)),
                                story_position=idx,
                                metadata_json=seg,
                                is_used=bool(seg.get("is_used", True))
                            )
                            db.add(clip)
                        await db.commit()
                
                loop.run_until_complete(_save_results(final_segs))
                
                # Stitch the segments into a final video summary
                logging.info("  🎬 [Pipeline] Generating final stitched video summary...")
                clips_dir = Path(tmpdir) / "clips"
                reel_path = Path(tmpdir) / "final_video.mp4"
                
                from app.services.stitch_service import build_reel_from_segments
                
                # Stitch the (possibly beat-snapped) final_segs
                build_reel_from_segments(final_segs, clips_dir, reel_path)
                
                if reel_path.exists():
                    logging.info("  📤 [Pipeline] Uploading final video to MinIO...")
                    object_key = f"projects/{project_id}/jobs/{job_id}/final_video.mp4"
                    with open(reel_path, "rb") as video_file:
                        storage_service.upload_file_obj(video_file, object_key, content_type="video/mp4")
                    logging.info(f"  ✅ [Pipeline] Final video uploaded to MinIO: {object_key}")
                else:
                    raise FileNotFoundError("Final video file was not created by stitcher.")
                
                update_progress(100, JobStatus.COMPLETED)
                
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                update_progress(0, JobStatus.FAILED, error=str(e))
                raise

    finally:
        loop.run_until_complete(task_engine.dispose())
        loop.close()

