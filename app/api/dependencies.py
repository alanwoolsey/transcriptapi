from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.db.models import AppUser, Tenant, TenantUserMembership
from app.services.cognito_verifier import CognitoAccessTokenVerifier, TokenVerificationError


@dataclass
class AuthenticatedTenantContext:
    user: AppUser
    tenant: Tenant
    claims: dict


verifier = CognitoAccessTokenVerifier()


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
    db: Session = Depends(get_db),
) -> AuthenticatedTenantContext:
    try:
        claims = verifier.verify(token)
    except TokenVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    subject = claims.get("sub")
    username = claims.get("username")

    stmt = (
        select(AppUser, Tenant)
        .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
        .join(Tenant, Tenant.id == TenantUserMembership.tenant_id)
        .where(
            Tenant.id == tenant_id,
            Tenant.status == "active",
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
    user, tenant = row
    return AuthenticatedTenantContext(user=user, tenant=tenant, claims=claims)
