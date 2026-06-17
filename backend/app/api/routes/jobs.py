from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
import uuid
import io

from app.core.database import get_db
from app.models.domain import Project, AnalysisJob, AnalyzedClip, JobStatus
from app.services.pipeline_service import analyze_video_project
from app.services.storage_service import storage_service
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

router = APIRouter()

class AnalyzeRequest(BaseModel):
    directives: str = ""

class JobStatusResponse(BaseModel):
    id: str
    project_id: str
    status: JobStatus
    progress: int
    error_message: Optional[str] = None
    created_at: str

class AnalyzedClipResponse(BaseModel):
    id: str
    media_asset_id: str
    start_sec: float
    end_sec: float
    story_position: int
    metadata_json: Dict[str, Any]
    url: Optional[str] = None

@router.post("/projects/{project_id}/analyze", response_model=JobStatusResponse)
async def start_analysis_job(
    project_id: uuid.UUID,
    request: AnalyzeRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        project_result = await db.execute(
            select(Project)
            .options(selectinload(Project.media_assets))
            .filter(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not project.media_assets:
            raise HTTPException(status_code=400, detail="Project has no media assets")

        job = AnalysisJob(
            project_id=project_id,
            status=JobStatus.PENDING,
            progress=0
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Convert assets to dicts for Celery serialization
        assets_data = [
            {
                "id": str(asset.id),
                "file_name": asset.filename,
                "storage_path": asset.object_key,
            }
            for asset in project.media_assets
        ]

        analyze_video_project.delay(
            project_id=str(project_id),
            job_id=str(job.id),
            media_assets=assets_data,
            directives=request.directives
        )

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            created_at=str(job.created_at)
        )
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        job_result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            created_at=str(job.created_at)
        )
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))

@router.get("/projects/{project_id}/timeline", response_model=List[AnalyzedClipResponse])
async def get_project_timeline(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Find the most recent completed job
    job_result = await db.execute(
        select(AnalysisJob)
        .filter(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.created_at.desc())
    )
    job = job_result.scalars().first()
    
    if not job:
        raise HTTPException(status_code=404, detail="No completed analysis job found for this project")

    # Get clips ordered by story_position, with their associated media_asset
    clips_result = await db.execute(
        select(AnalyzedClip)
        .options(selectinload(AnalyzedClip.media_asset))
        .filter(AnalyzedClip.job_id == job.id)
        .order_by(AnalyzedClip.story_position.asc())
    )
    clips = clips_result.scalars().all()

    return [
        AnalyzedClipResponse(
            id=str(c.id),
            media_asset_id=str(c.media_asset_id),
            start_sec=c.start_sec,
            end_sec=c.end_sec,
            story_position=c.story_position or 0,
            metadata_json=c.metadata_json or {},
            url=storage_service.generate_presigned_url(c.media_asset.object_key) if c.media_asset else None
        )
        for c in clips
    ]

@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: uuid.UUID):
    """Return a list of all log files for this job."""
    try:
        response = storage_service.s3_client.list_objects_v2(
            Bucket=storage_service.llm_logs_bucket,
            Prefix=f"logs/llm/{job_id}/"
        )
        files = [
            obj["Key"].split("/")[-1]
            for obj in response.get("Contents", [])
        ]
        return {"job_id": str(job_id), "files": sorted(files)}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/jobs/{job_id}/logs/view")
async def view_job_log_summary(job_id: uuid.UUID):
    """Stream the SUMMARY.txt log file directly in the browser as plain text."""
    object_key = f"logs/llm/{job_id}/SUMMARY.txt"
    return await _stream_log_file(job_id, object_key)

@router.get("/jobs/{job_id}/logs/view/{filename}")
async def view_job_log_file(job_id: uuid.UUID, filename: str):
    """Stream any specific log file directly in the browser as plain text."""
    # Sanitize filename - only allow alphanumeric, underscore, dash, dot
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    object_key = f"logs/llm/{job_id}/{safe}"
    return await _stream_log_file(job_id, object_key)

async def _stream_log_file(job_id: uuid.UUID, object_key: str) -> Response:
    try:
        obj = storage_service.s3_client.get_object(
            Bucket=storage_service.llm_logs_bucket,
            Key=object_key
        )
        content = obj["Body"].read().decode("utf-8")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": "inline"}
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Log file not found: {object_key}")
