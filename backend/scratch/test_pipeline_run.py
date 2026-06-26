import uuid
import sys
import os
import logging
import asyncio

# Setup Python path
sys.path.append("/Users/priyanshimodi/Documents/projects/TSC/video_analyzer/backend")

from app.core.database import AsyncSessionLocal
from app.models.domain import Project, AnalysisJob, JobStatus, MediaAsset
from app.services.pipeline_service import analyze_video_project, continue_video_analysis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_session():
    # Helper to execute async code synchronously using a fresh event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

def run_pipeline():
    project_id = uuid.UUID("b0484f2d-b40c-4d40-bb53-d5a7eb2ae91b")
    loop = get_session()
    
    async def get_data():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Project)
                .options(selectinload(Project.media_assets))
                .filter(Project.id == project_id)
            )
            project = result.scalar_one_or_none()
            if not project:
                return None, None
            
            job = AnalysisJob(
                project_id=project_id,
                status=JobStatus.PENDING,
                progress=0,
                vibe="cinematic",
                directives="",
                music_config={"mode": "ai"}
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            
            assets_data = [
                {
                    "id": str(asset.id),
                    "file_name": asset.filename,
                    "storage_path": asset.object_key,
                }
                for asset in sorted(project.media_assets, key=lambda x: x.sequence_index)
            ]
            return str(job.id), assets_data
            
    job_id, assets_data = loop.run_until_complete(get_data())
    print(f"Created new Job ID: {job_id}")

    # Run Phase 1
    print("\n--- Running Phase 1 (analyze_video_project) ---")
    analyze_video_project(
        project_id=str(project_id),
        job_id=job_id,
        media_assets=assets_data,
        directives="",
        vibe="cinematic",
        music_config={"mode": "ai"}
    )
    
    async def check_phase1():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one()
            print(f"\nPhase 1 completed. Job Status: {job.status}")
            print(f"Proposed Order: {job.proposed_asset_order}")
            print(f"Story Summary: {job.story_summary}")
            
            # Auto-confirm story context and transition to Phase 2
            job.confirmed_asset_order = job.proposed_asset_order
            job.status = JobStatus.RUNNING
            await db.commit()
            return job.story_summary, job.confirmed_asset_order, job.asset_phases, job.music_config

    confirmed_summary, confirmed_order, confirmed_phases, music_config = loop.run_until_complete(check_phase1())
        
    print("\n--- Running Phase 2 (continue_video_analysis) ---")
    continue_video_analysis(
        job_id=job_id,
        confirmed_order=confirmed_order,
        confirmed_summary=confirmed_summary,
        confirmed_phases=confirmed_phases,
        music_config=music_config
    )
    
    async def print_clips():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one()
            print(f"\nPhase 2 completed. Job Status: {job.status}")
            
            from app.models.domain import AnalyzedClip
            clips_res = await db.execute(
                select(AnalyzedClip)
                .options(selectinload(AnalyzedClip.media_asset))
                .filter(AnalyzedClip.job_id == job.id)
                .order_by(AnalyzedClip.story_position.asc())
            )
            clips = clips_res.scalars().all()
            print("\nFinal Timeline Clips:")
            for c in clips:
                if c.is_used or (c.metadata_json and c.metadata_json.get("is_used", False)):
                    print(f"Position: {c.story_position} | File: {c.media_asset.filename} | Start: {c.start_sec}s | End: {c.end_sec}s")

    loop.run_until_complete(print_clips())

if __name__ == "__main__":
    run_pipeline()
