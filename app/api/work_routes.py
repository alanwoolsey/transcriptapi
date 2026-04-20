from fastapi import APIRouter, Depends, Query

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.ops_models import WorkItemsResponse, WorkSummaryResponse
from app.services.admissions_ops_service import AdmissionsOpsService

router = APIRouter(prefix="/work", tags=["work"])
admissions_ops_service = AdmissionsOpsService()


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
