"""
app/services/storage/base.py + implementations
──────────────────────────────────────────────────────────────────────────────
File storage for images uploaded during calls.

Use case: Seller says "ek second, photo bhej raha hoon" during a live call.
  1. They WhatsApp/upload a photo to a companion web URL
  2. Photo is stored here and linked to the active call_sid
  3. call_socket.py detects new image → sends to Gemini vision → updates catalog

Change STORAGE_PROVIDER in .env to swap backends.
"""

import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings


# ── Abstract base ──────────────────────────────────────────────────────────

class StorageProvider(ABC):

    @abstractmethod
    async def save(self, call_sid: str, filename: str, data: bytes, content_type: str) -> str:
        """Save file and return public URL."""
        ...

    @abstractmethod
    async def get_url(self, path: str) -> str:
        """Return public URL for a stored file."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a stored file."""
        ...


# ── Local filesystem ───────────────────────────────────────────────────────

class LocalStorageProvider(StorageProvider):
    """Stores files in LOCAL_UPLOAD_DIR. Good for dev."""

    def __init__(self):
        self.base = settings.LOCAL_UPLOAD_DIR
        os.makedirs(self.base, exist_ok=True)

    async def save(self, call_sid: str, filename: str, data: bytes, content_type: str) -> str:
        folder = os.path.join(self.base, call_sid)
        os.makedirs(folder, exist_ok=True)
        ext  = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"
        name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(data)
        # Return a URL the FastAPI static file server can serve
        return f"{settings.PUBLIC_BASE_URL}/uploads/{call_sid}/{name}"

    async def get_url(self, path: str) -> str:
        return f"{settings.PUBLIC_BASE_URL}/uploads/{path}"

    async def delete(self, path: str) -> None:
        full = os.path.join(self.base, path)
        if os.path.exists(full):
            os.remove(full)


# ── AWS S3 ─────────────────────────────────────────────────────────────────

class S3StorageProvider(StorageProvider):
    """Stores files in AWS S3. Set AWS_* keys in .env."""

    def __init__(self):
        import boto3
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY,
            aws_secret_access_key=settings.AWS_SECRET_KEY,
            region_name=settings.AWS_REGION,
        )
        self.bucket = settings.AWS_BUCKET

    async def save(self, call_sid: str, filename: str, data: bytes, content_type: str) -> str:
        ext  = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"
        key  = f"calls/{call_sid}/{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type, ACL="public-read",
        )
        return f"https://{self.bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"

    async def get_url(self, path: str) -> str:
        return f"https://{self.bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{path}"

    async def delete(self, path: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=path)


# ── Google Cloud Storage ───────────────────────────────────────────────────

class GCSStorageProvider(StorageProvider):
    """Stores files in Google Cloud Storage. Set GCS_* in .env."""

    def __init__(self):
        from google.cloud import storage as gcs
        import json as _json
        if settings.GCS_CREDENTIALS_JSON:
            info = _json.loads(settings.GCS_CREDENTIALS_JSON)
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(info)
            self.client = gcs.Client(credentials=creds)
        else:
            self.client = gcs.Client()  # uses ADC
        self.bucket_name = settings.GCS_BUCKET

    async def save(self, call_sid: str, filename: str, data: bytes, content_type: str) -> str:
        ext    = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"
        name   = f"calls/{call_sid}/{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
        bucket = self.client.bucket(self.bucket_name)
        blob   = bucket.blob(name)
        blob.upload_from_string(data, content_type=content_type)
        blob.make_public()
        return blob.public_url

    async def get_url(self, path: str) -> str:
        return f"https://storage.googleapis.com/{self.bucket_name}/{path}"

    async def delete(self, path: str) -> None:
        bucket = self.client.bucket(self.bucket_name)
        bucket.blob(path).delete()


# ── Factory ────────────────────────────────────────────────────────────────

def get_storage_provider() -> StorageProvider:
    p = settings.STORAGE_PROVIDER.lower()
    if p == "local":
        return LocalStorageProvider()
    elif p == "s3":
        return S3StorageProvider()
    elif p == "gcs":
        return GCSStorageProvider()
    else:
        raise ValueError(f"Unknown STORAGE_PROVIDER='{p}'. Supported: local, s3, gcs")


# Singleton — import and use this everywhere
storage = get_storage_provider()
