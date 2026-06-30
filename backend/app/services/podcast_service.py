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
            
            # Step 5: Calculate zoom effects
            logger.info("Step 5: Calculating zoom effects...")
            zoom_effects = await self.zoom_effects_service.calculate_zoom_keyframes(
                important_moments,
                options.zoom_intensity
            )

            # Validate keyframes before rendering — catch bad data early
            issues = self.zoom_effects_service.validate_zoom_keyframes(zoom_effects)
            if issues:
                logger.warning(f"Zoom keyframe issues detected: {issues}")
                # Drop keyframes that would crash FFmpeg, keep the rest
                zoom_effects = [
                    kf for kf in zoom_effects
                    if kf.get("end_time", 0) > kf.get("start_time", 0)
                    and 0.5 <= kf.get("zoom_start", 1.0) <= 3.0
                ]
            
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

        # Zoom filter using zoompan with frame-number keying (confirmed working on FFmpeg 8.x)
        hold_kfs = [kf for kf in zoom_effects if kf.get("transition_type") == "hold"]
        zoom_filter = self._build_zoom_filter(hold_kfs, options.zoom_intensity, w, h, fps)

        # Assemble vf chain
        vf_parts = []
        if zoom_filter:
            vf_parts.append(zoom_filter)
        if caption_filter:
            vf_parts.append(caption_filter)
        vf = ",".join(vf_parts) if vf_parts else None

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

        logger.info(f"FFmpeg render: {len(hold_kfs)} zoom windows, {len(caption_segments)} captions, {w}x{h}@{fps}")

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
        zoompan-based zoom keyed on 'on' (output frame number).

        Anti-jitter fix: x/y wrapped in trunc() to force whole-pixel
        positions, removing sub-pixel rounding shake between frames.

        NOTE: an earlier version tried rendering zoompan at 2x internal
        fps then downsampling — this caused a buffer backlog/stall on
        real video (confirmed via FFmpeg "buffers queued" warning and
        render hang). Do NOT reintroduce that approach. Single-pass at
        native fps with trunc() is the stable, tested fix.

        Subtle zoom range (1.15x - 1.3x), eased ramp in/hold/out.
        """
        if not hold_kfs:
            return ""

        MIN_ZOOM = 1.15
        MAX_ZOOM = 1.3
        ease_seconds = 1.1
        ease_frames = max(1, int(ease_seconds * fps))

        zoom_expr = "1.0"
        for kf in reversed(hold_kfs):
            s_fr = max(0, int(kf["start_time"] * fps))
            e_fr = int(kf["end_time"] * fps)
            z = round(min(max(max(kf["zoom_start"], kf["zoom_end"]), MIN_ZOOM), MAX_ZOOM), 2)

            half_window = max(1, (e_fr - s_fr) // 2)
            ef = min(ease_frames, half_window)

            ease_in_end     = s_fr + ef
            ease_out_start  = e_fr - ef

            this_zoom = (
                f"if(between(on,{s_fr},{ease_in_end}),"
                    f"1.0+({z}-1.0)*(on-{s_fr})/{ef},"
                f"if(between(on,{ease_in_end},{ease_out_start}),"
                    f"{z},"
                f"if(between(on,{ease_out_start},{e_fr}),"
                    f"{z}-({z}-1.0)*(on-{ease_out_start})/{ef},"
                f"{zoom_expr})))"
            )
            zoom_expr = this_zoom

        logger.info(
            f"Eased zoom built ({len(hold_kfs)} windows, "
            f"{ease_frames}f ease @ {fps}fps native, "
            f"min={MIN_ZOOM} max={MAX_ZOOM})"
        )

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