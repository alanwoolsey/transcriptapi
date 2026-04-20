from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.dashboard_models import DashboardActivityItem, DashboardAgentItem, DashboardFunnelItem, DashboardResponse, DashboardRoutingMixItem, DashboardStat
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
dashboard_service = DashboardService()


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> DashboardResponse:
    return dashboard_service.get_dashboard(auth_context.tenant.id)


@router.get("/stats", response_model=list[DashboardStat])
def get_dashboard_stats(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DashboardStat]:
    return dashboard_service.get_stats(auth_context.tenant.id)


@router.get("/funnel", response_model=list[DashboardFunnelItem])
def get_dashboard_funnel(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DashboardFunnelItem]:
    return dashboard_service.get_funnel(auth_context.tenant.id)


@router.get("/routing-mix", response_model=list[DashboardRoutingMixItem])
def get_dashboard_routing_mix(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DashboardRoutingMixItem]:
    return dashboard_service.get_routing_mix(auth_context.tenant.id)


@router.get("/agents", response_model=list[DashboardAgentItem])
def get_dashboard_agents(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DashboardAgentItem]:
    return dashboard_service.get_agents(auth_context.tenant.id)


@router.get("/activity", response_model=list[DashboardActivityItem])
def get_dashboard_activity(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DashboardActivityItem]:
    return dashboard_service.get_activity(auth_context.tenant.id)
