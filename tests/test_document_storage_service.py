import pytest

from app.core.config import settings
from app.services.document_storage_service import DocumentStorageService


def test_default_bucket_uses_direct_upload_for_local_backend(monkeypatch):
    monkeypatch.setattr(settings, "document_storage_backend", "local")
    monkeypatch.setattr(settings, "document_storage_bucket", None)

    assert DocumentStorageService().default_bucket() == "direct-upload"


def test_default_bucket_uses_configured_s3_bucket(monkeypatch):
    monkeypatch.setattr(settings, "document_storage_backend", "s3")
    monkeypatch.setattr(settings, "document_storage_bucket", "tenant-documents")

    assert DocumentStorageService().default_bucket() == "tenant-documents"


def test_default_bucket_requires_bucket_for_s3(monkeypatch):
    monkeypatch.setattr(settings, "document_storage_backend", "s3")
    monkeypatch.setattr(settings, "document_storage_bucket", None)

    with pytest.raises(ValueError, match="DOCUMENT_STORAGE_BUCKET"):
        DocumentStorageService().default_bucket()
