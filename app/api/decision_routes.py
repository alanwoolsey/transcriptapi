from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.db import get_db
from app.models.decision_models import (
    CreateDecisionRequest,
    DecisionAssignRequest,
    DecisionAssignResponse,
    DecisionDetailResponse,
    DecisionNoteCreateRequest,
    DecisionNoteItem,
    DecisionStatusUpdateRequest,
    DecisionStatusUpdateResponse,
    DecisionTimelineEvent,
    DecisionWorkbenchItem,
)
from app.services.decision_service import (
    DecisionNotFoundError,
    DecisionService,
    DecisionValidationError,
)

router = APIRouter(prefix="/decisions", tags=["decisions"])
decision_service = DecisionService()


@router.get("", response_model=list[DecisionWorkbenchItem])
def list_decisions(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DecisionWorkbenchItem]:
    return decision_service.list_decisions(auth_context.tenant.id)


@router.post("", response_model=DecisionWorkbenchItem, status_code=status.HTTP_201_CREATED)
def create_decision(
    payload: CreateDecisionRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db: Session = Depends(get_db),
) -> DecisionWorkbenchItem:
    try:
        return decision_service.create_decision(
            db=db,
            tenant_id=auth_context.tenant.id,
            user_id=auth_context.user.id,
            payload=payload,
        )
    except DecisionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{decision_id}", response_model=DecisionDetailResponse)
def get_decision_detail(
    decision_id: UUID,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DecisionDetailResponse:
    try:
        return decision_service.get_decision_detail(auth_context.tenant.id, decision_id)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{decision_id}/status", response_model=DecisionStatusUpdateResponse)
def update_decision_status(
    decision_id: UUID,
    payload: DecisionStatusUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db: Session = Depends(get_db),
) -> DecisionStatusUpdateResponse:
    try:
        return decision_service.update_status(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            decision_id=decision_id,
            payload=payload,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DecisionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{decision_id}/assign", response_model=DecisionAssignResponse)
def assign_decision(
    decision_id: UUID,
    payload: DecisionAssignRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db: Session = Depends(get_db),
) -> DecisionAssignResponse:
    try:
        return decision_service.assign_decision(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            decision_id=decision_id,
            payload=payload,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DecisionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{decision_id}/notes", response_model=DecisionNoteItem, status_code=status.HTTP_201_CREATED)
def add_decision_note(
    decision_id: UUID,
    payload: DecisionNoteCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db: Session = Depends(get_db),
) -> DecisionNoteItem:
    try:
        return decision_service.add_note(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user=auth_context.user,
            decision_id=decision_id,
            payload=payload,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DecisionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{decision_id}/timeline", response_model=list[DecisionTimelineEvent])
def get_decision_timeline(
    decision_id: UUID,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DecisionTimelineEvent]:
    try:
        return decision_service.get_timeline(auth_context.tenant.id, decision_id)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
