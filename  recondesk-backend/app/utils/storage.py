import uuid
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

ALLOWED_EXTENSIONS = {".json", ".xlsx", ".xls", ".csv"}


def _get_client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{s.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=s.R2_ACCESS_KEY_ID,
        aws_secret_access_key=s.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


async def upload_file(file_content: bytes, user_id: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("file type not allowed")
    max_b = get_settings().MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_content) > max_b:
        raise ValueError(
            f"file exceeds {get_settings().MAX_FILE_SIZE_MB}MB limit"
        )
    s = get_settings()
    now = datetime.utcnow()
    key = f"uploads/{user_id}/{now.year}/{now.month:02d}/{uuid.uuid4()}{ext}"
    _get_client().put_object(
        Bucket=s.R2_BUCKET_NAME,
        Key=key,
        Body=file_content,
        ServerSideEncryption="AES256",
    )
    return key


async def generate_signed_url(storage_key: str, expires_in: int = 900) -> str:
    s = get_settings()
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": s.R2_BUCKET_NAME, "Key": storage_key},
        ExpiresIn=expires_in,
    )


async def delete_file(storage_key: str) -> bool:
    try:
        s = get_settings()
        _get_client().delete_object(Bucket=s.R2_BUCKET_NAME, Key=storage_key)
        return True
    except ClientError:
        return False


async def file_exists(storage_key: str) -> bool:
    try:
        s = get_settings()
        _get_client().head_object(Bucket=s.R2_BUCKET_NAME, Key=storage_key)
        return True
    except ClientError:
        return False


async def upload_file_raw(file_content: bytes, key: str) -> str:
    """Upload *file_content* to R2 at the exact *key* provided.

    The caller is responsible for routing uploads through an isolated working
    directory when staging files locally (see upload routes).
    """
    s = get_settings()
    _get_client().put_object(
        Bucket=s.R2_BUCKET_NAME,
        Key=key,
        Body=file_content,
        ServerSideEncryption="AES256",
    )
    return key
