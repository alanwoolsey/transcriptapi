from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.ops_models import WorkItemsResponse, WorkProjectionRebuildResponse, WorkProjectionStatusResponse, WorkSummaryResponse
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.work_state_projector import WorkStateProjector

router = APIRouter(prefix="/work", tags=["work"])
admissions_ops_service = AdmissionsOpsService()
work_state_projector = WorkStateProjector()


@router.get("/summary", response_model=WorkSummaryResponse)
def get_work_summary(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkSummaryResponse:
    return admissions_ops_service.get_work_summary(auth_context.tenant.id)


@router.get("/items", response_model=WorkItemsResponse)
def get_work_items(
    section: str | None = Query(default=None),
    population: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    ownerId: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    aging_bucket: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    page: int | None = Query(default=None, ge=1),
    pageSize: int | None = Query(default=None, ge=1, le=200),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkItemsResponse:
    resolved_limit = pageSize or limit
    resolved_offset = ((page - 1) * resolved_limit) if page else offset
    return admissions_ops_service.get_work_items(
        auth_context.tenant.id,
        section=section,
        population=population,
        owner=(ownerId or owner),
        priority=priority,
        aging_bucket=aging_bucket,
        q=q,
        limit=resolved_limit,
        offset=resolved_offset,
    )


@router.get("/projection/status", response_model=WorkProjectionStatusResponse)
def get_work_projection_status(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionStatusResponse:
    status_payload = work_state_projector.get_projection_status(auth_context.tenant.id)
    if status_payload["lastProjectedAt"] is not None and not isinstance(status_payload["lastProjectedAt"], str):
        status_payload["lastProjectedAt"] = admissions_ops_service._isoformat(status_payload["lastProjectedAt"])
    return WorkProjectionStatusResponse(**status_payload)


@router.post("/projection/rebuild", response_model=WorkProjectionRebuildResponse, status_code=status.HTTP_202_ACCEPTED)
def rebuild_work_projection(
    reset: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionRebuildResponse:
    if reset:
        work_state_projector.reset_tenant_projection(auth_context.tenant.id)
    chunk_result = work_state_projector.rebuild_tenant_projection_chunk(
        auth_context.tenant.id,
        limit=limit,
        cursor=cursor,
    )
    return WorkProjectionRebuildResponse(
        status="ready" if chunk_result["remainingStudents"] == 0 else "partial",
        detail="Work-state projection rebuild chunk completed.",
        processedStudents=int(chunk_result["processedStudents"]),
        nextCursor=chunk_result["nextCursor"],
        remainingStudents=int(chunk_result["remainingStudents"]),
    )
