from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.dashboard_models import DashboardResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
dashboard_service = DashboardService()


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DashboardResponse:
    return dashboard_service.get_dashboard(auth_context.tenant.id)
