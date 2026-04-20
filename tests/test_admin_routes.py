from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.operations_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(
                can=lambda permission: True,
                can_access_tier=lambda tier: True,
            ),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_get_admin_users_returns_paginated_payload(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_users",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "userId": "123",
                    "email": "jane@example.edu",
                    "displayName": "Jane Smith",
                    "status": "active",
                    "baseRole": "director",
                    "roles": ["admissions_counselor"],
                    "permissions": ["view_student_360", "edit_checklist"],
                    "sensitivityTiers": ["basic_profile"],
                    "scopes": {
                        "campuses": ["main"],
                        "territories": ["midwest"],
                        "programs": ["business"],
                        "studentPopulations": ["transfer"],
                        "stages": ["*"],
                    },
                    "lastLoginAt": "2026-04-20T10:00:00Z",
                    "createdAt": "2026-04-01T12:00:00Z",
                    "updatedAt": "2026-04-20T10:00:00Z",
                }
            ],
            "page": 1,
            "pageSize": 25,
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/users?q=jane&page=1&pageSize=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["userId"] == "123"


def test_create_admin_user_returns_created_record(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "create_admin_user",
        lambda tenant_id, actor_user_id, payload: {
            "userId": "123",
            "email": payload.email,
            "displayName": payload.displayName,
            "status": "invited",
            "baseRole": payload.baseRole,
            "roles": payload.roles,
            "permissions": ["admin_users_view"],
            "sensitivityTiers": payload.sensitivityTiers,
            "scopes": payload.scopes.model_dump(),
            "lastLoginAt": None,
            "createdAt": "2026-04-20T10:00:00Z",
            "updatedAt": "2026-04-20T10:00:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "newuser@example.edu",
            "displayName": "New User",
            "baseRole": "director",
            "roles": ["admissions_processor"],
            "sensitivityTiers": ["basic_profile"],
            "scopes": {
                "campuses": ["main"],
                "territories": ["midwest"],
                "programs": ["business"],
                "studentPopulations": ["transfer"],
                "stages": ["*"],
            },
            "sendInvite": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "invited"


def test_get_admin_user_returns_404_when_missing(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(operations_routes.operations_service, "get_admin_user", lambda tenant_id, user_id: None)

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/admin/users/{uuid4()}")

    assert response.status_code == 404


def test_patch_admin_user_returns_updated_record(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "update_admin_user",
        lambda tenant_id, actor_user_id, user_id, payload: {
            "userId": user_id,
            "email": "jane@example.edu",
            "displayName": payload.displayName,
            "status": payload.status,
            "baseRole": "director",
            "roles": payload.roles,
            "permissions": ["admin_users_update"],
            "sensitivityTiers": payload.sensitivityTiers,
            "scopes": payload.scopes.model_dump(),
            "lastLoginAt": "2026-04-20T10:00:00Z",
            "createdAt": "2026-04-01T12:00:00Z",
            "updatedAt": "2026-04-20T10:00:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.patch(
        f"/api/v1/admin/users/{uuid4()}",
        json={
            "displayName": "Jane Smith",
            "roles": ["admissions_counselor", "reviewer_evaluator"],
            "sensitivityTiers": ["basic_profile", "academic_record"],
            "scopes": {
                "territories": ["midwest", "south"],
                "programs": ["business", "transfer"],
            },
            "status": "active",
        },
    )

    assert response.status_code == 200
    assert response.json()["displayName"] == "Jane Smith"


def test_deactivate_admin_user_surfaces_forbidden(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "deactivate_admin_user",
        lambda tenant_id, actor_user_id, current_user_id, user_id: {
            "success": False,
            "status": "forbidden",
            "detail": "Cannot deactivate the last admin user.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/admin/users/{uuid4()}/deactivate")

    assert response.status_code == 403


def test_get_admin_roles_returns_items(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_roles",
        lambda: {"items": [{"key": "admissions_counselor", "label": "Admissions Counselor", "description": "Works students, yield, melt", "active": True}]},
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 200
    assert response.json()["items"][0]["key"] == "admissions_counselor"


def test_get_admin_scope_options_returns_values(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_scope_options",
        lambda tenant_id: {
            "campuses": ["*", "main"],
            "territories": ["*", "midwest"],
            "programs": ["*", "business"],
            "studentPopulations": ["*", "transfer"],
            "stages": ["*", "incomplete"],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/scope-options")

    assert response.status_code == 200
    assert response.json()["territories"] == ["*", "midwest"]
