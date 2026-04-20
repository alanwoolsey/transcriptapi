from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.access_models import CurrentUserAccessResponse, CurrentUserScopesResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=CurrentUserAccessResponse)
def get_current_user(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> CurrentUserAccessResponse:
    return _build_current_user_response(auth_context)


@router.get("/access", response_model=CurrentUserAccessResponse)
def get_current_user_access(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> CurrentUserAccessResponse:
    return _build_current_user_response(auth_context)


def _build_current_user_response(auth_context: AuthenticatedTenantContext) -> CurrentUserAccessResponse:
    authorization = auth_context.authorization
    scopes = authorization.scopes
    return CurrentUserAccessResponse(
        userId=str(auth_context.user.id),
        email=auth_context.user.email,
        displayName=auth_context.user.display_name,
        tenantId=str(auth_context.tenant.id),
        tenantSlug=auth_context.tenant.slug,
        tenantName=auth_context.tenant.name,
        baseRole=authorization.base_role,
        roles=sorted(authorization.roles),
        permissions=sorted(authorization.permissions),
        sensitivityTiers=sorted(authorization.sensitivity_tiers),
        scopes=CurrentUserScopesResponse(
            tenants=sorted(scopes.get("tenant", set())),
            campuses=sorted(scopes.get("campus", set())),
            territories=sorted(scopes.get("territory", set())),
            programs=sorted(scopes.get("program", set())),
            studentPopulations=sorted(scopes.get("student_population", set())),
            stages=sorted(scopes.get("stage", set())),
        ),
        recordExceptions=sorted(authorization.record_exceptions),
    )
