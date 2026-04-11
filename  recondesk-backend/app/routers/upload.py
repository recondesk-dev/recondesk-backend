from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import get_current_active_user
from app.models.upload import PresignedUrlRequest, PresignedUrlResponse, UploadResponse
from app.services.r2_service import (
    create_presigned_upload_url,
    generate_file_key,
    upload_file_to_r2,
)

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


@router.post("/file", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Direct file upload (server-side). Max 50 MB."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 50 MB limit",
        )

    file_key = generate_file_key(file.filename or "upload", str(current_user["id"]))
    public_url = upload_file_to_r2(content, file_key, file.content_type or "application/octet-stream")

    return UploadResponse(
        file_key=file_key,
        file_name=file.filename or "upload",
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        public_url=public_url,
        uploaded_at=datetime.now(timezone.utc),
    )


@router.post("/presign", response_model=PresignedUrlResponse)
async def get_presigned_url(
    payload: PresignedUrlRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate a presigned URL for direct browser-to-R2 uploads."""
    if payload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {payload.content_type}",
        )
    file_key = generate_file_key(payload.file_name, str(current_user["id"]))
    upload_url = create_presigned_upload_url(file_key, payload.content_type)
    return PresignedUrlResponse(upload_url=upload_url, file_key=file_key)
