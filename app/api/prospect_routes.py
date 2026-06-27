from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.prospect_models import (
    ProspectConvertResponse,
    ProspectFitResponse,
    ProspectApiCredentialListResponse,
    ProspectApiCredentialRequest,
    ProspectApiCredentialResponse,
    ProspectApiImportRequest,
    ProspectApiImportResponse,
    ProspectAssignmentRuleListResponse,
    ProspectAssignmentRuleRequest,
    ProspectAssignmentRuleResponse,
    ProspectImportBatchListResponse,
    ProspectImportConfirmResponse,
    ProspectImportErrorFileResponse,
    ProspectImportExceptionListResponse,
    ProspectImportExceptionResolveRequest,
    ProspectImportExceptionResponse,
    ProspectImportPreviewResponse,
    ProspectImportRowsRequest,
    ProspectImportSourceCreateRequest,
    ProspectImportSourceListResponse,
    ProspectImportSourceResponse,
    ProspectImportTemplateListResponse,
    ProspectImportTemplateRequest,
    ProspectImportTemplateResponse,
    ProspectInquiryRequest,
    ProspectInquiryResponse,
    ProspectScheduledImportListResponse,
    ProspectScheduledImportRequest,
    ProspectScheduledImportResponse,
    ProspectSourceReportingResponse,
    ProspectUploadResponse,
    ProspectUploadStatusResponse,
)
from app.services.prospect_service import ProspectNotFoundError, ProspectService, ProspectValidationError

router = APIRouter(prefix="/prospects", tags=["prospects"])
prospect_service = ProspectService()


@router.get("/import-sources", response_model=ProspectImportSourceListResponse)
def list_prospect_import_sources(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportSourceListResponse:
    return prospect_service.list_import_sources(db, tenant_id=auth_context.tenant.id)


@router.post("/import-sources", response_model=ProspectImportSourceResponse)
def create_prospect_import_source(
    payload: ProspectImportSourceCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportSourceResponse:
    try:
        return prospect_service.create_import_source(
            db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            payload=payload,
        )
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/imports/preview", response_model=ProspectImportPreviewResponse)
def preview_prospect_import(
    payload: ProspectImportRowsRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportPreviewResponse:
    try:
        return prospect_service.preview_import_rows(db, tenant_id=auth_context.tenant.id, payload=payload)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/imports", response_model=ProspectImportConfirmResponse)
def confirm_prospect_import(
    payload: ProspectImportRowsRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportConfirmResponse:
    try:
        return prospect_service.import_rows(
            db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            payload=payload,
        )
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/imports", response_model=ProspectImportBatchListResponse)
def list_prospect_imports(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportBatchListResponse:
    return prospect_service.list_import_batches(db, tenant_id=auth_context.tenant.id)


@router.get("/imports/{batch_id}/errors", response_model=ProspectImportErrorFileResponse)
def get_prospect_import_error_file(
    batch_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportErrorFileResponse:
    try:
        return prospect_service.get_import_error_file(db, tenant_id=auth_context.tenant.id, batch_id=batch_id)
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/import-templates", response_model=ProspectImportTemplateListResponse)
def list_prospect_import_templates(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportTemplateListResponse:
    return prospect_service.list_import_templates(db, tenant_id=auth_context.tenant.id)


@router.post("/import-templates", response_model=ProspectImportTemplateResponse)
def create_prospect_import_template(
    payload: ProspectImportTemplateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportTemplateResponse:
    try:
        return prospect_service.create_import_template(db, tenant_id=auth_context.tenant.id, actor_user_id=auth_context.user.id, payload=payload)
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assignment-rules", response_model=ProspectAssignmentRuleListResponse)
def list_prospect_assignment_rules(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectAssignmentRuleListResponse:
    return prospect_service.list_assignment_rules(db, tenant_id=auth_context.tenant.id)


@router.post("/assignment-rules", response_model=ProspectAssignmentRuleResponse)
def create_prospect_assignment_rule(
    payload: ProspectAssignmentRuleRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectAssignmentRuleResponse:
    try:
        return prospect_service.create_assignment_rule(db, tenant_id=auth_context.tenant.id, payload=payload)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scheduled-imports", response_model=ProspectScheduledImportListResponse)
def list_prospect_scheduled_imports(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectScheduledImportListResponse:
    return prospect_service.list_scheduled_imports(db, tenant_id=auth_context.tenant.id)


@router.post("/scheduled-imports", response_model=ProspectScheduledImportResponse)
def create_prospect_scheduled_import(
    payload: ProspectScheduledImportRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectScheduledImportResponse:
    try:
        return prospect_service.create_scheduled_import(db, tenant_id=auth_context.tenant.id, payload=payload)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api-credentials", response_model=ProspectApiCredentialListResponse)
def list_prospect_api_credentials(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectApiCredentialListResponse:
    return prospect_service.list_api_credentials(db, tenant_id=auth_context.tenant.id)


@router.post("/api-credentials", response_model=ProspectApiCredentialResponse)
def create_prospect_api_credential(
    payload: ProspectApiCredentialRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectApiCredentialResponse:
    try:
        return prospect_service.create_api_credential(db, tenant_id=auth_context.tenant.id, actor_user_id=auth_context.user.id, payload=payload)
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/import-exceptions", response_model=ProspectImportExceptionListResponse)
def list_prospect_import_exceptions(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportExceptionListResponse:
    return prospect_service.list_import_exceptions(db, tenant_id=auth_context.tenant.id)


@router.post("/import-exceptions/{exception_id}/resolve", response_model=ProspectImportExceptionResponse)
def resolve_prospect_import_exception(
    exception_id: str,
    payload: ProspectImportExceptionResolveRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectImportExceptionResponse:
    try:
        return prospect_service.resolve_import_exception(db, tenant_id=auth_context.tenant.id, exception_id=exception_id, payload=payload)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api-imports", response_model=ProspectApiImportResponse)
def create_prospect_api_import(
    payload: ProspectApiImportRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectApiImportResponse:
    try:
        return prospect_service.api_import(db, tenant_id=auth_context.tenant.id, actor_user_id=auth_context.user.id, payload=payload)
    except ProspectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProspectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/source-reporting", response_model=ProspectSourceReportingResponse)
def get_prospect_source_reporting(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> ProspectSourceReportingResponse:
    return prospect_service.get_source_reporting(db, tenant_id=auth_context.tenant.id)


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
