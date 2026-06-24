from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional, Literal
import uuid
from sqlalchemy import or_

from app.core.database import get_db
from app.models.domain import Project, AnalysisJob, AnalyzedClip, JobStatus, User
from app.services.pipeline_service import analyze_video_project, continue_video_analysis
from app.services.storage_service import storage_service
from app.core.vibe_config import VibePreset
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.core.security import get_current_user

router = APIRouter()

class MusicRequest(BaseModel):
    mode: Literal["ai", "custom", "none", "suno"] = "ai"
    custom_query: Optional[str] = None      # e.g. "Satranga Arijit Singh"
    instrumental: bool = True

class AnalyzeRequest(BaseModel):
    vibe: VibePreset = VibePreset.CINEMATIC  # Preset vibe for the reel
    directives: str = ""                    # Custom free-form description (overrides/supplements vibe hint)
    music: MusicRequest = MusicRequest()

class JobStatusResponse(BaseModel):
    id: str
    project_id: str
    status: JobStatus
    progress: int
    error_message: Optional[str] = None
    created_at: str
    final_video_url: Optional[str] = None
    story_summary: Optional[str] = None
    proposed_asset_order: Optional[List[int]] = None
    asset_phases: Optional[Dict[str, str]] = None

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        project_result = await db.execute(
            select(Project)
            .options(selectinload(Project.media_assets))
            .filter(Project.id == project_id, or_(Project.user_id == current_user.id, Project.user_id == None))
        )
        project = project_result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not project.media_assets:
            raise HTTPException(status_code=400, detail="Project has no media assets")

        job = AnalysisJob(
            project_id=project_id,
            status=JobStatus.PENDING,
            progress=0,
            vibe=request.vibe.value,
            directives=request.directives,
            music_config=request.music.dict()
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
            directives=request.directives,
            vibe=request.vibe.value,
            music_config=request.music.dict()
        )

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            created_at=str(job.created_at),
            final_video_url=None
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        job_result = await db.execute(
            select(AnalysisJob)
            .join(Project, Project.id == AnalysisJob.project_id)
            .filter(AnalysisJob.id == job_id, or_(Project.user_id == current_user.id, Project.user_id == None))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        final_video_url = None
        if job.status == JobStatus.COMPLETED:
            object_key = f"projects/{job.project_id}/jobs/{job.id}/final_video.mp4"
            final_video_url = storage_service.generate_presigned_url(object_key)

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            vibe=job.vibe,
            directives=job.directives,
            story_summary=job.story_summary,
            proposed_asset_order=job.proposed_asset_order,
            asset_phases=job.asset_phases,
            created_at=str(job.created_at),
            final_video_url=final_video_url
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))

@router.get("/projects/{project_id}/jobs/latest", response_model=JobStatusResponse)
async def get_latest_job(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        job_result = await db.execute(
            select(AnalysisJob)
            .join(Project, Project.id == AnalysisJob.project_id)
            .filter(Project.id == project_id, or_(Project.user_id == current_user.id, Project.user_id == None))
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="No jobs found for this project")

        final_video_url = None
        if job.status == JobStatus.COMPLETED:
            object_key = f"projects/{job.project_id}/jobs/{job.id}/final_video.mp4"
            final_video_url = storage_service.generate_presigned_url(object_key)

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            vibe=job.vibe,
            directives=job.directives,
            story_summary=job.story_summary,
            proposed_asset_order=job.proposed_asset_order,
            asset_phases=job.asset_phases,
            created_at=str(job.created_at),
            final_video_url=final_video_url
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))

from typing import List, Dict, Optional
class ConfirmStoryRequest(BaseModel):
    rewrite_instructions: Optional[str] = None

