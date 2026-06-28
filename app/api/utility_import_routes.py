from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import AuthenticatedTenantContext, require_any_role
from app.services.utility_import_service import utility_import_service

router = APIRouter(prefix="/utilities/imports", tags=["utility-imports"])
require_utility_admin = require_any_role("tenant_admin", "master_tenant_admin")


@router.get("/jobs")
def list_import_jobs(
    auth_context: AuthenticatedTenantContext = Depends(require_utility_admin),
) -> dict[str, Any]:
    return utility_import_service.list_jobs(auth_context.tenant.id)


@router.post("/jobs", status_code=201)
def create_import_job(
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_utility_admin),
) -> dict[str, Any]:
    return utility_import_service.create_job(auth_context.tenant.id, auth_context.user.id, payload)


@router.patch("/jobs/{job_id}")
def update_import_job(
    job_id: str,
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_utility_admin),
) -> dict[str, Any]:
    try:
        return utility_import_service.update_job(auth_context.tenant.id, job_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/templates")
def list_import_templates(
    auth_context: AuthenticatedTenantContext = Depends(require_utility_admin),
) -> dict[str, Any]:
    return utility_import_service.list_templates(auth_context.tenant.id)


@router.post("/templates", status_code=201)
def save_import_template(
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_utility_admin),
) -> dict[str, Any]:
    try:
        return utility_import_service.save_template(auth_context.tenant.id, auth_context.user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
