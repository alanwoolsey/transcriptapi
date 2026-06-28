from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


class UtilityImportService:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path or Path(".document_storage") / "utility_imports.json"
        self._jobs: dict[str, list[dict[str, Any]]] = {}
        self._templates: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def list_jobs(self, tenant_id: UUID) -> dict[str, Any]:
        items = sorted(self._jobs.get(str(tenant_id), []), key=lambda item: item.get("updatedAt") or "", reverse=True)
        return {"items": deepcopy(items), "total": len(items)}

    def create_job(self, tenant_id: UUID, actor_user_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        item = {
            "id": f"import-{uuid4()}",
            "tenantId": str(tenant_id),
            "actorUserId": str(actor_user_id),
            "status": payload.get("status") or "draft",
            "fileName": payload.get("fileName"),
            "documentId": payload.get("documentId"),
            "importType": payload.get("importType") or "Students / Prospects",
            "actionMode": payload.get("actionMode") or "Add new and update existing",
            "settings": payload.get("settings") or {},
            "mappings": payload.get("mappings") or [],
            "summary": payload.get("summary") or {},
            "rows": payload.get("rows") or [],
            "templateName": payload.get("templateName"),
            "createdAt": now,
            "updatedAt": now,
            "completedAt": payload.get("completedAt"),
        }
        self._jobs.setdefault(str(tenant_id), []).append(item)
        self._save()
        return deepcopy(item)

    def update_job(self, tenant_id: UUID, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        for item in self._jobs.get(str(tenant_id), []):
            if item["id"] != job_id:
                continue
            for key in ("status", "importType", "actionMode", "settings", "mappings", "summary", "rows", "templateName", "completedAt"):
                if key in payload:
                    item[key] = payload[key]
            item["updatedAt"] = self._now()
            self._save()
            return deepcopy(item)
        raise LookupError("Import job not found.")

    def list_templates(self, tenant_id: UUID) -> dict[str, Any]:
        items = sorted(self._templates.get(str(tenant_id), []), key=lambda item: item.get("updatedAt") or "", reverse=True)
        return {"items": deepcopy(items), "total": len(items)}

    def save_template(self, tenant_id: UUID, actor_user_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("name"):
            raise ValueError("Template name is required.")
        now = self._now()
        templates = self._templates.setdefault(str(tenant_id), [])
        existing = next((item for item in templates if item.get("name") == payload["name"]), None)
        item = existing or {
            "id": f"template-{uuid4()}",
            "tenantId": str(tenant_id),
            "actorUserId": str(actor_user_id),
            "createdAt": now,
        }
        item.update(
            {
                "name": payload["name"],
                "source": payload.get("source") or "Manual Inquiry Upload",
                "importType": payload.get("importType") or "Students / Prospects",
                "mappings": payload.get("mappings") or [],
                "transformRules": payload.get("transformRules") or [],
                "validationRules": payload.get("validationRules") or [],
                "matchingStrategy": payload.get("matchingStrategy") or [],
                "updateBehavior": payload.get("updateBehavior") or "Do not overwrite existing values",
                "updatedAt": now,
            }
        )
        if existing is None:
            templates.append(item)
        self._save()
        return deepcopy(item)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._jobs = payload.get("jobs") if isinstance(payload.get("jobs"), dict) else {}
            self._templates = payload.get("templates") if isinstance(payload.get("templates"), dict) else {}
        except (OSError, json.JSONDecodeError):
            self._jobs = {}
            self._templates = {}

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(
            json.dumps({"jobs": self._jobs, "templates": self._templates}, indent=2, sort_keys=True),
            encoding="utf-8",
        )


utility_import_service = UtilityImportService()
