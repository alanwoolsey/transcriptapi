from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.me_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            user=SimpleNamespace(id=uuid4(), email="user@example.com", display_name="Taylor Reed"),
            tenant=SimpleNamespace(id=uuid4(), slug="test-tenant", name="Test Tenant"),
            claims={},
            authorization=SimpleNamespace(
                base_role="admissions_counselor",
                roles={"admissions_counselor", "reviewer_evaluator"},
                permissions={"view_student_360", "edit_checklist"},
                sensitivity_tiers={"basic_profile", "academic_record"},
                scopes={
                    "tenant": {"tenant-1"},
                    "campus": {"north"},
                    "territory": {"midwest"},
                    "program": {"nursing"},
                    "student_population": {"transfer"},
                    "stage": {"incomplete"},
                },
                record_exceptions={"nursing"},
            ),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_get_current_user_returns_access_payload():
    client = TestClient(_build_test_app())
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["displayName"] == "Taylor Reed"
    assert payload["permissions"] == ["edit_checklist", "view_student_360"]
    assert payload["scopes"]["territories"] == ["midwest"]


def test_get_current_user_access_returns_same_payload_shape():
    client = TestClient(_build_test_app())
    response = client.get("/api/v1/me/access")

    assert response.status_code == 200
    payload = response.json()
    assert payload["baseRole"] == "admissions_counselor"
    assert payload["roles"] == ["admissions_counselor", "reviewer_evaluator"]
    assert payload["recordExceptions"] == ["nursing"]
