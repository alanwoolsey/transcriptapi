from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.utility_import_routes import router


def _build_test_app(roles):
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(roles=set(roles), base_role=roles[0] if roles else None),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_tenant_admin_can_create_import_job():
    client = TestClient(_build_test_app(["tenant_admin"]))

    response = client.post("/api/v1/utilities/imports/jobs", json={"fileName": "prospects.csv"})

    assert response.status_code == 201
    assert response.json()["fileName"] == "prospects.csv"
    assert response.json()["status"] == "draft"


def test_non_admin_cannot_list_import_jobs():
    client = TestClient(_build_test_app(["admissions_counselor"]))

    response = client.get("/api/v1/utilities/imports/jobs")

    assert response.status_code == 403


def test_master_tenant_admin_can_save_template():
    client = TestClient(_build_test_app(["master_tenant_admin"]))

    response = client.post(
        "/api/v1/utilities/imports/templates",
        json={"name": "Manual Inquiry Upload", "mappings": [{"source": "Email", "target": "email"}]},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Manual Inquiry Upload"
