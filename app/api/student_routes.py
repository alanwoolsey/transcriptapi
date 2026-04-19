from fastapi import APIRouter, Depends, Query

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.student_models import Student360Record
from app.services.student_360_service import Student360Service

router = APIRouter(prefix="/students", tags=["students"])
student_service = Student360Service()


@router.get("", response_model=list[Student360Record])
def list_students(
    q: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[Student360Record]:
    return student_service.list_students(tenant_id=auth_context.tenant.id, q=q)
