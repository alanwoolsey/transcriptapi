from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.decision_models import DecisionWorkbenchItem
from app.services.decision_service import DecisionService

router = APIRouter(prefix="/decisions", tags=["decisions"])
decision_service = DecisionService()


@router.get("", response_model=list[DecisionWorkbenchItem])
def list_decisions(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[DecisionWorkbenchItem]:
    return decision_service.list_decisions(auth_context.tenant.id)
