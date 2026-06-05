from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.prospect_models import (
    ProspectConvertResponse,
    ProspectFitResponse,
    ProspectInquiryRequest,
    ProspectInquiryResponse,
    ProspectUploadResponse,
    ProspectUploadStatusResponse,
)
from app.services.prospect_service import ProspectNotFoundError, ProspectService, ProspectValidationError

router = APIRouter(prefix="/prospects", tags=["prospects"])
prospect_service = ProspectService()


@router.post("/inquiries", response_model=ProspectInquiryResponse)
def create_prospect_inquiry(
    payload: ProspectInquiryRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectInquiryResponse:
    try:
        return prospect_service.create_inquiry(
            db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            payload=payload,
        )
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transcripts/uploads", response_model=ProspectUploadResponse)
async def create_prospect_transcript_upload(
    file: UploadFile = File(...),
    email: str = Form(...),
    population: str = Form(...),
    programInterest: str | None = Form(default=None),
    termInterest: str | None = Form(default=None),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectUploadResponse:
    try:
        content = await file.read()
        return prospect_service.create_transcript_upload(
            db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            email=email,
            population=population,
            program_interest=programInterest,
            term_interest=termInterest,
            filename=file.filename or "transcript.pdf",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/transcripts/uploads/{upload_id}/status", response_model=ProspectUploadStatusResponse)
def get_prospect_upload_status(
    upload_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> ProspectUploadStatusResponse:
    try:
        return prospect_service.get_upload_status(auth_context.tenant.id, upload_id)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{prospect_id}/fit", response_model=ProspectFitResponse)
def get_prospect_fit(
    prospect_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> ProspectFitResponse:
    try:
        return prospect_service.get_fit(auth_context.tenant.id, prospect_id)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{prospect_id}/convert-application", response_model=ProspectConvertResponse)
def convert_prospect_application(
    prospect_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_checklist")),
    db: Session = Depends(get_db),
) -> ProspectConvertResponse:
    try:
        return prospect_service.convert_application(
            db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            prospect_id=prospect_id,
        )
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
