from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import List
import uuid

from app.core.database import get_db
from app.models.domain import Project, MediaAsset, User
from app.schemas.project import ProjectCreate, ProjectResponse
from app.schemas.media import MediaAssetResponse, MediaAssetWithUrlResponse
from app.services.storage_service import storage_service
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_project = Project(directives=project_in.directives, user_id=current_user.id)
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return new_project

import asyncio

@router.post("/{project_id}/media", response_model=List[MediaAssetWithUrlResponse], status_code=status.HTTP_201_CREATED)
async def upload_media(
    project_id: uuid.UUID,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists and belongs to the user (or is unowned)
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            or_(Project.user_id == current_user.id, Project.user_id == None)
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine sequence index (max current sequence + 1)
    seq_result = await db.execute(
        select(func.coalesce(func.max(MediaAsset.sequence_index), 0))
        .where(MediaAsset.project_id == project_id)
    )
    next_seq = seq_result.scalar() + 1

    async def process_file(file: UploadFile, seq_idx: int):
        object_key = f"projects/{project_id}/media/{uuid.uuid4()}_{file.filename}"
        await asyncio.to_thread(storage_service.upload_file_obj, file.file, object_key, file.content_type)
        url = storage_service.generate_presigned_url(object_key)
        
        return {
            "media_asset": MediaAsset(
                project_id=project_id,
                sequence_index=seq_idx,
                filename=file.filename,
                object_key=object_key,
                file_size_bytes=file.size,
                mime_type=file.content_type
            ),
            "url": url
        }

    # Upload all files to MinIO in parallel
    tasks = [process_file(file, next_seq + i) for i, file in enumerate(files)]
    results = await asyncio.gather(*tasks)

    # Save to DB
    media_assets = [res["media_asset"] for res in results]
    db.add_all(media_assets)
    await db.commit()
    
    # Refresh to get DB-generated fields
    for asset in media_assets:
        await db.refresh(asset)

    # Construct response
    response = []
    for asset, res in zip(media_assets, results):
        asset_dict = {c.name: getattr(asset, c.name) for c in asset.__table__.columns}
        asset_dict["presigned_url"] = res["url"]
        response.append(MediaAssetWithUrlResponse(**asset_dict))

    return response

@router.get("/{project_id}/media", response_model=List[MediaAssetWithUrlResponse])
async def list_media(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists and belongs to the user (or is unowned)
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            or_(Project.user_id == current_user.id, Project.user_id == None)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    media_result = await db.execute(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .where(MediaAsset.is_deleted == False)
        .order_by(MediaAsset.sequence_index)
    )
    assets = media_result.scalars().all()

    response = []
    for asset in assets:
        url = storage_service.generate_presigned_url(asset.object_key)
        asset_dict = {c.name: getattr(asset, c.name) for c in asset.__table__.columns}
        asset_dict["presigned_url"] = url
        response.append(MediaAssetWithUrlResponse(**asset_dict))

    return response

