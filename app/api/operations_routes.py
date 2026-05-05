import hashlib
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context, require_permission
from app.models.operations_models import (
    ActionResponse,
    AdminChecklistTemplatePayload,
    AdminChecklistTemplateRecord,
    AdminChecklistTemplatesResponse,
    AdminConfigPayload,
    AdminPermissionItem,
    AdminPermissionsResponse,
    AdminRoleItem,
    AdminRolesResponse,
    AdminScopeOptionsResponse,
    AdminUserCreateRequest,
    AdminUserItem,
    AdminUserReassignRequest,
    AdminUsersResponse,
    AgentRunActionsResponse,
    AgentRunStatusResponse,
    AdminUserUpdateRequest,
    DocumentReprocessStartResponse,
    DocumentsQueueResponse,
    HandoffResponse,
    IncompleteQueueResponse,
    MeltQueueResponse,
    ReportingOverviewResponse,
    ReviewReadyResponse,
    SensitivityTierItem,
    SensitivityTiersResponse,
    YieldQueueResponse,
)
from app.services.document_storage_service import DocumentStorageService
from app.services.operations_service import OperationsService
from app.utils.storage_utils import build_document_storage_key

router = APIRouter(tags=["operations"])
operations_service = OperationsService()
document_storage = DocumentStorageService()


def _normalize_action_response(response: ActionResponse | dict) -> ActionResponse:
    if isinstance(response, ActionResponse):
        return response
    return ActionResponse(**response)


def _normalize_reprocess_response(response: DocumentReprocessStartResponse | dict) -> DocumentReprocessStartResponse:
    if isinstance(response, DocumentReprocessStartResponse):
        return response
    return DocumentReprocessStartResponse(**response)


def _run_document_reprocess_upload(
    *,
    tenant_id: str,
    document_id: str,
    actor_user_id: str | None,
    filename: str,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
    content: bytes,
    agent_run_id: str,
) -> None:
    operations_service.run_document_reprocess_upload(
        UUID(tenant_id),
        document_id=document_id,
        actor_user_id=UUID(actor_user_id) if actor_user_id else None,
        filename=filename,
        content_type=content_type,
        requested_document_type=requested_document_type,
        use_bedrock=use_bedrock,
        content=content,
        agent_run_id=agent_run_id,
    )


def _run_stored_document_reprocess(
    *,
    tenant_id: str,
    document_id: str,
    actor_user_id: str | None,
    agent_run_id: str,
) -> None:
    operations_service.run_stored_document_reprocess(
        UUID(tenant_id),
        document_id=document_id,
        actor_user_id=UUID(actor_user_id) if actor_user_id else None,
        agent_run_id=agent_run_id,
    )


@router.get("/incomplete", response_model=IncompleteQueueResponse)
def get_incomplete_queue(
    view: str | None = Query(default=None),
    q: str | None = Query(default=None),
    ownerId: str | None = Query(default=None),
    population: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=200),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> IncompleteQueueResponse:
    return operations_service.list_incomplete(
        auth_context.tenant.id,
        view=view,
        q=q,
        owner_id=ownerId,
        population=population,
        page=page,
        page_size=pageSize,
    )


