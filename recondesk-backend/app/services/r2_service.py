import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.models.upload import UploadResponse
from app.services.storage_service import get_storage_service


def _get_r2_client():
    return get_storage_service().get_s3_client()


def generate_file_key(original_filename: str, user_id: str) -> str:
    return get_storage_service().generate_file_key(original_filename, user_id)


def upload_file_to_r2(
    file_content: bytes,
    file_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload bytes to primary storage (AWS S3) and return URL/key."""
    get_storage_service().upload_bytes(file_content, file_key, content_type=content_type)
    if settings.R2_PUBLIC_URL:
        return f"{settings.R2_PUBLIC_URL.rstrip('/')}/{file_key}"
    return file_key


def create_presigned_upload_url(file_key: str, content_type: str, expires_in: int = 3600) -> str:
    """Generate a presigned PUT URL for direct browser uploads to S3."""
    return get_storage_service().generate_presigned_upload_url(
        file_key, content_type=content_type, expires_in=expires_in
    )


def create_presigned_download_url(file_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for secure file downloads from S3."""
    return get_storage_service().generate_presigned_download_url(
        file_key, expires_in=expires_in
    )


def delete_file_from_r2(file_key: str) -> bool:
    try:
        return get_storage_service().delete_object(file_key)
    except Exception:
        return False
