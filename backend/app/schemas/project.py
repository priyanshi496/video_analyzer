from pydantic import BaseModel, UUID4
from datetime import datetime
from typing import Optional
from app.models.domain import ProjectStatus

class ProjectCreate(BaseModel):
    name: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None


class ProjectResponse(BaseModel):
    id: UUID4
    name: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    audio_object_key: Optional[str] = None
    audio_filename: Optional[str] = None

    class Config:
        from_attributes = True

