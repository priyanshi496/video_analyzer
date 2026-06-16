from pydantic import BaseModel, UUID4
from datetime import datetime
from typing import Optional

class MediaAssetResponse(BaseModel):
    id: UUID4
    project_id: UUID4
    sequence_index: int
    filename: str
    file_size_bytes: Optional[int]
    mime_type: Optional[str]
    duration_sec: Optional[float]
    created_at: datetime
    
    class Config:
        from_attributes = True

class MediaAssetWithUrlResponse(MediaAssetResponse):
    presigned_url: str
