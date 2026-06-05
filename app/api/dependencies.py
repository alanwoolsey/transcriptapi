from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Tenant, TenantUserMembership
from app.db.session import get_session_factory
from app.services.rbac_service import AuthorizationProfile, RBACService
from app.services.cognito_verifier import CognitoAccessTokenVerifier, TokenVerificationError


@dataclass
class AuthenticatedTenantContext:
    user: AppUser
    tenant: Tenant
    claims: dict
    authorization: AuthorizationProfile


verifier = CognitoAccessTokenVerifier()
rbac_service = RBACService()


def get_authorization_token(authorization: str | None = Header(default=None, alias="Authorization")) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header is required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required.")
    return token.strip()


def get_tenant_id(x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id")) -> UUID:
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required.",
        )
    try:
        return UUID(x_tenant_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-Id must be a valid UUID.") from exc


def get_current_tenant_context(
    tenant_id: UUID = Depends(get_tenant_id),
    token: str = Depends(get_authorization_token),
) -> AuthenticatedTenantContext:
    try:
        claims = verifier.verify(token)
    except TokenVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    subject = claims.get("sub")
    username = claims.get("username")
    session_factory = get_session_factory()
    with session_factory() as db:
        stmt = (
            select(AppUser, Tenant, TenantUserMembership.role)
            .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
            .join(Tenant, Tenant.id == TenantUserMembership.tenant_id)
            .where(
                Tenant.id == tenant_id,
                Tenant.status == "active",
                AppUser.tenant_id == tenant_id,
                AppUser.is_active.is_(True),
                TenantUserMembership.status == "active",
                or_(
                    AppUser.cognito_sub == subject,
                    AppUser.email == username,
                ),
            )
            .limit(1)
        )
        row = db.execute(stmt).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not authorized for this tenant.")
        if len(row) == 2:
            user, tenant = row
            membership_role = None
        else:
            user, tenant, membership_role = row
        authorization = rbac_service.resolve_profile(
            db,
            tenant_id=tenant.id,
            user_id=user.id,
            membership_role=membership_role,
        )
        db.expunge(user)
        db.expunge(tenant)
        return AuthenticatedTenantContext(user=user, tenant=tenant, claims=claims, authorization=authorization)


def require_permission(permission_code: str):
    def dependency(auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context)) -> AuthenticatedTenantContext:
        if not auth_context.authorization.can(permission_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission_code}")
        return auth_context

    return dependency


def require_sensitivity_tier(tier: str):
    def dependency(auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context)) -> AuthenticatedTenantContext:
        if not auth_context.authorization.can_access_tier(tier):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing sensitivity tier: {tier}")
        return auth_context

    return dependency
