from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_key: str
    file_name: str
    file_size: int
    content_type: str
    public_url: Optional[str] = None
    uploaded_at: datetime


class PresignedUrlRequest(BaseModel):
    file_name: str
    content_type: str


class PresignedUrlResponse(BaseModel):
    upload_url: str
    file_key: str
    expires_in: int = 3600
