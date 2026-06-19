import sys
import logging
import subprocess
import os
import json
from pathlib import Path
import tempfile
import uuid
import asyncio

from app.models.domain import AnalysisJob, AnalyzedClip, MediaAsset, JobStatus
from app.services.storage_service import storage_service
from app.core.config import settings
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

async def compose_video_project(job_id: str, TaskSessionLocal):
    """
    Physically composes the final video using FFmpeg based on the AI's timeline decisions.
    Downloads clips from MinIO, trims them, applies transitions, and uploads the final output.
    """
    logger.info(f"Starting rendering for job {job_id}")
    
    async with TaskSessionLocal() as db:
        from sqlalchemy import select
        # Load job with its clips and media assets
        stmt = select(AnalysisJob).options(
            selectinload(AnalysisJob.analyzed_clips).selectinload(AnalyzedClip.media_asset)
        ).filter(AnalysisJob.id == uuid.UUID(job_id))
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job:
            logger.error("Job not found")
            return False

        # Sort clips by story_position
        clips = sorted([c for c in job.analyzed_clips if c.is_used], key=lambda x: x.story_position)
        if not clips:
            logger.error("No used clips found in job.")
            return False
            
        project_id = str(job.project_id)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        processed_clips = []
        
        # 1. Download and normalize clips
        for idx, clip in enumerate(clips):
            m_asset = clip.media_asset
            if not m_asset:
                logger.warning(f"Clip {idx} missing media asset")
                continue
                
            object_key = m_asset.object_key
            logger.info(f"Downloading {object_key}...")
            
            raw_path = temp_dir_path / f"raw_{idx}.mp4"
            # Get presigned URL
            url = storage_service.generate_presigned_url(object_key)
            if not url:
                continue
            
            # Download using requests
            import requests
            try:
                resp = requests.get(url, stream=True)
                resp.raise_for_status()
                with open(raw_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            except Exception as e:
                logger.error(f"Failed to download {object_key}: {e}")
                continue
            
            # Trim and normalize
            trimmed_path = temp_dir_path / f"trimmed_{idx}.mp4"
            in_s = clip.start_sec
            out_s = clip.end_sec
            
            # Normalize to 1080x1920, 30fps, same audio rate to ensure concat/xfade works perfectly
            scale_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
            
            # Check if raw video has audio
            probe_a_cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(raw_path)]
            try:
                has_audio = bool(subprocess.check_output(probe_a_cmd, text=True).strip())
            except Exception:
                has_audio = False

            dur_s = float(out_s) - float(in_s)
            if dur_s <= 0.1:
                logger.warning(f"Clip {idx} duration too short: {dur_s}s. Skipping.")
                continue

            trim_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error"
            ]
            
            if not has_audio:
                # Provide a silent audio stream of the exact needed duration
                trim_cmd.extend(["-f", "lavfi", "-t", str(dur_s), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
                
            # Input the raw file, applying seek
            trim_cmd.extend(["-ss", str(in_s), "-to", str(out_s), "-i", str(raw_path)])
            
            if not has_audio:
                # 0 is anullsrc, 1 is raw_path
                trim_cmd.extend(["-map", "1:v:0", "-map", "0:a:0"])
            
            trim_cmd.extend([
                "-vf", scale_filter,
                "-c:v", "libx264", "-c:a", "aac",
                "-ar", "44100", "-ac", "2",
                "-crf", "18", "-preset", "superfast",
                str(trimmed_path)
            ])
            try:
                subprocess.run(trim_cmd, check=True)
                
                # Verify that the output actually has video and audio streams
                probe_streams_cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(trimmed_path)]
                streams_out = subprocess.check_output(probe_streams_cmd, text=True)
                streams_data = json.loads(streams_out)
                codec_types = [s.get("codec_type") for s in streams_data.get("streams", [])]
                
                if "video" not in codec_types or "audio" not in codec_types:
                    logger.error(f"Trimmed clip {idx} missing required streams (found {codec_types}). Skipping.")
                    continue

                # Get actual duration after trim
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(trimmed_path)]
                dur_out = subprocess.check_output(probe_cmd, text=True).strip()
                if dur_out == 'N/A' or not dur_out:
                    actual_dur = float(out_s) - float(in_s)
                else:
                    actual_dur = float(dur_out)
                
                meta = clip.metadata_json or {}
                t_out = meta.get("transition_out", "hard_cut")
                t_dur = float(meta.get("transition_duration", 0.0))
                # Fallback if AI chose transition but duration is 0
                if t_out != "hard_cut" and t_out != "cut" and t_dur <= 0:
                    t_dur = 0.5
                
                processed_clips.append({
                    "path": trimmed_path,
                    "duration": actual_dur,
                    "t_out": t_out,
                    "t_dur": t_dur
                })
                logger.info(f"Prepared clip {idx} ({actual_dur}s, transition: {t_out} for {t_dur}s)")
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg trim failed for clip {idx}: {e}")
                continue
        
        if not processed_clips:
            logger.error("No clips were successfully processed.")
            return False

        # 2. Build Filter Graph for xfade and concat
        output_path = temp_dir_path / "final_output.mp4"
        
        if len(processed_clips) == 1:
            # Just copy it
            import shutil
            shutil.copy(processed_clips[0]["path"], output_path)
        else:
            inputs = []
            filter_parts = []
            
            for i, pc in enumerate(processed_clips):
                inputs.extend(["-i", str(pc["path"])])
            
            current_v = "[0:v]"
            current_a = "[0:a]"
            current_time = processed_clips[0]["duration"]
            
            for i in range(1, len(processed_clips)):
                prev = processed_clips[i-1]
                curr = processed_clips[i]
                next_v = f"[{i}:v]"
                next_a = f"[{i}:a]"
                
                t_dur = prev["t_dur"]
                t_out = prev["t_out"]
                
                # If duration is 0 or it's a cut, xfade won't work well, but xfade duration must be > 0.
                if t_dur > 0 and t_out not in ["hard_cut", "cut"]:
                    # ensure t_dur doesn't exceed clip duration
                    t_dur = min(t_dur, prev["duration"]/2, curr["duration"]/2)
                    if t_dur < 0.1: t_dur = 0.1 # minimum valid
                    
                    offset = current_time - t_dur
                    v_out = f"[v{i}]"
                    a_out = f"[a{i}]"
                    
                    # Map styles directly to xfade
                    allowed_xfades = ["fade", "wipeleft", "wiperight", "slideleft", "slideright", "circlecrop", "rectcrop", "distance", "dissolve", "pixelize", "radial", "hblur", "zoomin", "fadeblack"]
                    fade_type = t_out if t_out in allowed_xfades else "fade"
                    
                    filter_parts.append(f"{current_v}settb=1/30[v_tb1_{i}];{next_v}settb=1/30[v_tb2_{i}];[v_tb1_{i}][v_tb2_{i}]xfade=transition={fade_type}:duration={t_dur}:offset={offset}{v_out}")
                    filter_parts.append(f"{current_a}{next_a}acrossfade=d={t_dur}{a_out}")
                    
                    current_v = v_out
                    current_a = a_out
                    current_time = current_time + curr["duration"] - t_dur
                else:
                    # Concat
                    v_out = f"[v{i}]"
                    a_out = f"[a{i}]"
                    filter_parts.append(f"{current_v}{next_v}concat=n=2:v=1:a=0{v_out}")
                    filter_parts.append(f"{current_a}{next_a}concat=n=2:v=0:a=1{a_out}")
                    
                    current_v = v_out
                    current_a = a_out
                    current_time = current_time + curr["duration"]

            filter_complex = ";".join(filter_parts)
            
            ffmpeg_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            ffmpeg_cmd.extend(inputs)
            ffmpeg_cmd.extend(["-filter_complex", filter_complex])
            ffmpeg_cmd.extend(["-map", current_v, "-map", current_a])
            ffmpeg_cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-crf", "18", str(output_path)])
            
            logger.info("Running FFmpeg composition...")
            try:
                subprocess.run(ffmpeg_cmd, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg composition failed: {e}")
                return False

        # 3. Upload to MinIO
        final_key = f"projects/{project_id}/final_reel_{job_id}.mp4"
        logger.info(f"Uploading final reel to MinIO: {final_key}")
        with open(output_path, "rb") as f:
            storage_service.upload_file_obj(f, final_key, content_type="video/mp4")
            
        # 4. Update Database
        async with TaskSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.final_video_key = final_key
                await db.commit()
                logger.info(f"Successfully saved final_video_key {final_key} to DB.")
                
        return True
