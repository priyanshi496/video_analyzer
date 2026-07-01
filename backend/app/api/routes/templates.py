import os
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.domain import Project, AnalysisJob, JobStatus, User, MediaAsset
from app.core.security import get_current_user
from app.services.pipeline_service import render_project_from_template

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")

class SlotMapping(BaseModel):
    slot_id: str
    media_asset_id: Optional[str] = None
    text: Optional[str] = None

class RenderTemplateRequest(BaseModel):
    template_id: str
    slots: List[SlotMapping]

@router.get("/", response_model=List[Dict[str, Any]])
async def list_templates(current_user: User = Depends(get_current_user)):
    """List all available video templates configured in the system."""
    templates = []
    if not os.path.exists(TEMPLATES_DIR):
        return []
    
    from app.services.storage_service import storage_service
    
    for filename in os.listdir(TEMPLATES_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(TEMPLATES_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    template_data = json.load(f)
                    
                # Generate preview URL dynamically if the preview video exists in MinIO
                template_id = template_data.get("id")
                preview_key = f"previews/{template_id}.mp4"
                if template_id and storage_service.object_exists(preview_key):
                    presigned_url = storage_service.generate_presigned_url(preview_key, expiration=3600)
                    template_data["preview_url"] = presigned_url
                    
                # Generate thumbnail URL dynamically if the thumbnail image exists in MinIO
                thumb_key = f"thumbnails/{template_id}.jpg"
                if template_id and storage_service.object_exists(thumb_key):
                    thumb_url = storage_service.generate_presigned_url(thumb_key, expiration=3600)
                    template_data["thumbnail_url"] = thumb_url
                    
                templates.append(template_data)
            except Exception as e:
                # Log error and skip malformed template files
                import logging
                logging.getLogger(__name__).error(f"Failed to load template {filename}: {e}")
                
    return templates

@router.post("/{project_id}/render", status_code=status.HTTP_201_CREATED)
async def render_from_template(
    project_id: uuid.UUID,
    request: RenderTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger template rendering job on Celery worker."""
    # 1. Verify project exists
    project_result = await db.execute(
        select(Project)
        .options(selectinload(Project.media_assets))
        .filter(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Check if the template exists
    template_path = os.path.join(TEMPLATES_DIR, f"{request.template_id}.json")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail=f"Template {request.template_id} not found")

    with open(template_path, "r", encoding="utf-8") as f:
        template_data = json.load(f)

    # 3. Build AnalysisJob for tracking
    job = AnalysisJob(
        project_id=project_id,
        status=JobStatus.PENDING,
        progress=0,
        vibe=f"template:{request.template_id}",
        directives=f"Template: {template_data.get('name')}",
        music_config={
            "mode": "ai",
            "query": template_data.get("music_query", "ambient"),
            "volume": template_data.get("music_volume", 0.15)
        }
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 4. Fetch all media assets of this project for mapping
    media_map = {str(asset.id): asset.object_key for asset in project.media_assets}

    # 5. Build slot payloads to send to celery
    slots_payload = []
    for s_map in request.slots:
        # Resolve media key if asset id is provided
        obj_key = None
        if s_map.media_asset_id:
            obj_key = media_map.get(s_map.media_asset_id)
            if not obj_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"Media asset {s_map.media_asset_id} not found in this project"
                )

        slots_payload.append({
            "slot_id": s_map.slot_id,
            "object_key": obj_key,
            "text": s_map.text
        })

    # 6. Trigger Celery task
    render_project_from_template.delay(
        project_id=str(project_id),
        job_id=str(job.id),
        template_id=request.template_id,
        slots=slots_payload
    )

    return {
        "id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at.isoformat()
    }
