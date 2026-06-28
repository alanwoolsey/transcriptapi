from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.ops_models import ChecklistStatusUpdateRequest, StudentChecklistResponse, StudentReadinessResponse
from app.models.student_models import (
    Student360DetailResponse,
    Student360ListResponse,
    StudentCreateRequest,
    StudentInteractionCreateRequest,
    StudentInteractionCreateResponse,
    StudentInteractionUpdateRequest,
    StudentInteractionsListResponse,
    StudentNextActionRequest,
    StudentNextActionResponse,
    StudentProgramUpdateRequest,
    StudentProgramUpdateResponse,
    StudentTimelineResponse,
)
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


@router.post("", response_model=Student360DetailResponse, response_model_exclude_none=True, status_code=201)
def create_student(
    payload: StudentCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_student_profile")),
    db: Session = Depends(get_db),
) -> Student360DetailResponse:
    try:
        record = student_service.create_student(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            payload=payload,
            authorization=auth_context.authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Student360DetailResponse(student=record)


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


@router.patch("/{student_id}", response_model=StudentProgramUpdateResponse)
def update_student(
    student_id: str,
    payload: StudentProgramUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> StudentProgramUpdateResponse:
    try:
        program_name = payload.degreeProgram or payload.program
        return student_service.update_student_program(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            program_name=program_name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{student_id}/next-action", response_model=StudentNextActionResponse)
def record_student_next_action(
    student_id: str,
    payload: StudentNextActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> StudentNextActionResponse:
    try:
        return student_service.record_next_action(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{student_id}/interactions", response_model=StudentInteractionCreateResponse)
def create_student_interaction(
    student_id: str,
    payload: StudentInteractionCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> StudentInteractionCreateResponse:
    try:
        return student_service.create_student_interaction(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{student_id}/interactions", response_model=StudentInteractionsListResponse)
def list_student_interactions(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> StudentInteractionsListResponse:
    try:
        return student_service.list_student_interactions(
            tenant_id=auth_context.tenant.id,
            student_id=student_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{student_id}/interactions/{interaction_id}", response_model=StudentInteractionCreateResponse)
def update_student_interaction(
    student_id: str,
    interaction_id: str,
    payload: StudentInteractionUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> StudentInteractionCreateResponse:
    try:
        return student_service.update_student_interaction(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            interaction_id=interaction_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{student_id}/communications/log")
def log_student_communication(
    student_id: str,
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return student_service.log_student_communication(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{student_id}/handoffs")
def create_student_handoff(
    student_id: str,
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return student_service.create_student_handoff(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{student_id}/post-admit-readiness")
def get_post_admit_readiness(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> dict[str, Any]:
    try:
        return student_service.get_post_admit_readiness(auth_context.tenant.id, student_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{student_id}/milestones/{milestone_id}/status")
def update_post_admit_milestone(
    student_id: str,
    milestone_id: str,
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return student_service.update_post_admit_milestone(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            milestone_id=milestone_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
