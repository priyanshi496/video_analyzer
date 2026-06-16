import os

# Fix macOS Objective-C threading crash during multiprocessing fork
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "video_analyzer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.api.routes.jobs", "app.services.pipeline_service"] # Define modules where tasks are found
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
