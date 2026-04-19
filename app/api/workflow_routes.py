from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.workflow_models import WorkflowListItem
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])
workflow_service = WorkflowService()


@router.get("", response_model=list[WorkflowListItem])
def list_workflows(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[WorkflowListItem]:
    return workflow_service.list_workflows(auth_context.tenant.id)