@router.post("/jobs/{job_id}/confirm-story", response_model=JobStatusResponse)
async def confirm_story_context(
    job_id: uuid.UUID,
    request: ConfirmStoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        job_result = await db.execute(
            select(AnalysisJob)
            .join(Project, Project.id == AnalysisJob.project_id)
            .filter(AnalysisJob.id == job_id, or_(Project.user_id == current_user.id, Project.user_id == None))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != JobStatus.STORY_PROPOSED:
            raise HTTPException(status_code=400, detail=f"Job status must be STORY_PROPOSED to confirm story, current status is {job.status}")

        # 1. Update Story Summary
        final_asset_order = job.proposed_asset_order
        if request.rewrite_instructions and request.rewrite_instructions.strip() not in ["", "string"]:
            from app.services.llm_service import rewrite_story_summary
            import logging
            logging.info(f"Rewriting story based on user instructions: {request.rewrite_instructions}")
            new_summary = rewrite_story_summary(job.story_summary, request.rewrite_instructions)
            job.story_summary = new_summary
            
            # CRITICAL: The old proposed asset order is now stale and contradicts the new story!
            # We must nullify it so Phase 2 does NOT pre-sort the clips incorrectly based on the old story.
            final_asset_order = []

        # 2. Update or Fallback Array Fields
        final_asset_phases = job.asset_phases

        job.confirmed_asset_order = final_asset_order
        job.asset_phases = final_asset_phases
        job.status = JobStatus.RUNNING
        job.progress = 25
        await db.commit()
        await db.refresh(job)

        # Trigger Celery Task Phase 2
        continue_video_analysis.delay(
            job_id=str(job.id),
            confirmed_order=final_asset_order,
            confirmed_summary=job.story_summary,  # Pass the safe DB value, not the raw request
            confirmed_phases=final_asset_phases,
            music_config=job.music_config
        )

        return JobStatusResponse(
            id=str(job.id),
            project_id=str(job.project_id),
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            created_at=str(job.created_at),
            final_video_url=None,
            story_summary=job.story_summary,
            proposed_asset_order=job.proposed_asset_order,
            asset_phases=job.asset_phases
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(err))


class TimelineResponse(BaseModel):
    active_segments: List[AnalyzedClipResponse]
    all_segments: List[AnalyzedClipResponse]
    final_video_url: Optional[str] = None

@router.get("/projects/{project_id}/timeline", response_model=TimelineResponse)
async def get_project_timeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project belongs to user
    proj_result = await db.execute(
        select(Project).filter(Project.id == project_id, or_(Project.user_id == current_user.id, Project.user_id == None))
    )
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the most recent completed job
    job_result = await db.execute(
        select(AnalysisJob)
        .filter(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.created_at.desc())
    )
    job = job_result.scalars().first()
    
    if not job:
        raise HTTPException(status_code=404, detail="No completed analysis job found for this project")

    # Get clips ordered by story_position and load their media_assets
    clips_result = await db.execute(
        select(AnalyzedClip)
        .options(selectinload(AnalyzedClip.media_asset))
        .filter(AnalyzedClip.job_id == job.id)
        .order_by(AnalyzedClip.story_position.asc())
    )
    clips = clips_result.scalars().all()

    all_segments = []
    for c in clips:
        clip_url = None
        if c.media_asset and c.media_asset.object_key:
            base_url = storage_service.generate_presigned_url(c.media_asset.object_key)
            clip_url = f"{base_url}#t={c.start_sec},{c.end_sec}"
            
        all_segments.append(
            AnalyzedClipResponse(
                id=str(c.id),
                media_asset_id=str(c.media_asset_id),
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                story_position=c.story_position or 0,
                metadata_json=c.metadata_json or {},
                url=clip_url
            )
        )
        
    active_segments = [c for c in all_segments if c.metadata_json.get("is_used", False)]
    active_segments.sort(key=lambda x: x.story_position)

    final_video_key = f"projects/{project_id}/jobs/{job.id}/final_video.mp4"
    final_video_url = storage_service.generate_presigned_url(final_video_key)

    return TimelineResponse(
        active_segments=active_segments,
        all_segments=all_segments,
        final_video_url=final_video_url
    )

@router.get("/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify job ownership
    job_result = await db.execute(
        select(AnalysisJob)
        .join(Project, Project.id == AnalysisJob.project_id)
        .filter(AnalysisJob.id == job_id, or_(Project.user_id == current_user.id, Project.user_id == None))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Retrieve the presigned url for the SUMMARY.md log
    object_key = f"logs/llm/{job_id}/SUMMARY.md"
    presigned = storage_service.generate_presigned_url(object_key, bucket=storage_service.llm_logs_bucket)
    if not presigned:
        raise HTTPException(status_code=404, detail="Log not found")
    return {"url": presigned}

@router.get("/projects/{project_id}/active-segments/urls", response_model=List[str])
async def get_active_segments_urls(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project ownership
    proj_result = await db.execute(
        select(Project).filter(Project.id == project_id, or_(Project.user_id == current_user.id, Project.user_id == None))
    )
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the most recent completed job
    job_result = await db.execute(
        select(AnalysisJob)
        .filter(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.created_at.desc())
    )
    job = job_result.scalars().first()
    
    if not job:
        raise HTTPException(status_code=404, detail="No completed analysis job found for this project")

    # Get clips ordered by story_position and load their media_assets
    clips_result = await db.execute(
        select(AnalyzedClip)
        .options(selectinload(AnalyzedClip.media_asset))
        .filter(AnalyzedClip.job_id == job.id)
        .order_by(AnalyzedClip.story_position.asc())
    )
    clips = clips_result.scalars().all()

    urls = []
    for c in clips:
        is_used = c.is_used or (c.metadata_json and c.metadata_json.get("is_used", False))
        if is_used and c.media_asset and c.media_asset.object_key:
            base_url = storage_service.generate_presigned_url(c.media_asset.object_key)
            clip_url = f"{base_url}#t={c.start_sec},{c.end_sec}"
            urls.append(clip_url)
            
    return urls

@router.get("/projects/{project_id}/clips/urls", response_model=List[str])
async def get_clips_urls(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project ownership
    proj_result = await db.execute(
        select(Project).filter(Project.id == project_id, or_(Project.user_id == current_user.id, Project.user_id == None))
    )
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the most recent completed job
    job_result = await db.execute(
        select(AnalysisJob)
        .filter(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.created_at.desc())
    )
    job = job_result.scalars().first()
    
    if not job:
        raise HTTPException(status_code=404, detail="No completed analysis job found for this project")

    # Get clips ordered by story_position and load their media_assets
    clips_result = await db.execute(
        select(AnalyzedClip)
        .options(selectinload(AnalyzedClip.media_asset))
        .filter(AnalyzedClip.job_id == job.id)
        .order_by(AnalyzedClip.story_position.asc())
    )
    clips = clips_result.scalars().all()

    urls = []
    for c in clips:
        if c.media_asset and c.media_asset.object_key:
            base_url = storage_service.generate_presigned_url(c.media_asset.object_key)
            clip_url = f"{base_url}#t={c.start_sec},{c.end_sec}"
            urls.append(clip_url)
            
    return urls


