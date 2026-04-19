from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.trust_models import TrustCaseItem
from app.services.trust_service import TrustService

router = APIRouter(prefix="/trust", tags=["trust"])
trust_service = TrustService()


@router.get("/cases", response_model=list[TrustCaseItem])
def list_trust_cases(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[TrustCaseItem]:
    return trust_service.list_cases(auth_context.tenant.id)
