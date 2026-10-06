import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_r2_s3_endpoint_url, settings
from app.models.upload import UploadResponse


def is_r2_configured() -> bool:
    """Return True if R2/S3 object storage credentials and endpoint are configured."""
    try:
        endpoint = get_r2_s3_endpoint_url()
        return bool(endpoint and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY)
    except Exception:
        return False


def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=get_r2_s3_endpoint_url(),
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def generate_file_key(original_filename: str, user_id: str) -> str:
    ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "bin"
    return f"uploads/{user_id}/{uuid.uuid4()}.{ext}"


def upload_bytes_to_r2(
    file_content: bytes,
    file_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload raw bytes to R2 object storage at file_key."""
    client = _get_r2_client()
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=file_key,
        Body=file_content,
        ContentType=content_type,
    )
    return file_key


def download_file_from_r2(file_key: str) -> bytes:
    """Download object bytes from R2 object storage at file_key."""
    client = _get_r2_client()
    resp = client.get_object(Bucket=settings.R2_BUCKET_NAME, Key=file_key)
    return resp["Body"].read()


def upload_file_to_r2(
    file_content: bytes,
    file_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload bytes to R2 and return the public URL."""
    upload_bytes_to_r2(file_content, file_key, content_type)
    return f"{settings.R2_PUBLIC_URL}/{file_key}"


def create_presigned_upload_url(file_key: str, content_type: str, expires_in: int = 3600) -> str:
    """Generate a presigned PUT URL for direct browser uploads."""
    client = _get_r2_client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": file_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def create_presigned_download_url(file_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for secure file downloads."""
    client = _get_r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": file_key},
        ExpiresIn=expires_in,
    )


def delete_file_from_r2(file_key: str) -> bool:
    try:
        client = _get_r2_client()
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=file_key)
        return True
    except ClientError:
        return False
