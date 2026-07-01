import os
import sys

# Prepend local bin containing static FFmpeg/FFprobe with drawtext support to PATH
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
local_bin = os.path.join(base_dir, "bin")
os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

# Fix macOS Objective-C threading crash during multiprocessing fork
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# pyrefly: ignore [missing-import]
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "video_analyzer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.api.routes.jobs", 
        "app.services.pipeline_service",
        "app.tasks.podcast_tasks"  # Add podcast tasks
    ] # Define modules where tasks are found
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Export app for tasks to use
app = celery_app
