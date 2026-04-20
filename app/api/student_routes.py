from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.db import get_db
from app.models.ops_models import ChecklistItemResponse, ChecklistStatusUpdateRequest, StudentReadinessResponse
from app.models.student_models import Student360ListRecord, Student360Record
from app.services.admissions_ops_service import AdmissionsOpsNotFoundError, AdmissionsOpsService, AdmissionsOpsValidationError
from app.services.student_360_service import Student360Service

router = APIRouter(prefix="/students", tags=["students"])
student_service = Student360Service()
admissions_ops_service = AdmissionsOpsService()


@router.get("", response_model=list[Student360ListRecord], response_model_exclude_none=True)
def list_students(
    q: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[Student360ListRecord]:
    return student_service.list_students(tenant_id=auth_context.tenant.id, q=q)


@router.get("/{student_id}", response_model=Student360Record, response_model_exclude_none=True)
def get_student(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> Student360Record:
    record = student_service.get_student(tenant_id=auth_context.tenant.id, student_id=student_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return record


@router.get("/{student_id}/checklist", response_model=list[ChecklistItemResponse])
def get_student_checklist(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[ChecklistItemResponse]:
    try:
        return admissions_ops_service.get_student_checklist(auth_context.tenant.id, student_id)
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{student_id}/checklist/items/{item_id}/status", response_model=list[ChecklistItemResponse])
def update_student_checklist_item_status(
    student_id: str,
    item_id: str,
    payload: ChecklistStatusUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db: Session = Depends(get_db),
) -> list[ChecklistItemResponse]:
    try:
        return admissions_ops_service.update_checklist_item_status(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            item_id=item_id,
            status=payload.status,
        )
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdmissionsOpsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{student_id}/readiness", response_model=StudentReadinessResponse)
def get_student_readiness(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> StudentReadinessResponse:
    try:
        return admissions_ops_service.get_student_readiness(auth_context.tenant.id, student_id)
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
