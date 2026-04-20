from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import dependencies


def test_get_authorization_token_requires_bearer_scheme():
    with pytest.raises(HTTPException) as exc:
        dependencies.get_authorization_token("Basic abc")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Bearer token is required."


def test_get_tenant_id_requires_uuid():
    with pytest.raises(HTTPException) as exc:
        dependencies.get_tenant_id("not-a-uuid")

    assert exc.value.status_code == 400
    assert exc.value.detail == "X-Tenant-Id must be a valid UUID."


def test_get_current_tenant_context_rejects_invalid_token(monkeypatch):
    tenant_id = uuid4()

    monkeypatch.setattr(
        dependencies.verifier,
        "verify",
        lambda token: (_ for _ in ()).throw(dependencies.TokenVerificationError("Invalid access token.")),
    )

    with pytest.raises(HTTPException) as exc:
        dependencies.get_current_tenant_context(tenant_id=tenant_id, token="bad-token")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid access token."


def test_get_current_tenant_context_requires_active_membership(monkeypatch):
    tenant_id = uuid4()
    claims = {"sub": "sub-123", "username": "user@example.com"}

    monkeypatch.setattr(dependencies.verifier, "verify", lambda token: claims)

    class FakeResult:
        def first(self):
            return None

    class FakeDb:
        def execute(self, stmt):
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(dependencies, "get_session_factory", lambda: FakeDb)
    with pytest.raises(HTTPException) as exc:
        dependencies.get_current_tenant_context(tenant_id=tenant_id, token="good-token")

    assert exc.value.status_code == 403
    assert exc.value.detail == "User is not authorized for this tenant."


def test_get_current_tenant_context_returns_user_and_tenant(monkeypatch):
    tenant_id = uuid4()
    claims = {"sub": "sub-123", "username": "user@example.com"}
    user = SimpleNamespace(id=uuid4(), email="user@example.com")
    tenant = SimpleNamespace(id=tenant_id, slug="test")
    authorization = SimpleNamespace(can=lambda code: True, can_access_tier=lambda tier: True)

    monkeypatch.setattr(dependencies.verifier, "verify", lambda token: claims)
    monkeypatch.setattr(
        dependencies.rbac_service,
        "resolve_profile",
        lambda db, tenant_id, user_id, membership_role: authorization,
    )

    class FakeResult:
        def first(self):
            return (user, tenant, "counselor")

    class FakeDb:
        def execute(self, stmt):
            return FakeResult()
        def expunge(self, value):
            return None
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(dependencies, "get_session_factory", lambda: FakeDb)
    context = dependencies.get_current_tenant_context(tenant_id=tenant_id, token="good-token")

    assert context.user is user
    assert context.tenant is tenant
    assert context.claims == claims
    assert context.authorization is authorization


def test_require_permission_rejects_missing_permission():
    dependency = dependencies.require_permission("release_decision")

    with pytest.raises(HTTPException) as exc:
        dependency(auth_context=SimpleNamespace(authorization=SimpleNamespace(can=lambda code: False)))

    assert exc.value.status_code == 403


def test_require_sensitivity_tier_rejects_missing_tier():
    dependency = dependencies.require_sensitivity_tier("trust_fraud_flags")

    with pytest.raises(HTTPException) as exc:
        dependency(auth_context=SimpleNamespace(authorization=SimpleNamespace(can_access_tier=lambda tier: False)))

    assert exc.value.status_code == 403
