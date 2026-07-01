"""
Celery tasks for podcast video processing.

DB writes use psycopg2 directly (sync) to avoid asyncpg event-loop conflicts.
The podcast pipeline itself runs in one fresh event loop per task.
"""

import logging
import tempfile
import os
import asyncio
import json
from pathlib import Path
from typing import Dict, Any

from app.core.celery_app import app
from app.services.podcast_service import podcast_service, PodcastProcessingOptions
from app.services.storage_service import storage_service
from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Sync DB helpers (psycopg2, no asyncpg) ───────────────────────────────────

def _get_sync_conn():
    """Open a plain psycopg2 connection from the async DATABASE_URL."""
    import psycopg2
    # Convert  postgresql+asyncpg://user:pass@host:port/db
    #      →   postgresql://user:pass@host:port/db
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def _set_status_sync(job_id: str, status_value: str, progress: int, message: str = None):
    """Write job status synchronously via psycopg2."""
    try:
        conn = _get_sync_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE analysis_jobs
               SET status        = %s,
                   progress      = %s,
                   error_message = %s
             WHERE id = %s::uuid
            """,
            (status_value, progress, message, job_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Job {job_id}: {status_value} {progress}%")
    except Exception as e:
        logger.error(f"_set_status_sync failed: {e}")


def _save_metadata_sync(job_id: str, processing_result: Dict[str, Any]):
    """Write processing metadata synchronously via psycopg2."""
    try:
        text = processing_result["transcript"]["text"]
        metadata = {
            "transcript_summary": {
                "text": text[:500] + ("..." if len(text) > 500 else ""),
                "language": processing_result["transcript"]["language"],
                "duration": processing_result["transcript"]["duration"],
                "word_count": len(processing_result["transcript"]["words"]),
            },
            "caption_segments":  processing_result["caption_segments"],
            "important_moments": processing_result["important_moments"],
            "zoom_effects":      processing_result["zoom_effects"],
            "processing_options":processing_result["processing_options"],
            "final_video_url":   processing_result["video_url"],
        }
        conn = _get_sync_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE analysis_jobs SET metadata_json = %s WHERE id = %s::uuid",
            (json.dumps(metadata), job_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Metadata saved for job {job_id}")
    except Exception as e:
        logger.error(f"_save_metadata_sync failed: {e}")


# ── Async pipeline (runs in one dedicated loop) ───────────────────────────────

async def _run_pipeline(
    job_id: str,
    video_storage_path: str,
    processing_options: Dict[str, Any],
):
    """Full podcast pipeline in one async context. No DB calls here — those are sync."""
    loop = asyncio.get_running_loop()

    # Download video (sync storage call → thread pool)
    logger.info(f"Downloading: {video_storage_path}")
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        video_path = f.name
    await loop.run_in_executor(
        None, storage_service.download_file, video_storage_path, video_path
    )
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        raise RuntimeError(f"Empty download for {video_storage_path}")

    with tempfile.NamedTemporaryFile(suffix='_final.mp4', delete=False) as f:
        output_path = f.name

    try:
        options = PodcastProcessingOptions(**processing_options)
        result = await podcast_service.process_podcast_video(
            job_id=job_id,
            video_path=video_path,
            output_path=output_path,
            options=options,
        )
        return result
    finally:
        Path(video_path).unlink(missing_ok=True)
        Path(output_path).unlink(missing_ok=True)


# ── Celery task ───────────────────────────────────────────────────────────────

@app.task(bind=True, name="process_podcast_video")
def process_podcast_video_task(
    self,
    job_id: str,
    project_id: str,
    video_storage_path: str,
    processing_options: Dict[str, Any],
):
    _set_status_sync(job_id, "RUNNING", 5)

    try:
        # Run async pipeline in a fresh isolated loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _run_pipeline(job_id, video_storage_path, processing_options)
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        _save_metadata_sync(job_id, result)
        _set_status_sync(job_id, "COMPLETED", 100)

        logger.info(f"Podcast job {job_id} COMPLETED ✓")
        return {
            "job_id": job_id,
            "status": "completed",
            "final_video_url": result.get("video_url"),
            "transcript_summary": result["transcript"]["text"][:200],
        }

    except Exception as e:
        logger.error(f"Podcast job {job_id} FAILED: {e}")
        _set_status_sync(job_id, "FAILED", 0, f"Podcast processing failed: {e}")
        raise
