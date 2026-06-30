from types import SimpleNamespace
from uuid import uuid4

from app.models.assistant_models import AssistantActiveEntity, AssistantChatRequest, AssistantDocumentClassificationRequest
from app.core.config import settings
from app.services.assistant_context_service import AssistantContextService


def _auth_context():
    return SimpleNamespace(
        tenant=SimpleNamespace(id=uuid4(), name="CRTFY"),
        user=SimpleNamespace(id=uuid4(), display_name="Test User"),
        claims={"raw_token": "token"},
        authorization=SimpleNamespace(
            base_role="tenant_admin",
            roles={"tenant_admin"},
            permissions={"view_student_360"},
            sensitivity_tiers=set(),
            can=lambda permission: permission == "view_student_360",
        ),
    )


def test_context_service_retrieves_compact_current_student_context(monkeypatch):
    student = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "id": "student-1",
            "name": "Emily Johnson",
            "program": "BS Nursing",
            "stage": "Prospect",
            "risk": "Low",
            "advisor": "Alan Woolsey",
            "nextBestAction": "Request transcript",
            "transcripts": [{"id": "tx-1", "institution": "Central High", "status": "received"}],
            "documents": [{"id": "doc-1", "title": "Application", "documentType": "Application form", "status": "stored"}],
            "interactions": [{"id": "comm-1", "type": "communication", "message": "Requested transcript"}],
        }
    )
    checklist = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "status": "incomplete",
            "completionPercent": 60,
            "oneItemAway": False,
            "items": [
                {"label": "High school transcript", "done": False},
                {"label": "Application", "done": True},
            ],
        }
    )
    student_service = SimpleNamespace(
        get_student=lambda *args, **kwargs: student,
        get_student_timeline=lambda *args, **kwargs: SimpleNamespace(events=[]),
    )
    admissions_ops_service = SimpleNamespace(get_student_checklist=lambda *args, **kwargs: checklist)
    service = AssistantContextService(student_service=student_service, admissions_ops_service=admissions_ops_service)
    captured = {}

    def fake_governed(payload, auth_context):
        captured["payload"] = payload
        return {"response": "Emily is missing a high school transcript.", "policyStatus": "allowed", "guardrails": ["tenant_scoped"], "auditId": "audit-1"}

    monkeypatch.setattr(service, "call_governed_ai", fake_governed)

    response = service.run_chat(
        AssistantChatRequest(
            message="What is missing for this student?",
            route="/students/student-1",
            activeEntity=AssistantActiveEntity(type="student", id="student-1"),
        ),
        _auth_context(),
    )

    assert response.retrieval.intent == "student_checklist_question"
    assert "ANSWER_FOCUS_JSON" in captured["payload"]["message"]
    assert "APP_CONTEXT_JSON" in captured["payload"]["message"]
    assert "High school transcript" in captured["payload"]["message"]
    assert response.auditId == "audit-1"


def test_context_service_resolves_named_student_for_missing_items(monkeypatch):
    student_id = "student-mia"
    student = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "id": student_id,
            "name": "Mia Brown",
            "program": "Student Search Service",
            "stage": "Prospect",
            "risk": "Low",
            "advisor": "Alan Woolsey",
        }
    )
    search_response = SimpleNamespace(students=[student], total=1)
    checklist = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "status": "incomplete",
            "completionPercent": 0,
            "oneItemAway": False,
            "items": [
                {"label": "Application form", "done": False},
                {"label": "FAFSA", "done": False},
                {"label": "Official transcript", "done": False},
            ],
        }
    )
    student_service = SimpleNamespace(
        list_students=lambda *args, **kwargs: search_response,
        get_student=lambda *args, **kwargs: student,
    )
    admissions_ops_service = SimpleNamespace(get_student_checklist=lambda *args, **kwargs: checklist)
    service = AssistantContextService(student_service=student_service, admissions_ops_service=admissions_ops_service)
    captured = {}

    def fake_governed(payload, auth_context):
        captured["payload"] = payload
        return {"response": "Mia Brown is missing Application form, FAFSA, and Official transcript."}

    monkeypatch.setattr(service, "call_governed_ai", fake_governed)

    response = service.run_chat(
        AssistantChatRequest(message="what is student mia brown missing", route="/students"),
        _auth_context(),
    )

    assert response.retrieval.intent == "student_checklist_question"
    assert "Mia Brown" in captured["payload"]["message"]
    assert '"missingItems":["Application form","FAFSA","Official transcript"]' in captured["payload"]["message"]


