from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.application_models import (
    AdmissionsDecisionCreateRequest,
    AdmissionsDecisionResponse,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStatusUpdateRequest,
)
from app.services.application_service import ApplicationNotFoundError, ApplicationService, ApplicationValidationError

router = APIRouter(prefix="/applications", tags=["applications"])
application_service = ApplicationService()


@router.get("", response_model=ApplicationListResponse, response_model_exclude_none=True)
def list_applications(
    student_id: str | None = Query(default=None, alias="studentId"),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    applications, total = application_service.list_applications(
        db=db,
        tenant_id=auth_context.tenant.id,
        student_id=student_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ApplicationListResponse(applications=applications, total=total)


@router.post("", response_model=ApplicationResponse, response_model_exclude_none=True, status_code=201)
def create_application(
    payload: ApplicationCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_student_profile")),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    try:
        application = application_service.create_application(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            payload=payload,
        )
    except ApplicationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApplicationResponse(application=application)


@router.get("/{application_id}", response_model=ApplicationResponse, response_model_exclude_none=True)
def get_application(
    application_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    try:
        application = application_service.get_application(
            db=db,
            tenant_id=auth_context.tenant.id,
            application_id=application_id,
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApplicationResponse(application=application)


@router.post("/{application_id}/status", response_model=ApplicationResponse, response_model_exclude_none=True)
def update_application_status(
    application_id: str,
    payload: ApplicationStatusUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_student_profile")),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    try:
        application = application_service.update_status(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            application_id=application_id,
            payload=payload,
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApplicationResponse(application=application)


@router.post("/{application_id}/decisions", response_model=AdmissionsDecisionResponse, response_model_exclude_none=True, status_code=201)
def create_admissions_decision(
    application_id: str,
    payload: AdmissionsDecisionCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("release_decision")),
    db: Session = Depends(get_db),
) -> AdmissionsDecisionResponse:
    try:
        decision = application_service.create_decision(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            application_id=application_id,
            payload=payload,
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdmissionsDecisionResponse(decision=decision)
