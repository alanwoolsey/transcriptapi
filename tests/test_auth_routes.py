from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_routes import router
from app.db import get_db
from app.services.auth_service import AuthService, CognitoAuthError, LocalUserNotFoundError


def _build_test_app() -> FastAPI:
    def override_get_db():
        yield None

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    return app


def test_login_returns_404_when_local_user_mapping_is_missing(monkeypatch):
    from app.api import auth_routes

    def fake_login(db, payload):
        raise LocalUserNotFoundError(payload.username)

    monkeypatch.setattr(auth_routes.auth_service, "login", fake_login)

    client = TestClient(_build_test_app())
    response = client.post("/api/auth/login", json={"username": "missing@example.com", "password": "secret"})

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found."}


def test_login_returns_new_password_required_challenge(monkeypatch):
    from app.api import auth_routes

    tenant_id = str(uuid4())

    def fake_login(db, payload):
        return {
            "tenant_id": tenant_id,
            "tenant_name": "Acme University",
            "tenant_code": "acme",
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "session-token",
        }

    monkeypatch.setattr(auth_routes.auth_service, "login", fake_login)

    client = TestClient(_build_test_app())
    response = client.post("/api/auth/login", json={"username": "user@example.com", "password": "secret"})

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": tenant_id,
        "tenant_name": "Acme University",
        "tenant_code": "acme",
        "challenge_name": "NEW_PASSWORD_REQUIRED",
        "session": "session-token",
    }


def test_complete_new_password_returns_tokens(monkeypatch):
    from app.api import auth_routes

    tenant_id = str(uuid4())

    def fake_complete(db, payload):
        return {
            "tenant_id": tenant_id,
            "tenant_name": "Acme University",
            "tenant_code": "acme",
            "access_token": "access-token",
            "id_token": "id-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(auth_routes.auth_service, "complete_new_password", fake_complete)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/auth/complete-new-password",
        json={"username": "user@example.com", "new_password": "NewPassword123!", "session": "session-token"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_code"] == "acme"
    assert response.json()["access_token"] == "access-token"


def test_change_password_maps_cognito_errors(monkeypatch):
    from app.api import auth_routes

    def fake_change(payload):
        raise CognitoAuthError("bad password", 400)

    monkeypatch.setattr(auth_routes.auth_service, "change_password", fake_change)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/auth/change-password",
        json={
            "access_token": "access-token",
            "previous_password": "old-password",
            "proposed_password": "new-password",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "bad password"}


def test_auth_service_uses_local_cognito_username_for_login(monkeypatch):
    service = AuthService()
    calls = {}
    resolved = SimpleNamespace(
        user=SimpleNamespace(email="user@example.com"),
        tenant=SimpleNamespace(id=uuid4(), name="Acme University", slug="acme"),
    )

    monkeypatch.setattr(service, "_resolve_user", lambda db, email: resolved)

    def fake_initiate_auth(username, password):
        calls["username"] = username
        calls["password"] = password
        return {
            "AuthenticationResult": {
                "AccessToken": "access-token",
                "IdToken": "id-token",
                "RefreshToken": "refresh-token",
                "ExpiresIn": 3600,
                "TokenType": "Bearer",
            }
        }

    monkeypatch.setattr(service, "_initiate_auth", fake_initiate_auth)

    response = service.login(db=None, payload=SimpleNamespace(username="user@example.com", password="secret"))

    assert calls == {"username": "user@example.com", "password": "secret"}
    assert response.tenant_code == "acme"
    assert response.access_token == "access-token"


def test_auth_service_prefers_default_active_membership(monkeypatch):
    service = AuthService()

    rows = [
        (
            SimpleNamespace(email="user@example.com"),
            SimpleNamespace(id=uuid4(), name="Default Tenant", slug="default-tenant"),
        )
    ]

    class FakeResult:
        def first(self):
            return rows[0]

    class FakeDb:
        def execute(self, stmt):
            return FakeResult()

    resolved = service._resolve_user(FakeDb(), "user@example.com")

    assert resolved.user.email == "user@example.com"
    assert resolved.tenant.slug == "default-tenant"
