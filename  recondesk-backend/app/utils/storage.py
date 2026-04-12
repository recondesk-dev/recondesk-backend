import boto3
import uuid
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError
from app.config import settings

ALLOWED_EXTENSIONS = {".json", ".xlsx", ".xls", ".csv"}
MAX_SIZE_JSON = 50 * 1024 * 1024
MAX_SIZE_EXCEL = 20 * 1024 * 1024

def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

async def upload_file(file_content: bytes, user_id: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type {ext} not allowed")
    if ext == ".json" and len(file_content) > MAX_SIZE_JSON:
        raise ValueError("JSON file exceeds 50MB limit")
    if ext in {".xlsx", ".xls"} and len(file_content) > MAX_SIZE_EXCEL:
        raise ValueError("Excel file exceeds 20MB limit")

    now = datetime.utcnow()
    key = f"uploads/{user_id}/{now.year}/{now.month:02d}/{uuid.uuid4()}{ext}"
    _get_client().put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_content,
        ServerSideEncryption="AES256",
    )
    return key

async def generate_signed_url(storage_key: str, expires_in: int = 900) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": storage_key},
        ExpiresIn=expires_in,
    )

async def delete_file(storage_key: str) -> bool:
    try:
        _get_client().delete_object(Bucket=settings.R2_BUCKET_NAME, Key=storage_key)
        return True
    except ClientError:
        return False

async def file_exists(storage_key: str) -> bool:
    try:
        _get_client().head_object(Bucket=settings.R2_BUCKET_NAME, Key=storage_key)
        return True
    except ClientError:
        return False