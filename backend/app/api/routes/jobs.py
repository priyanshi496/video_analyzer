from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
import uuid

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
    error_message: str | None = None
    created_at: str

class AnalyzedClipResponse(BaseModel):
    id: str
    media_asset_id: str
    start_sec: float
    end_sec: float
    story_position: int
    metadata_json: Dict[str, Any]

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

    # Get clips ordered by story_position
    clips_result = await db.execute(
        select(AnalyzedClip)
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
            metadata_json=c.metadata_json or {}
        )
        for c in clips
    ]

@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: uuid.UUID):
    # Retrieve the presigned url for the SUMMARY.txt log
    object_key = f"logs/llm/{job_id}/SUMMARY.txt"
    presigned = storage_service.generate_presigned_url(object_key, bucket=storage_service.llm_logs_bucket)
    if not presigned:
        raise HTTPException(status_code=404, detail="Log not found")
    return {"url": presigned}
