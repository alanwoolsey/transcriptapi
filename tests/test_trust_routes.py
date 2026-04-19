from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.trust_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_trust_cases_returns_array(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "list_cases",
        lambda tenant_id: [
            {
                "id": "TRUST-01",
                "student": "Student Name",
                "severity": "High",
                "signal": "Issuer mismatch",
                "evidence": "Explanation of the trust issue.",
                "status": "Quarantined",
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/trust/cases")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["id"] == "TRUST-01"
