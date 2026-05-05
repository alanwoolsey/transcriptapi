from __future__ import annotations

import re


def slugify_storage_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "upload.bin"


def build_pending_storage_key(filename: str) -> str:
    return f"pending/{slugify_storage_filename(filename)}"


def build_document_storage_key(document_id: str, filename: str) -> str:
    return f"{document_id}/{slugify_storage_filename(filename)}"
