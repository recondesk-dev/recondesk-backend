import uuid
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.services.storage_service import get_storage_service

ALLOWED_EXTENSIONS = {".json", ".xlsx", ".xls", ".csv"}


def _get_client():
    return get_storage_service().get_s3_client()


async def upload_file(file_content: bytes, user_id: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("file type not allowed")
    max_b = get_settings().MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_content) > max_b:
        raise ValueError(
            f"file exceeds {get_settings().MAX_FILE_SIZE_MB}MB limit"
        )
    now = datetime.utcnow()
    key = f"uploads/{user_id}/{now.year}/{now.month:02d}/{uuid.uuid4()}{ext}"
    get_storage_service().upload_bytes(file_content, key)
    return key


async def generate_signed_url(storage_key: str, expires_in: int = 900) -> str:
    return get_storage_service().generate_presigned_download_url(storage_key, expires_in=expires_in)


async def delete_file(storage_key: str) -> bool:
    try:
        return get_storage_service().delete_object(storage_key)
    except Exception:
        return False


async def file_exists(storage_key: str) -> bool:
    return get_storage_service().file_exists(storage_key)


async def upload_file_raw(file_content: bytes, key: str) -> str:
    """Upload *file_content* to object storage at the exact *key* provided.

    The caller is responsible for routing uploads through an isolated working
    directory when staging files locally (see upload routes).
    """
    get_storage_service().upload_bytes(file_content, key)
    return key
