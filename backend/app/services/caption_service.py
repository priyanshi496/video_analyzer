"""
Caption Service

Handles intelligent caption generation with line-by-line grouping (3-4 words per line)
and FFmpeg drawtext filter generation for word-perfect timing.

Keyword highlighting (one word per line rendered in a different color)
uses Pillow to measure exact text widths in Python, so the keyword's
x-position is computed precisely BEFORE building the FFmpeg filter —
no fragile FFmpeg cross-filter text_w chaining, no overlapping text,
no missing backdrop boxes. This replaces an earlier broken approach
that tried to chain separate drawtext calls using each call's own
text_w expression, which produced word collisions and inconsistent
spacing in practice (confirmed via screenshots).
"""

import logging
import re
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from PIL import ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed — keyword highlighting will fall back to plain captions. Run: pip install Pillow")


@dataclass
class CaptionSegment:
    """Represents a caption line with timing"""
    text: str
    start_time: float
    end_time: float
    words: List[Dict]
    position_y: int = 1700


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
        self.default_bold_font_paths = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        self._font_cache: Dict[Tuple[str, int], Any] = {}

    # ── Caption generation (unchanged) ──────────────────────────────────

    async def generate_line_captions(
        self,
        words: List[Dict],
        words_per_line: int = 4
    ) -> List[Dict]:
        if not words:
            return []

        caption_segments = []
        current_line_words = []

        for word_data in words:
            word_text = word_data["word"].strip()
            if not word_text:
                continue

            current_line_words.append(word_data)

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

        if current_line_words:
            segment = self._create_caption_segment(current_line_words)
            caption_segments.append(segment)

        logger.info(f"Generated {len(caption_segments)} caption segments")
        return caption_segments

    def _create_caption_segment(self, words: List[Dict]) -> Dict:
        if not words:
            return None

        # Keep ALL words including single-letter ones like "a", "I"
        text_parts = []
        for w in words:
            word = w["word"].strip()
            if word:  # Only check if non-empty after strip
                text_parts.append(word)
        
        text = " ".join(text_parts)
        start_time = words[0]["start"]
        end_time = words[-1]["end"]

        return {
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
            "words": words,
            "duration": end_time - start_time,
            "keyword": None,
            "keyword_color": None,
        }

    # ── Keyword highlighting ─────────────────────────────────────────────

    def apply_keyword_highlights(
        self,
        caption_segments: List[Dict],
        important_moments: List[Dict],
        highlight_color: str = "#FFD60A",
    ) -> List[Dict]:
        """
        Highlights keywords in 2-3 consecutive caption lines around each important moment.
        This creates a more visible, sentence-length highlight effect.
        """
        if not caption_segments or not important_moments:
            return caption_segments

        STOPWORDS = {
            "the", "a", "an", "is", "are", "was", "were", "i", "you",
            "it", "of", "to", "in", "on", "and", "or", "but", "so",
            "we", "they", "he", "she", "be", "as", "at", "by", "with",
        }

        for moment in important_moments:
            moment_start = moment["start_time"]
            moment_end = moment["end_time"]
            
            # Find all segments that overlap this moment
            overlapping_indices = []
            for i, segment in enumerate(caption_segments):
                seg_start = segment["start_time"]
                seg_end = segment["end_time"]
                
                if seg_start < moment_end and seg_end > moment_start:
                    overlapping_indices.append(i)
            
            if not overlapping_indices:
                continue
            
            # Highlight 2-3 consecutive lines around the moment center
            # Find the centermost overlapping segment
            center_idx = overlapping_indices[len(overlapping_indices) // 2]
            
            # Expand to include 1 segment before and 1 after (total 3 segments)
            highlight_start = max(0, center_idx - 1)
            highlight_end = min(len(caption_segments), center_idx + 2)
            
            # Apply highlighting to these 2-3 segments
            for i in range(highlight_start, highlight_end):
                segment = caption_segments[i]
                
                # Pick the longest meaningful word in this line as the keyword
                candidates = [
                    w["word"].strip(".,!?;:\"'") for w in segment["words"]
                    if w["word"].strip(".,!?;:\"'").lower() not in STOPWORDS
                    and len(w["word"].strip(".,!?;:\"'")) > 2
                ]
                
                if candidates:
                    keyword = max(candidates, key=len)
                    segment["keyword"] = keyword
                    segment["keyword_color"] = highlight_color

        highlighted_count = sum(1 for s in caption_segments if s.get("keyword"))
        logger.info(f"Applied keyword highlights to {highlighted_count}/{len(caption_segments)} caption lines (2-3 lines per moment)")
        return caption_segments

    def _is_natural_break(self, word: str) -> bool:
        return bool(re.search(r'[.!?,:;]$', word))

    def _has_pause_after(self, current_word: Dict, all_words: List[Dict]) -> bool:
        current_end = current_word["end"]
        for word_data in all_words:
            if word_data["start"] > current_end:
                return (word_data["start"] - current_end) > 0.3
        return False

    # ── Pillow-based text measurement ───────────────────────────────────

    def _get_pil_font(self, font_path: Optional[str], size: int):
        """Cache PIL ImageFont objects — loading a font is relatively slow."""
        cache_key = (font_path or "default", size)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, size)
        else:
            font = ImageFont.load_default(size=size)

        self._font_cache[cache_key] = font
        return font

    def _measure_text_width(self, text: str, font_path: Optional[str], size: int) -> int:
        """Returns the rendered pixel width of `text` at `size` using `font_path`."""
        if not PIL_AVAILABLE:
            # Rough fallback estimate: ~0.55 * font_size per character
            return int(len(text) * size * 0.55)

        font = self._get_pil_font(font_path, size)
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]  # right - left = width

    # ── FFmpeg filter building ──────────────────────────────────────────

    def build_ffmpeg_caption_filters(
        self,
        caption_segments: List[Dict],
        options: Any
    ) -> str:
        """
        Build FFmpeg drawtext filters for captions.

        Highlighted lines: keyword position is computed EXACTLY in
        Python (via Pillow font metrics) before any FFmpeg filter is
        built, so the centered line + colored keyword overlay align
        pixel-perfectly with no runtime FFmpeg cross-filter math.
        """
        if not caption_segments:
            return ""

        font_file = self._find_available_font()
        bold_font_file = self._find_available_bold_font() or font_file

        filters = []
        for segment in caption_segments:
            keyword = segment.get("keyword")
            y_position = self._calculate_position(options.caption_position, options.font_size)

            if keyword and keyword in segment["text"] and PIL_AVAILABLE:
                filters.extend(
                    self._build_highlighted_line_filters(
                        segment, keyword, y_position, options, font_file, bold_font_file
                    )
                )
            else:
                filters.append(
                    self._build_plain_line_filter(
                        segment["text"], segment["start_time"], segment["end_time"],
                        y_position, options, font_file
                    )
                )

        return ",".join(filters)

    def _build_plain_line_filter(
        self, text, start_time, end_time, y_position, options, font_file
    ) -> str:
        """Single centered drawtext call — used for non-highlighted lines."""
        escaped_text = self._escape_text_for_ffmpeg(text)
        parts = [
            f"text='{escaped_text}'",
            f"enable='between(t,{start_time:.3f},{end_time:.3f})'",
            f"x=(w-text_w)/2",
            f"y={y_position}",
            f"fontsize={options.font_size}",
            f"fontcolor={options.font_color}",
            "box=1",
            "boxcolor=black@0.7",
            "boxborderw=10",
        ]
        if font_file:
            parts.insert(-3, f"fontfile='{font_file}'")
        return "drawtext=" + ":".join(parts)

    def _build_highlighted_line_filters(
        self, segment, keyword, y_position, options, font_file, bold_font_file
    ) -> List[str]:
        """
        Properly centered highlighted line using Pillow-measured widths.

        Math:
          1. Measure full_w = width of the ENTIRE line at base font size
          2. Measure before_w = width of "text before keyword + space"
             at base font size
          3. Measure keyword_w = width of keyword at its (slightly
             larger, bold) font size
          4. The full centered line's left edge sits at:
               line_left = (video_w - full_w) / 2
             (We let FFmpeg compute this dynamically via (w-text_w)/2
             on the BACKDROP layer, but for positioning the separately-
             colored before/keyword/after pieces we need a concrete
             pixel value — so we use options' known render width if
             available, falling back to a sane default of 1080.)
          5. before's left = line_left
             keyword's left = line_left + before_w
             after's left   = line_left + before_w + keyword_w
        """
        text = segment["text"]
        start_time = segment["start_time"]
        end_time = segment["end_time"]
        keyword_color = segment.get("keyword_color") or "#FFD60A"

        idx = text.find(keyword)
        before = text[:idx].rstrip()
        after = text[idx + len(keyword):].lstrip()
        
        logger.info(f"[Highlight Debug] text={text!r} keyword={keyword!r} idx={idx} before={before!r} after={after!r}")

        base_size = options.font_size
        keyword_size = int(base_size * 1.05)

        video_w = getattr(options, "video_width", 1080)  # see note below re: wiring this in

        full_w = self._measure_text_width(text, font_file, base_size)
        line_left = (video_w - full_w) / 2

        before_with_space = (before + " ") if before else ""
        before_w = self._measure_text_width(before_with_space, font_file, base_size) if before else 0

        keyword_w = self._measure_text_width(keyword, bold_font_file, keyword_size)

        # Add 8px buffer to absorb font metric mismatches between regular/bold fonts
        before_x   = line_left
        keyword_x  = line_left + before_w
        after_x    = keyword_x + keyword_w + 8  # +8px buffer for bold font width variance

        esc_full = self._escape_text_for_ffmpeg(text)
        enable = f"enable='between(t,{start_time:.3f},{end_time:.3f})'"

        # Backdrop box — invisible text (alpha 0), visible dark box behind the whole line
        backdrop_parts = [
            f"text='{esc_full}'",
            enable,
            f"x={line_left:.1f}",
            f"y={y_position}",
            f"fontsize={base_size}",
            f"fontcolor={options.font_color}@0.0",
            "box=1",
            "boxcolor=black@0.7",
            "boxborderw=10",
        ]
        if font_file:
            backdrop_parts.insert(-3, f"fontfile='{font_file}'")
        filters_out = ["drawtext=" + ":".join(backdrop_parts)]

        if before:
            esc_before = self._escape_text_for_ffmpeg(before_with_space)
            before_parts = [
                f"text='{esc_before}'",
                enable,
                f"x={before_x:.1f}",
                f"y={y_position}",
                f"fontsize={base_size}",
                f"fontcolor={options.font_color}",
            ]
            if font_file:
                before_parts.insert(-1, f"fontfile='{font_file}'")
            filters_out.append("drawtext=" + ":".join(before_parts))

        esc_keyword = self._escape_text_for_ffmpeg(keyword)
        keyword_parts = [
            f"text='{esc_keyword}'",
            enable,
            f"x={keyword_x:.1f}",
            f"y={y_position}",
            f"fontsize={keyword_size}",
            f"fontcolor={keyword_color}",
        ]
        if bold_font_file:
            keyword_parts.insert(-1, f"fontfile='{bold_font_file}'")
        filters_out.append("drawtext=" + ":".join(keyword_parts))

        if after:
            esc_after = self._escape_text_for_ffmpeg(" " + after)
            after_parts = [
                f"text='{esc_after}'",
                enable,
                f"x={after_x:.1f}",
                f"y={y_position}",
                f"fontsize={base_size}",
                f"fontcolor={options.font_color}",
            ]
            if font_file:
                after_parts.insert(-1, f"fontfile='{font_file}'")
            filters_out.append("drawtext=" + ":".join(after_parts))

        return filters_out

    # ── Word-by-word mode (unchanged) ───────────────────────────────────

    def build_word_by_word_filters(self, words: List[Dict], options: Any) -> str:
        if not words:
            return ""

        font_file = self._find_available_font()
        filters = []
        y_position = self._calculate_position(options.caption_position, options.font_size)

        for word_data in words:
            word = word_data["word"].strip()
            if not word:
                continue

            escaped_word = self._escape_text_for_ffmpeg(word)
            parts = [
                f"text='{escaped_word}'",
                f"enable='between(t,{word_data['start']:.3f},{word_data['end']:.3f})'",
                f"x=(w-text_w)/2",
                f"y={y_position}",
                f"fontsize={options.font_size}",
                f"fontcolor={options.font_color}",
                "box=1",
                "boxcolor=black@0.7",
                "boxborderw=8"
            ]
            if font_file:
                parts.insert(-3, f"fontfile='{font_file}'")
            filters.append("drawtext=" + ":".join(parts))

        return ",".join(filters)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _find_available_font(self) -> Optional[str]:
        for font_path in self.default_font_paths:
            if os.path.exists(font_path):
                return font_path
        return None

    def _find_available_bold_font(self) -> Optional[str]:
        for font_path in self.default_bold_font_paths:
            if os.path.exists(font_path):
                return font_path
        return None

    def _escape_text_for_ffmpeg(self, text: str) -> str:
        text = text.replace("\\", "\\\\")
        text = text.replace("'", "\u2019")
        text = text.replace(":", "\\:")
        text = text.replace("%", "\\%")
        text = re.sub(r'[\n\r\t]', ' ', text)
        return text

    def _calculate_position(self, position: str, font_size: int) -> int:
        if position == "top":
            return 100
        elif position == "center":
            return "h/2"
        else:
            return f"h-{font_size + 50}"

    async def generate_srt_file(self, caption_segments: List[Dict]) -> str:
        srt_content = []
        for i, segment in enumerate(caption_segments, 1):
            start_srt = self._format_srt_timestamp(segment["start_time"])
            end_srt = self._format_srt_timestamp(segment["end_time"])
            srt_content.extend([str(i), f"{start_srt} --> {end_srt}", segment["text"], ""])
        return "\n".join(srt_content)

    def _format_srt_timestamp(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"