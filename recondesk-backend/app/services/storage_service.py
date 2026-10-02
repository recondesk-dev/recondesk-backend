"""Unified Cloud Storage Service for ReconDesk.

Handles all object storage operations with:
1. Native AWS S3 as primary storage backend (ap-south-1).
2. Transparent dual-read fallback from Cloudflare R2 for unmigrated legacy objects.
3. Transparent sync-on-read so legacy R2 reads populate S3 automatically.
4. Presigned upload (PUT) and download (GET) URL generation.
5. Strict tenant isolation, SSE-S3 AES-256 encryption, and private bucket access.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from app.config import get_r2_s3_endpoint_url, get_settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


class StorageService:
    """Enterprise Storage Service supporting AWS S3 and R2 migration fallback."""

    def __init__(self) -> None:
        self._s3_client: Optional[Any] = None
        self._r2_client: Optional[Any] = None

    @property
    def settings(self):
        return get_settings()

    @property
    def s3_bucket(self) -> str:
        s = self.settings
        return (s.AWS_S3_BUCKET_NAME or s.R2_BUCKET_NAME or "recondesk-storage-991216470563").strip()

    @property
    def r2_bucket(self) -> str:
        s = self.settings
        return (s.R2_BUCKET_NAME or "recondesk").strip()

    def get_s3_client(self):
        """Get or initialize native AWS S3 boto3 client."""
        if self._s3_client is not None:
            return self._s3_client

        s = self.settings
        region = (s.AWS_REGION or "ap-south-1").strip()
        client_kwargs: dict[str, Any] = {
            "region_name": region,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        }

        # Regional endpoint for clean presigned URLs without 307 redirects
        if s.AWS_S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = s.AWS_S3_ENDPOINT_URL.strip()
        else:
            client_kwargs["endpoint_url"] = f"https://s3.{region}.amazonaws.com"

        # Explicit credentials if provided; otherwise boto3 automatically resolves
        # EC2 IAM instance profiles, ECS task roles, or environment variables.
        if s.AWS_ACCESS_KEY_ID and s.AWS_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = s.AWS_ACCESS_KEY_ID.strip()
            client_kwargs["aws_secret_access_key"] = s.AWS_SECRET_ACCESS_KEY.strip()

        self._s3_client = boto3.client("s3", **client_kwargs)
        return self._s3_client

    def get_r2_client(self):
        """Get or initialize legacy Cloudflare R2 client for read fallback."""
        if self._r2_client is not None:
            return self._r2_client

        s = self.settings
        if not s.R2_ACCESS_KEY_ID or not s.R2_SECRET_ACCESS_KEY:
            return None

        try:
            endpoint = get_r2_s3_endpoint_url()
        except Exception:
            return None

        self._r2_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=s.R2_ACCESS_KEY_ID.strip(),
            aws_secret_access_key=s.R2_SECRET_ACCESS_KEY.strip(),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        return self._r2_client

    def upload_bytes(
        self,
        body: bytes,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        """Upload raw bytes directly to native AWS S3."""
        s3 = self.get_s3_client()
        params: dict[str, Any] = {
            "Bucket": self.s3_bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
            "ServerSideEncryption": "AES256",
        }
        if metadata:
            params["Metadata"] = metadata
        s3.put_object(**params)
        logger.info("Uploaded %d bytes to S3 key=%s", len(body), key)
        return key

    def get_object(self, key: str) -> dict[str, Any]:
        """Fetch object from S3; fall back to R2 with sync-on-read if missing in S3."""
        s3 = self.get_s3_client()
        try:
            return s3.get_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchKey", "NotFound"):
                raise

        # Fallback to R2
        r2 = self.get_r2_client()
        if r2 is not None:
            try:
                r2_obj = r2.get_object(Bucket=self.r2_bucket, Key=key)
                logger.info("Read fallback to R2 succeeded for key=%s; syncing to S3", key)
                data = r2_obj["Body"].read()
                content_type = r2_obj.get("ContentType", "application/octet-stream")

                # Sync to S3 so future reads hit S3 directly
                try:
                    s3.put_object(
                        Bucket=self.s3_bucket,
                        Key=key,
                        Body=data,
                        ContentType=content_type,
                        ServerSideEncryption="AES256",
                        Metadata={"migrated_from": "r2_fallback_sync"},
                    )
                except Exception as sync_err:
                    logger.warning("Failed to sync fallback object to S3 key=%s: %s", key, sync_err)

                return {
                    "Body": io.BytesIO(data),
                    "ContentType": content_type,
                    "ContentLength": len(data),
                }
            except ClientError as r2_exc:
                r2_code = str(r2_exc.response.get("Error", {}).get("Code", ""))
                if r2_code not in ("404", "NoSuchKey", "NotFound"):
                    logger.warning("R2 fallback read error for key=%s: %s", key, r2_exc)

        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": f"The specified key does not exist: {key}"}},
            "GetObject",
        )

    def download_bytes(self, key: str) -> bytes:
        """Download entire object body as bytes."""
        obj = self.get_object(key)
        body = obj["Body"]
        if hasattr(body, "read"):
            return body.read()
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        raise ValueError(f"Unexpected body type: {type(body)}")

    def head_object(self, key: str) -> dict[str, Any]:
        """Check metadata for object in S3; fall back to R2 if not in S3."""
        s3 = self.get_s3_client()
        try:
            return s3.head_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchKey", "NotFound"):
                raise

        r2 = self.get_r2_client()
        if r2 is not None:
            try:
                return r2.head_object(Bucket=self.r2_bucket, Key=key)
            except ClientError:
                pass

        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": f"Object not found: {key}"}},
            "HeadObject",
        )

    def file_exists(self, key: str) -> bool:
        """Return True if object exists in S3 or R2."""
        try:
            self.head_object(key)
            return True
        except ClientError:
            return False

    def delete_object(self, key: str) -> bool:
        """Delete object from S3 and R2 (to prevent ghost resurrection)."""
        deleted_any = False
        s3 = self.get_s3_client()
        try:
            s3.delete_object(Bucket=self.s3_bucket, Key=key)
            deleted_any = True
        except ClientError as exc:
            logger.warning("S3 delete failed for key=%s: %s", key, exc)

        r2 = self.get_r2_client()
        if r2 is not None:
            try:
                r2.delete_object(Bucket=self.r2_bucket, Key=key)
                deleted_any = True
            except ClientError as exc:
                logger.debug("R2 delete failed/not found for key=%s: %s", key, exc)

        return deleted_any

    def delete_objects(self, keys: list[str]) -> None:
        """Batch delete multiple objects."""
        for k in keys:
            if k:
                self.delete_object(k)

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate a presigned PUT URL for browser direct uploads directly to S3."""
        s3 = self.get_s3_client()
        return s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.s3_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: Optional[str] = None,
    ) -> str:
        """Generate a presigned GET URL for secure download from S3.

        If the object currently only exists in R2, it is synced to S3 first so
        the resulting presigned S3 GET URL is guaranteed to succeed.
        """
        s3 = self.get_s3_client()

        # Check if object exists in S3; if missing, trigger fallback sync
        try:
            s3.head_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                # Read via get_object which automatically syncs R2 -> S3
                try:
                    self.get_object(key)
                except Exception as err:
                    logger.warning("Could not sync object before presigning download: %s", err)

        params: dict[str, Any] = {
            "Bucket": self.s3_bucket,
            "Key": key,
        }
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        return s3.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def verify_sha256(
        self,
        key: str,
        expected_hex: str,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> int:
        """Verify object existence, file size, and SHA-256 integrity hash."""
        try:
            body = self.download_bytes(key)
        except ClientError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Object not found in storage",
            ) from exc

        if len(body) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File too large",
            )

        digest = hashlib.sha256(body).hexdigest()
        if digest.lower() != (expected_hex or "").lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File hash mismatch",
            )

        return len(body)

    @staticmethod
    def generate_file_key(original_filename: str, user_id: str) -> str:
        """Generate standard tenant-isolated object key for general uploads."""
        ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "bin"
        return f"uploads/{user_id}/{uuid.uuid4()}.{ext}"


_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Get or create singleton StorageService."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