@router.get("/review-ready", response_model=ReviewReadyResponse)
def get_review_ready_queue(
    q: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ReviewReadyResponse:
    return operations_service.list_review_ready(auth_context.tenant.id, q=q)


@router.get("/documents/queue", response_model=DocumentsQueueResponse)
def get_documents_queue(
    view: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DocumentsQueueResponse:
    return operations_service.list_documents_queue(auth_context.tenant.id, view=view)


@router.post("/documents/{document_id}/confirm-match", response_model=ActionResponse)
def confirm_document_match(
    document_id: str,
    payload: dict,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.confirm_document_match(
        auth_context.tenant.id,
        document_id=document_id,
        student_id=str(payload.get("studentId") or payload.get("student_id") or ""),
        actor_user_id=auth_context.user.id,
    )


@router.post("/documents/{document_id}/reject-match", response_model=ActionResponse)
def reject_document_match(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.reject_document_match(auth_context.tenant.id, document_id=document_id, actor_user_id=auth_context.user.id)


@router.post("/documents/{document_id}/reprocess", response_model=DocumentReprocessStartResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    background_tasks: BackgroundTasks,
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DocumentReprocessStartResponse:
    response = _normalize_reprocess_response(
        operations_service.start_stored_document_reprocess(
            auth_context.tenant.id,
            document_id=document_id,
            actor_user_id=auth_context.user.id,
        )
    )
    background_tasks.add_task(
        _run_stored_document_reprocess,
        tenant_id=str(auth_context.tenant.id),
        document_id=document_id,
        actor_user_id=str(auth_context.user.id),
        agent_run_id=response.agentRunId,
    )
    return response


@router.post(
    "/documents/{document_id}/reprocess-upload",
    response_model=DocumentReprocessStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_document_upload(
    background_tasks: BackgroundTasks,
    document_id: str,
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    use_bedrock: str | None = Form(None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DocumentReprocessStartResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    filename = file.filename or "upload.bin"
    normalized_use_bedrock = str(use_bedrock or "").strip().lower() not in {"0", "false", "no", "off"}
    response = _normalize_reprocess_response(
        operations_service.start_document_reprocess_upload(
            auth_context.tenant.id,
            document_id=document_id,
            actor_user_id=auth_context.user.id,
            filename=filename,
            content_type=file.content_type,
            file_size_bytes=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            requested_document_type=document_type,
            use_bedrock=normalized_use_bedrock,
        )
    )
    document_storage.store_bytes(
        storage_key=build_document_storage_key(response.transcriptId, filename),
        content=content,
        content_type=file.content_type,
    )
    background_tasks.add_task(
        _run_document_reprocess_upload,
        tenant_id=str(auth_context.tenant.id),
        document_id=document_id,
        actor_user_id=str(auth_context.user.id),
        filename=filename,
        content_type=file.content_type,
        requested_document_type=document_type,
        use_bedrock=normalized_use_bedrock,
        content=content,
        agent_run_id=response.agentRunId,
    )
    return response


@router.get("/agent-runs/{run_id}", response_model=AgentRunStatusResponse)
def get_agent_run_status(
    run_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AgentRunStatusResponse:
    response = operations_service.get_agent_run_status(auth_context.tenant.id, run_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return response


@router.get("/agent-runs/{run_id}/actions", response_model=AgentRunActionsResponse)
def get_agent_run_actions(
    run_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AgentRunActionsResponse:
    response = operations_service.get_agent_run_actions(auth_context.tenant.id, run_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return response


@router.post("/documents/{document_id}/index", response_model=ActionResponse)
def index_document(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.index_document(auth_context.tenant.id, document_id=document_id)


@router.post("/documents/{document_id}/quarantine", response_model=ActionResponse)
def quarantine_document(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.quarantine_document(auth_context.tenant.id, document_id=document_id, actor_user_id=auth_context.user.id)


@router.post("/documents/{document_id}/release", response_model=ActionResponse)
def release_document(
    document_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.release_document(auth_context.tenant.id, document_id=document_id, actor_user_id=auth_context.user.id)


@router.get("/yield", response_model=YieldQueueResponse)
def get_yield_queue(
    view: str | None = Query(default=None),
    q: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> YieldQueueResponse:
    return operations_service.list_yield(auth_context.tenant.id, view=view, q=q)


@router.get("/melt", response_model=MeltQueueResponse)
def get_melt_queue(
    view: str | None = Query(default=None),
    q: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> MeltQueueResponse:
    return operations_service.list_melt(auth_context.tenant.id, view=view, q=q)


@router.get("/integrations/handoff", response_model=HandoffResponse)
def get_integrations_handoff(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> HandoffResponse:
    return operations_service.get_handoff(auth_context.tenant.id)


@router.post("/integrations/handoff/{student_id}/retry", response_model=ActionResponse)
def retry_handoff(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.retry_handoff(auth_context.tenant.id, student_id)


@router.post("/integrations/handoff/{student_id}/acknowledge", response_model=ActionResponse)
def acknowledge_handoff(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    return operations_service.acknowledge_handoff(auth_context.tenant.id, student_id)


@router.get("/reporting/overview", response_model=ReportingOverviewResponse)
def get_reporting_overview(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ReportingOverviewResponse:
    return operations_service.get_reporting_overview(auth_context.tenant.id)


@router.get("/admin/users", response_model=AdminUsersResponse)
def get_admin_users(
    q: str | None = Query(default=None),
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=200),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_view")),
) -> AdminUsersResponse:
    return operations_service.get_admin_users(auth_context.tenant.id, q=q, role=role, status=status, page=page, page_size=pageSize)


@router.post("/admin/users", response_model=AdminUserItem, status_code=status.HTTP_201_CREATED)
def create_admin_user(
    payload: AdminUserCreateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_create")),
) -> AdminUserItem:
    try:
        return operations_service.create_admin_user(auth_context.tenant.id, auth_context.user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/users/{user_id}", response_model=AdminUserItem)
def get_admin_user(
    user_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_view")),
) -> AdminUserItem:
    item = operations_service.get_admin_user(auth_context.tenant.id, user_id)
    if item is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return item


@router.patch("/admin/users/{user_id}", response_model=AdminUserItem)
def update_admin_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_update")),
) -> AdminUserItem:
    try:
        item = operations_service.update_admin_user(auth_context.tenant.id, auth_context.user.id, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return item


@router.post("/admin/users/{user_id}/deactivate", response_model=ActionResponse)
def deactivate_admin_user(
    user_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_deactivate")),
) -> ActionResponse:
    response = _normalize_action_response(
        operations_service.deactivate_admin_user(auth_context.tenant.id, auth_context.user.id, auth_context.user.id, user_id)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    if not response.success and response.status == "forbidden":
        raise HTTPException(status_code=403, detail=response.detail)
    return response


@router.post("/admin/users/{user_id}/reactivate", response_model=ActionResponse)
def reactivate_admin_user(
    user_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_deactivate")),
) -> ActionResponse:
    response = _normalize_action_response(
        operations_service.reactivate_admin_user(auth_context.tenant.id, auth_context.user.id, user_id)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.post("/admin/users/{user_id}/reset-password", response_model=ActionResponse)
def reset_admin_user_password(
    user_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_update")),
) -> ActionResponse:
    response = _normalize_action_response(
        operations_service.reset_admin_user_password(auth_context.tenant.id, auth_context.user.id, user_id)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    if not response.success:
        raise HTTPException(status_code=422, detail=response.detail)
    return response


@router.post("/admin/users/{user_id}/send-invite", response_model=ActionResponse)
def send_admin_user_invite(
    user_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_update")),
) -> ActionResponse:
    response = _normalize_action_response(
        operations_service.send_admin_user_invite(auth_context.tenant.id, auth_context.user.id, user_id)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    if not response.success:
        raise HTTPException(status_code=422, detail=response.detail)
    return response


@router.post("/admin/users/{user_id}/reassign", response_model=ActionResponse)
def reassign_admin_user(
    user_id: str,
    payload: AdminUserReassignRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_users_update")),
) -> ActionResponse:
    response = _normalize_action_response(
        operations_service.reassign_admin_user_objects(auth_context.tenant.id, auth_context.user.id, user_id, payload)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.get("/admin/roles", response_model=AdminRolesResponse)
def get_admin_roles(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_roles_view")),
) -> AdminRolesResponse:
    return operations_service.get_admin_roles()


@router.get("/admin/permissions", response_model=AdminPermissionsResponse)
def get_admin_permissions(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_roles_view")),
) -> AdminPermissionsResponse:
    return operations_service.get_admin_permissions()


@router.get("/admin/sensitivity-tiers", response_model=SensitivityTiersResponse)
def get_admin_sensitivity_tiers(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_roles_view")),
) -> SensitivityTiersResponse:
    return operations_service.get_sensitivity_tiers()


@router.get("/admin/scope-options", response_model=AdminScopeOptionsResponse)
def get_admin_scope_options(
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_scopes_manage")),
) -> AdminScopeOptionsResponse:
    return operations_service.get_admin_scope_options(auth_context.tenant.id)


@router.get("/admin/checklist-templates", response_model=AdminChecklistTemplatesResponse)
def get_admin_checklist_templates(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminChecklistTemplatesResponse:
    return operations_service.get_admin_checklist_templates(auth_context.tenant.id)


@router.post("/admin/checklist-templates", response_model=AdminChecklistTemplateRecord, status_code=status.HTTP_201_CREATED)
def create_admin_checklist_template(
    payload: AdminChecklistTemplatePayload,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminChecklistTemplateRecord:
    return operations_service.create_admin_checklist_template(auth_context.tenant.id, payload)


@router.get("/admin/routing-rules", response_model=AdminConfigPayload)
def get_routing_rules(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.get_routing_rules(auth_context.tenant.id)


@router.post("/admin/routing-rules", response_model=AdminConfigPayload)
def save_routing_rules(
    payload: AdminConfigPayload,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.save_routing_rules(auth_context.tenant.id, payload)


@router.get("/admin/decision-rules", response_model=AdminConfigPayload)
def get_decision_rules(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.get_decision_rules(auth_context.tenant.id)


@router.post("/admin/decision-rules", response_model=AdminConfigPayload)
def save_decision_rules(
    payload: AdminConfigPayload,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.save_decision_rules(auth_context.tenant.id, payload)


@router.get("/admin/sensitivity-settings", response_model=AdminConfigPayload)
def get_sensitivity_settings(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.get_sensitivity_settings(auth_context.tenant.id)


@router.post("/admin/sensitivity-settings", response_model=AdminConfigPayload)
def save_sensitivity_settings(
    payload: AdminConfigPayload,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AdminConfigPayload:
    return operations_service.save_sensitivity_settings(auth_context.tenant.id, payload)
