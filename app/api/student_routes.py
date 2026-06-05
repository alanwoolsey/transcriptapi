from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.ops_models import ChecklistStatusUpdateRequest, StudentChecklistResponse, StudentReadinessResponse
from app.models.student_models import Student360DetailResponse, Student360ListResponse, StudentTimelineResponse
from app.services.admissions_ops_service import AdmissionsOpsNotFoundError, AdmissionsOpsService, AdmissionsOpsValidationError
from app.services.student_360_service import Student360Service

router = APIRouter(prefix="/students", tags=["students"])
student_service = Student360Service()
admissions_ops_service = AdmissionsOpsService()


@router.get("", response_model=Student360ListResponse, response_model_exclude_none=True)
def list_students(
    q: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    population: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    source: str | None = Query(default=None),
    program: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> Student360ListResponse:
    return student_service.list_students(
        tenant_id=auth_context.tenant.id,
        q=q,
        stage=stage,
        population=population,
        owner=owner,
        source=source,
        program=program,
        limit=limit,
        offset=offset,
    )


@router.get("/{student_id}", response_model=Student360DetailResponse, response_model_exclude_none=True)
def get_student(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> Student360DetailResponse:
    record = student_service.get_student(
        tenant_id=auth_context.tenant.id,
        student_id=student_id,
        authorization=auth_context.authorization,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return Student360DetailResponse(student=record)


@router.get("/{student_id}/timeline", response_model=StudentTimelineResponse, response_model_exclude_none=True)
def get_student_timeline(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> StudentTimelineResponse:
    response = student_service.get_student_timeline(
        tenant_id=auth_context.tenant.id,
        student_id=student_id,
        authorization=auth_context.authorization,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return response


@router.get("/{student_id}/checklist", response_model=StudentChecklistResponse)
def get_student_checklist(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> StudentChecklistResponse:
    try:
        return admissions_ops_service.get_student_checklist(auth_context.tenant.id, student_id)
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{student_id}/checklist/items/{item_id}/status", response_model=StudentChecklistResponse)
def update_student_checklist_item_status(
    student_id: str,
    item_id: str,
    payload: ChecklistStatusUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_checklist")),
    db: Session = Depends(get_db),
) -> StudentChecklistResponse:
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
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> StudentReadinessResponse:
    try:
        return admissions_ops_service.get_student_readiness(auth_context.tenant.id, student_id)
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
