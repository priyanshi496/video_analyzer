"""
Podcast Video Processing Service

Handles the complete pipeline for talking-head video processing:
1. Whisper transcription with word timestamps
2. Smart caption generation (3-4 words per line)
3. LLM-based important moment detection
4. Auto-zoom effects on key moments
5. Final video rendering with captions + zoom effects
"""

import logging
import asyncio
import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import subprocess
import uuid
from dataclasses import dataclass

from app.services.transcription_service import TranscriptionService
from app.services.caption_service import CaptionService
from app.services.moment_detection_service import MomentDetectionService
from app.services.zoom_effects_service import ZoomEffectsService
from app.services.storage_service import storage_service
from app.core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class PodcastProcessingOptions:
    """Configuration options for podcast processing"""
    caption_style: str = "line_by_line"  # "word_by_word" or "line_by_line"
    words_per_line: int = 4
    zoom_detection: str = "auto_llm"     # "auto_llm" or "manual"
    zoom_intensity: float = 1.3          # 1.0x to zoom_intensity scale
    caption_position: str = "bottom"     # "bottom", "top", "center"
    font_size: int = 48
    font_color: str = "white"
    background_blur: bool = True

class PodcastService:
    """Main orchestrator for podcast video processing"""
    
    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.caption_service = CaptionService()
        self.moment_detection_service = MomentDetectionService()
        self.zoom_effects_service = ZoomEffectsService()

    async def process_podcast_video(
        self, 
        job_id: str,
        video_path: str, 
        output_path: str,
        options: PodcastProcessingOptions = None
    ) -> Dict[str, Any]:
        """
        Complete podcast video processing pipeline
        
        Returns:
            Dict containing processing results, transcript, captions, zoom markers
        """
        if options is None:
            options = PodcastProcessingOptions()
            
        logger.info(f"Starting podcast processing for job {job_id}")
        
        try:
            # Step 1: Extract audio from video
            audio_path = await self._extract_audio(video_path)
            
            # Step 2: Transcribe with Whisper (word-level timestamps)
            logger.info("Step 2: Transcribing audio with Whisper...")
            transcript_result = await self.transcription_service.transcribe_with_timestamps(
                audio_path, job_id
            )
            
            # Step 3: Generate smart captions (3-4 words per line)
            logger.info("Step 3: Generating smart captions...")
            caption_segments = await self.caption_service.generate_line_captions(
                transcript_result["words"], 
                options.words_per_line
            )
            
            # Step 4: Detect important moments with LLM
            logger.info("Step 4: Detecting important moments with LLM...")
            important_moments = await self.moment_detection_service.find_key_moments(
                transcript_result["text"],
                transcript_result["words"]
            )
            
            # Step 5: Apply keyword highlights to captions for important moments
            logger.info("Step 5: Applying keyword highlights to captions...")
            caption_segments = self.caption_service.apply_keyword_highlights(
                caption_segments,
                important_moments,
                highlight_color="#FFD60A"  # Yellow highlight for emphasis
            )
            
            # Zoom effects disabled - keeping only keyword highlighting
            zoom_effects = []
            
            # Step 6: Render final video with captions + zoom
            logger.info("Step 6: Rendering final video...")
            final_video_path = await self._render_final_video(
                video_path=video_path,
                output_path=output_path,
                caption_segments=caption_segments,
                zoom_effects=zoom_effects,
                options=options
            )
            
            # Step 7: Upload to storage and clean up
            final_video_key = f"podcast_outputs/{job_id}/final_video.mp4"
            final_video_url = await self._upload_file(final_video_path, final_video_key)
            
            # Clean up temporary files
            Path(audio_path).unlink(missing_ok=True)
            Path(final_video_path).unlink(missing_ok=True)
            
            # Return complete results
            result = {
                "job_id": job_id,
                "video_url": final_video_url,
                "transcript": transcript_result,
                "caption_segments": caption_segments,
                "important_moments": important_moments,
                "zoom_effects": zoom_effects,
                "processing_options": options.__dict__
            }
            
            logger.info(f"Podcast processing completed successfully for job {job_id}")
            return result
            
        except Exception as e:
            logger.error(f"Podcast processing failed for job {job_id}: {str(e)}")
            raise

    async def _extract_audio(self, video_path: str) -> str:
        """Extract audio track from video using FFmpeg"""
        audio_path = f"/tmp/audio_{uuid.uuid4()}.wav"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",  # no video
            "-acodec", "pcm_s16le",  # 16-bit PCM for Whisper
            "-ar", "16000",  # 16kHz sample rate
            "-ac", "1",      # mono
            audio_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown FFmpeg error"
            raise Exception(f"Failed to extract audio: {error_msg}")
            
        logger.info(f"Audio extracted to {audio_path}")
        return audio_path

    async def _render_final_video(
        self,
        video_path: str,
        output_path: str,
        caption_segments: List[Dict],
        zoom_effects: List[Dict],
        options: PodcastProcessingOptions
    ) -> str:
        """Render final video with captions + zoompan zoom."""

        # Probe video dimensions and fps for zoompan s= parameter
        probe = await self._probe_video(video_path)
        w, h, fps = probe["width"], probe["height"], probe["fps"]

        # Caption drawtext filters
        caption_filter = self.caption_service.build_ffmpeg_caption_filters(
            caption_segments, options
        )

        # Zoom disabled - no zoom filter applied
        vf = caption_filter if caption_filter else None

        cmd = ["ffmpeg", "-y", "-i", video_path]
        if vf:
            cmd += ["-vf", vf]
        cmd += [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",           # audio untouched → perfect sync
            "-movflags", "+faststart",
            output_path,
        ]

        logger.info(f"FFmpeg render: {len(caption_segments)} captions (zoom disabled), {w}x{h}@{fps}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown FFmpeg error"
            raise Exception(f"Failed to render video: {error_msg}")

        logger.info(f"Final video rendered to {output_path}")
        return output_path

    async def _probe_video(self, video_path: str) -> dict:
        """Get width, height, fps from video using ffprobe."""
        import json as _json
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-select_streams", "v:0",
            video_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        s = (_json.loads(stdout.decode()).get("streams") or [{}])[0]
        w = int(s.get("width", 720))
        h = int(s.get("height", 1280))
        fps_raw = s.get("r_frame_rate", "24/1")
        try:
            num, den = fps_raw.split("/")
            fps = round(int(num) / int(den))
        except Exception:
            fps = 24
        logger.info(f"Probed video: {w}x{h} @ {fps}fps")
        return {"width": w, "height": h, "fps": fps}

    def _build_zoom_filter(
        self, hold_kfs: List[Dict], max_zoom: float,
        video_w: int, video_h: int, fps: int
    ) -> str:
        """
        Precomputed per-frame zoom — NOT a live zoompan math expression.

        WHY: zoompan recomputes crop window from a string expression every
        frame. Even with trunc()/eased ramps, this produces visible
        jitter on real video (confirmed via testing — multiple ease
        durations, trunc() pixel snapping, and 2x-fps smoothing all
        tried, jitter persisted or caused stalls).

        APPROACH (inspired by CapCut's own keyframe model — two values,
        time range, engine interpolates): we compute the EXACT zoom
        level for every single output frame in Python using a proper
        cubic ease-in-out curve, then bake those values into the
        zoompan expression as a discrete lookup via nested if/between
        on a PER-FRAME basis rather than a continuous formula. This
        removes floating point expression evaluation jitter because
        every frame's zoom value is a fixed, pre-rounded constant
        instead of a live computed fraction.

        For long videos this can produce a long filter string (one
        if-branch per ease frame) — acceptable for podcast clips up to
        a few minutes. If filter strings get unwieldy on very long
        videos, switch to the file-based per-frame crop list approach
        instead (see _build_zoom_filter_v2_lut below, not yet wired in).
        """
        if not hold_kfs:
            return ""

        MIN_ZOOM = 1.15
        MAX_ZOOM = 1.3
        ease_seconds = 0.8  # Shorter ease = fewer frames = simpler expression
        ease_frames = max(1, int(ease_seconds * fps))

        def ease_in_out_cubic(t: float) -> float:
            """Smooth cubic ease — t in [0,1], returns eased [0,1]."""
            if t < 0.5:
                return 4 * t * t * t
            p = 2 * t - 2
            return 1 + p * p * p / 2

        # Build a frame -> zoom_value lookup table for every frame that
        # needs a non-default (non-1.0) zoom value.
        frame_zoom: Dict[int, float] = {}

        for kf in hold_kfs:
            s_fr = max(0, int(kf["start_time"] * fps))
            e_fr = int(kf["end_time"] * fps)
            z = round(min(max(max(kf["zoom_start"], kf["zoom_end"]), MIN_ZOOM), MAX_ZOOM), 3)

            half_window = max(1, (e_fr - s_fr) // 2)
            ef = min(ease_frames, half_window)

            ease_in_end    = s_fr + ef
            ease_out_start = e_fr - ef

            # Ramp up: frames [s_fr, ease_in_end)
            for i, frame in enumerate(range(s_fr, ease_in_end)):
                t = i / max(1, ef)
                eased_t = ease_in_out_cubic(t)
                frame_zoom[frame] = round(1.0 + (z - 1.0) * eased_t, 3)

            # Hold: frames [ease_in_end, ease_out_start)
            for frame in range(ease_in_end, ease_out_start):
                frame_zoom[frame] = z

            # Ramp down: frames [ease_out_start, e_fr]
            for i, frame in enumerate(range(ease_out_start, e_fr + 1)):
                t = i / max(1, ef)
                eased_t = ease_in_out_cubic(t)
                frame_zoom[frame] = round(z - (z - 1.0) * eased_t, 3)

        if not frame_zoom:
            return ""

        # Collapse consecutive identical values into ranges to keep the
        # filter string manageable (huge win: cubic easing means many
        # adjacent frames round to the same 3-decimal value).
        sorted_frames = sorted(frame_zoom.keys())
        ranges: List[Tuple[int, int, float]] = []  # (start_frame, end_frame, value)
        range_start = sorted_frames[0]
        range_val   = frame_zoom[range_start]
        prev_frame  = range_start

        for frame in sorted_frames[1:]:
            val = frame_zoom[frame]
            if frame == prev_frame + 1 and val == range_val:
                prev_frame = frame
                continue
            ranges.append((range_start, prev_frame, range_val))
            range_start = frame
            range_val   = val
            prev_frame  = frame
        ranges.append((range_start, prev_frame, range_val))

        logger.info(
            f"Precomputed zoom: {len(hold_kfs)} windows -> "
            f"{len(frame_zoom)} raw frames collapsed to {len(ranges)} ranges "
            f"(ease={ease_seconds}s cubic, min={MIN_ZOOM} max={MAX_ZOOM})"
        )

        # Build nested if/between expression from the collapsed ranges.
        # Each range is now a FIXED constant value, not a live formula —
        # this is the key difference from the old approach, which
        # recomputed (on-s_fr)/ef as a live division every frame.
        zoom_expr = "1.0"
        for s_fr, e_fr, val in reversed(ranges):
            zoom_expr = f"if(between(on,{s_fr},{e_fr}),{val},{zoom_expr})"

        return (
            f"zoompan=z='{zoom_expr}'"
            f":x='trunc(iw/2-(iw/zoom/2))'"
            f":y='trunc(ih/2-(ih/zoom/2))'"
            f":d=1"
            f":s={video_w}x{video_h}"
            f":fps={fps}"
        )

    async def _upload_file(self, local_path: str, storage_key: str) -> str:
        """Upload a local file to storage and return its presigned URL"""
        with open(local_path, "rb") as f:
            import io
            content = f.read()
            file_obj = io.BytesIO(content)
            storage_service.upload_file_obj(file_obj, storage_key, content_type="video/mp4")
        return storage_service.generate_presigned_url(storage_key)

    async def get_transcript_by_job_id(self, job_id: str) -> Optional[Dict]:
        """Get transcript data for a specific job"""
        try:
            transcript_key = f"transcripts/{job_id}/transcript.json"
            return storage_service.download_json(transcript_key)
        except Exception as e:
            logger.error(f"Failed to get transcript for job {job_id}: {str(e)}")
            return None

    async def regenerate_captions(
        self, 
        job_id: str, 
        words: List[Dict], 
        options: PodcastProcessingOptions
    ) -> List[Dict]:
        """Regenerate captions with different options"""
        return await self.caption_service.generate_line_captions(
            words, options.words_per_line
        )


# Global instance
podcast_service = PodcastService()