from pydantic import BaseModel, UUID4
from datetime import datetime
from typing import Optional
from app.models.domain import ProjectStatus

class ProjectCreate(BaseModel):
    directives: Optional[str] = None

class ProjectResponse(BaseModel):
    id: UUID4
    status: ProjectStatus
    directives: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