def test_context_service_retrieves_counselor_today_work_for_next_best_action(monkeypatch):
    auth_context = _auth_context()
    work_response = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "buckets": [
                {
                    "key": "incomplete",
                    "label": "Incomplete",
                    "meaning": "Missing transcript, essay, fee, etc.",
                    "items": [
                        {
                            "studentId": "student-1",
                            "studentName": "Mia Brown",
                            "stage": "Prospect",
                            "section": "incomplete",
                            "priority": "urgent",
                            "priorityScore": 94,
                            "owner": {"id": str(auth_context.user.id), "name": auth_context.user.display_name},
                            "reasonToAct": {"code": "missing_docs", "label": "Student is blocked by missing documents"},
                            "suggestedAction": {"code": "request_docs", "label": "Request missing application documents"},
                            "blockingItems": [{"label": "Official transcript"}, {"label": "FAFSA"}],
                        }
                    ],
                }
            ]
        }
    )
    admissions_ops_service = SimpleNamespace(get_counselor_today_work=lambda *args, **kwargs: work_response)
    service = AssistantContextService(student_service=SimpleNamespace(), admissions_ops_service=admissions_ops_service)
    captured = {}

    def fake_governed(payload, auth_context):
        captured["payload"] = payload
        return {"response": "Start with Mia Brown and request missing application documents."}

    monkeypatch.setattr(service, "call_governed_ai", fake_governed)

    response = service.run_chat(
        AssistantChatRequest(message="what is the next best thing for me to do", route="/work"),
        auth_context,
    )

    assert response.retrieval.intent == "counselor_next_best_action"
    assert "ANSWER_FOCUS_JSON" in captured["payload"]["message"]
    assert '"questionType":"counselor_next_best_action"' in captured["payload"]["message"]
    assert "Mia Brown" in captured["payload"]["message"]
    assert "Request missing application documents" in captured["payload"]["message"]


def test_context_service_classifies_document_with_governed_ai(monkeypatch):
    service = AssistantContextService(student_service=SimpleNamespace(), admissions_ops_service=SimpleNamespace())
    captured = {}

    def fake_governed(payload, auth_context):
        captured["payload"] = payload
        return {
            "response": '{"documentType":"Government ID / residency proof","confidence":0.94,"rationale":"Visible driver license."}',
            "policyStatus": "allowed",
            "guardrails": ["document_classification"],
            "auditId": "audit-classify-1",
        }

    monkeypatch.setattr(service, "call_governed_ai", fake_governed)

    response = service.classify_document(
        AssistantDocumentClassificationRequest(
            fileName="dl example.jpeg",
            contentType="image/jpeg",
            sizeBytes=1234,
            dataBase64="abc123",
            classificationOptions=["Application form", "Government ID / residency proof"],
        ),
        _auth_context(),
    )

    assert response.documentType == "Government ID / residency proof"
    assert response.confidence == 0.94
    assert captured["payload"]["attachments"][0]["fileName"] == "dl example.jpeg"


def test_call_governed_ai_forwards_auth_and_tenant_headers(monkeypatch):
    service = AssistantContextService(student_service=SimpleNamespace(), admissions_ops_service=SimpleNamespace())
    auth_context = _auth_context()
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": "ok"}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.services.assistant_context_service.httpx.Client", FakeClient)
    monkeypatch.setattr(settings, "governed_ai_url", "https://governed.example.com")

    response = service.call_governed_ai({"message": "hello"}, auth_context)

    assert response == {"response": "ok"}
    assert captured["url"] == "https://governed.example.com/api/agent/run"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["headers"]["X-Tenant-Id"] == str(auth_context.tenant.id)
