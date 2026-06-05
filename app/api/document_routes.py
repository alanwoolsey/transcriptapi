from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.ops_models import (
    DocumentAgentRunDetailsResponse,
    DocumentExceptionSummaryResponse,
    DocumentExceptionsResponse,
    LinkChecklistItemRequest,
    StudentChecklistResponse,
)
from app.services.admissions_ops_service import AdmissionsOpsNotFoundError, AdmissionsOpsService, AdmissionsOpsValidationError
from app.services.operations_service import OperationsService

router = APIRouter(prefix="/documents", tags=["documents"])
admissions_ops_service = AdmissionsOpsService()
operations_service = OperationsService()


@router.post("/{document_id}/link-checklist-item", response_model=StudentChecklistResponse)
def link_document_to_checklist_item(
    document_id: str,
    payload: LinkChecklistItemRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_checklist")),
    db: Session = Depends(get_db),
) -> StudentChecklistResponse:
    try:
        return admissions_ops_service.link_document_to_checklist_item(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            document_id=document_id,
            payload=payload,
        )
    except AdmissionsOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdmissionsOpsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/exceptions", response_model=DocumentExceptionsResponse)
def get_document_exceptions(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> DocumentExceptionsResponse:
    return admissions_ops_service.get_document_exceptions(auth_context.tenant.id)


@router.get("/{document_id}/exception-summary", response_model=DocumentExceptionSummaryResponse)
def get_document_exception_summary(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> DocumentExceptionSummaryResponse:
    response = operations_service.get_document_exception_summary(auth_context.tenant.id, document_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return response


@router.get("/{document_id}/run-details", response_model=DocumentAgentRunDetailsResponse)
def get_document_agent_run_details(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> DocumentAgentRunDetailsResponse:
    response = operations_service.get_document_agent_run_details(auth_context.tenant.id, document_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return response
