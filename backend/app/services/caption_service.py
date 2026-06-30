"""
Caption Service

Handles intelligent caption generation with line-by-line grouping (3-4 words per line)
and FFmpeg drawtext filter generation for word-perfect timing.
"""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class CaptionSegment:
    """Represents a caption line with timing"""
    text: str
    start_time: float
    end_time: float
    words: List[Dict]  # Individual words with their timestamps
    position_y: int = 1700  # Default bottom position

class CaptionService:
    """Handles smart caption generation and FFmpeg filter building"""
    
    def __init__(self):
        self.default_font_paths = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc", 
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        ]

    async def generate_line_captions(
        self, 
        words: List[Dict], 
        words_per_line: int = 4
    ) -> List[Dict]:
        """
        Generate line-by-line captions (CapCut style) from word timestamps
        
        Args:
            words: List of word objects with 'word', 'start', 'end' keys
            words_per_line: Target words per caption line
            
        Returns:
            List of caption segments with timing and text
        """
        if not words:
            return []
        
        caption_segments = []
        current_line_words = []
        
        for word_data in words:
            word_text = word_data["word"].strip()
            
            # Skip empty words
            if not word_text:
                continue
                
            current_line_words.append(word_data)
            
            # Check if we should end this line
            should_end_line = (
                len(current_line_words) >= words_per_line or
                self._is_natural_break(word_text) or
                self._has_pause_after(word_data, words)
            )
            
            if should_end_line:
                if current_line_words:
                    segment = self._create_caption_segment(current_line_words)
                    caption_segments.append(segment)
                    current_line_words = []
        
        # Handle remaining words
        if current_line_words:
            segment = self._create_caption_segment(current_line_words)
            caption_segments.append(segment)
        
        logger.info(f"Generated {len(caption_segments)} caption segments")
        return caption_segments

    def _create_caption_segment(self, words: List[Dict]) -> Dict:
        """Create a caption segment from a group of words"""
        if not words:
            return None
            
        # Combine words into text
        text_parts = []
        for word_data in words:
            word = word_data["word"].strip()
            # Clean up word (remove leading/trailing punctuation for better display)
            if word:
                text_parts.append(word)
        
        text = " ".join(text_parts)
        
        # Get timing from first and last word
        start_time = words[0]["start"]
        end_time = words[-1]["end"]
        
        return {
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
            "words": words,
            "duration": end_time - start_time
        }

    def _is_natural_break(self, word: str) -> bool:
        """Check if word ends with natural break punctuation"""
        return bool(re.search(r'[.!?,:;]$', word))

    def _has_pause_after(self, current_word: Dict, all_words: List[Dict]) -> bool:
        """Check if there's a natural pause after current word"""
        current_end = current_word["end"]
        
        # Find next word
        for word_data in all_words:
            if word_data["start"] > current_end:
                # If gap > 0.3 seconds, it's a natural pause
                gap = word_data["start"] - current_end
                return gap > 0.3
        
        return False

    def build_ffmpeg_caption_filters(
        self, 
        caption_segments: List[Dict], 
        options: Any
    ) -> str:
        """
        Build FFmpeg drawtext filters for captions
        
        Args:
            caption_segments: List of caption segments from generate_line_captions
            options: PodcastProcessingOptions with styling
            
        Returns:
            FFmpeg filter string for captions
        """
        if not caption_segments:
            return ""
        
        # Find available font
        font_file = self._find_available_font()
        
        # Build individual drawtext filters for each caption
        filters = []
        
        for i, segment in enumerate(caption_segments):
            text = segment["text"]
            start_time = segment["start_time"] 
            end_time = segment["end_time"]
            
            # Escape text for FFmpeg
            escaped_text = self._escape_text_for_ffmpeg(text)
            
            # Calculate position
            y_position = self._calculate_position(options.caption_position, options.font_size)
            
            # Build drawtext filter
            drawtext_parts = [
                f"text='{escaped_text}'",
                f"enable='between(t,{start_time:.3f},{end_time:.3f})'",
                f"x=(w-text_w)/2",  # Center horizontally
                f"y={y_position}",
                f"fontsize={options.font_size}",
                f"fontcolor={options.font_color}",
                "box=1",
                "boxcolor=black@0.7",
                "boxborderw=10"
            ]
            
            if font_file:
                drawtext_parts.insert(-3, f"fontfile='{font_file}'")
            
            filter_str = "drawtext=" + ":".join(drawtext_parts)
            filters.append(filter_str)
        
        # Combine all drawtext filters
        return ",".join(filters)

    def build_word_by_word_filters(
        self, 
        words: List[Dict], 
        options: Any
    ) -> str:
        """
        Build word-by-word karaoke-style captions
        
        For when user wants word-by-word highlighting instead of line-by-line
        """
        if not words:
            return ""
        
        font_file = self._find_available_font()
        filters = []
        
        y_position = self._calculate_position(options.caption_position, options.font_size)
        
        for word_data in words:
            word = word_data["word"].strip()
            if not word:
                continue
                
            start_time = word_data["start"]
            end_time = word_data["end"]
            
            escaped_word = self._escape_text_for_ffmpeg(word)
            
            drawtext_parts = [
                f"text='{escaped_word}'",
                f"enable='between(t,{start_time:.3f},{end_time:.3f})'",
                f"x=(w-text_w)/2",
                f"y={y_position}",
                f"fontsize={options.font_size}",
                f"fontcolor={options.font_color}",
                "box=1",
                "boxcolor=black@0.7",
                "boxborderw=8"
            ]
            
            if font_file:
                drawtext_parts.insert(-3, f"fontfile='{font_file}'")
            
            filter_str = "drawtext=" + ":".join(drawtext_parts)
            filters.append(filter_str)
        
        return ",".join(filters)

    def _find_available_font(self) -> Optional[str]:
        """Find first available font file on system"""
        import os
        for font_path in self.default_font_paths:
            if os.path.exists(font_path):
                return font_path
        return None

    def _escape_text_for_ffmpeg(self, text: str) -> str:
        """Escape text for FFmpeg drawtext filter"""
        # Order matters — escape backslashes first
        text = text.replace("\\", "\\\\")
        # Apostrophes/single quotes are the most dangerous — they break the filter chain
        # Replace with Unicode right single quotation mark (looks identical)
        text = text.replace("'", "\u2019")
        text = text.replace(":", "\\:")
        text = text.replace("%", "\\%")
        text = re.sub(r'[\n\r\t]', ' ', text)
        return text

    def _calculate_position(self, position: str, font_size: int) -> int:
        """Calculate Y position for captions based on position setting"""
        if position == "top":
            return 100
        elif position == "center": 
            return "h/2"
        else:  # bottom (default)
            return f"h-{font_size + 50}"  # Font size + padding from bottom

    async def generate_srt_file(self, caption_segments: List[Dict]) -> str:
        """
        Generate SRT subtitle file from caption segments
        
        Returns:
            SRT file content as string
        """
        srt_content = []
        
        for i, segment in enumerate(caption_segments, 1):
            start_time = segment["start_time"]
            end_time = segment["end_time"] 
            text = segment["text"]
            
            # Format timestamps for SRT (HH:MM:SS,mmm)
            start_srt = self._format_srt_timestamp(start_time)
            end_srt = self._format_srt_timestamp(end_time)
            
            # SRT format: number, timestamps, text, blank line
            srt_content.extend([
                str(i),
                f"{start_srt} --> {end_srt}",
                text,
                ""
            ])
        
        return "\n".join(srt_content)

    def _format_srt_timestamp(self, seconds: float) -> str:
        """Format seconds to SRT timestamp format (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"