from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.services.aws_client_factory import create_boto3_client


class DocumentStorageService:
    def __init__(self) -> None:
        self._client = None

    def default_bucket(self) -> str:
        if settings.document_storage_backend == "s3":
            if not settings.document_storage_bucket:
                raise ValueError("DOCUMENT_STORAGE_BUCKET is required when DOCUMENT_STORAGE_BACKEND=s3.")
            return settings.document_storage_bucket
        return "direct-upload"

    def store_bytes(self, *, storage_key: str, content: bytes, content_type: str | None = None, storage_bucket: str | None = None) -> None:
        bucket = storage_bucket or self.default_bucket()
        if settings.document_storage_backend == "s3":
            self._get_client().put_object(
                Bucket=bucket,
                Key=storage_key,
                Body=content,
                ContentType=content_type or "application/octet-stream",
            )
            return
        target = self._local_root() / Path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def read_bytes(self, *, storage_key: str, storage_bucket: str | None = None) -> bytes:
        bucket = storage_bucket or self.default_bucket()
        if settings.document_storage_backend == "s3":
            response = self._get_client().get_object(Bucket=bucket, Key=storage_key)
            return response["Body"].read()
        target = self._local_root() / Path(storage_key)
        return target.read_bytes()

    def _get_client(self):
        if self._client is None:
            self._client = create_boto3_client("s3")
        return self._client

    def _local_root(self) -> Path:
        return Path(settings.document_storage_dir).resolve()
