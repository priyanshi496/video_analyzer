from pydantic import BaseModel, UUID4
from datetime import datetime
from typing import Optional
from app.models.domain import ProjectStatus, PlatformType

class ProjectCreate(BaseModel):
    name: Optional[str] = None
    platform: Optional[PlatformType] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[PlatformType] = None


class ProjectResponse(BaseModel):
    id: UUID4
    name: str
    platform: Optional[PlatformType] = None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

