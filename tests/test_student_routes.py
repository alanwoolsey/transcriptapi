from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.student_routes import router
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.operations_service import OperationsService
from app.services.student_360_service import Student360Service


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(can=lambda permission: True),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_students_returns_records(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.student_service,
        "list_students",
        lambda tenant_id, q=None, **kwargs: {
            "students": [
                {
                    "id": "student-1",
                    "name": "Hunter Haymore",
                    "program": "Transcript intake",
                    "institutionGoal": "Grantsville High",
                    "stage": "Decision-ready",
                    "risk": "Low",
                    "fitScore": 86,
                    "depositLikelihood": 61,
                    "summary": "Latest transcript parsed from Grantsville High. Outcome draft prepared for review.",
                    "gpa": 0.0,
                    "creditsAccepted": 0,
                    "transcriptsCount": 1,
                    "advisor": "Unassigned",
                    "tags": ["Transcript intake", "Low", "Decision-ready"],
                    "nextBestAction": "Open the student record and review the latest transcript outcome.",
                }
            ],
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["students"][0]["name"] == "Hunter Haymore"
    assert payload["students"][0]["institutionGoal"] == "Grantsville High"
    assert "transcripts" not in payload["students"][0]


def test_list_students_passes_search_query(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_list_students(tenant_id, q=None, **kwargs):
        captured["tenant_id"] = tenant_id
        captured["q"] = q
        captured.update(kwargs)
        return {"students": [], "total": 0}

    monkeypatch.setattr(student_routes.student_service, "list_students", fake_list_students)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students?q=hunter")

    assert response.status_code == 200
    assert captured["q"] == "hunter"
    assert captured["limit"] == 50


def test_get_student_returns_detail_record(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_get_student(tenant_id, student_id, authorization=None):
        captured["tenant_id"] = tenant_id
        captured["student_id"] = student_id
        return {
            "id": student_id,
            "name": "Hunter Haymore",
            "preferredName": "Hunter",
            "email": None,
            "phone": None,
            "program": "Transcript intake",
            "institutionGoal": "Grantsville High",
            "stage": "Decision-ready",
            "risk": "Low",
            "fitScore": 86,
            "depositLikelihood": 61,
            "summary": "Latest transcript parsed from Grantsville High. Outcome draft prepared for review.",
            "gpa": 0.0,
            "creditsAccepted": 0,
            "transcriptsCount": 1,
            "advisor": "Unassigned",
            "tags": ["Transcript intake", "Low", "Decision-ready"],
            "nextBestAction": "Open the student record and review the latest transcript outcome.",
            "city": "Location pending",
            "lastActivity": "2026-04-19T15:21:59Z",
            "checklist": [{"label": "Identity matched", "done": True}],
            "transcripts": [],
            "termGpa": [],
            "recommendation": {
                "summary": "Latest transcript is ready for counselor review.",
                "fitNarrative": "Current transcript evidence from Grantsville High was parsed successfully and is available for review.",
                "nextBestAction": "Open the student record and review the latest transcript outcome.",
            },
            "application": {
                "id": "APP-123",
                "status": "Submitted",
                "type": "Transfer application",
                "entryTerm": "Fall 2026",
                "campus": "Main",
                "delivery": "On campus",
                "startedAt": "2026-05-01T00:00:00Z",
                "submittedAt": "2026-05-18T00:00:00Z",
                "residency": "In state",
                "studentType": "Transfer",
                "nextStep": "Review missing transcript",
            },
            "financialAid": {
                "usingFinancialAid": True,
                "status": "In progress",
                "fafsa": {
                    "status": "Received",
                    "receivedAt": "2026-05-20T00:00:00Z",
                    "aidYear": "2026-2027",
                    "sai": "3200",
                    "dependencyStatus": "Dependent",
                    "verificationStatus": "Not selected",
                },
                "packageStatus": "Estimated",
                "estimatedAid": 12500,
                "scholarshipStatus": "Offered",
                "scholarshipAmount": 4000,
                "nextStep": "Confirm award package",
            },
            "scholarshipOptions": [
                {
                    "id": "academic-merit",
                    "name": "Academic Merit Scholarship",
                    "amount": 6500,
                    "owner": "Admissions",
                    "description": "For applicants with strong academic performance.",
                    "action": "Generate merit estimate",
                    "matchScore": 88,
                    "status": "Strong match",
                    "evidence": ["Transcript GPA is 3.72."],
                    "missing": [],
                }
            ],
            "scholarshipOffers": [
                {
                    "id": "offer-1",
                    "name": "Academic Merit Scholarship",
                    "sourceType": "Institutional",
                    "provider": "This institution",
                    "amount": 5000,
                    "status": "Offered",
                    "offeredAt": "2026-06-15T00:00:00Z",
                    "renewable": True,
                    "requirements": "Maintain 3.0 GPA and full-time enrollment.",
                    "notes": "Stackable with need-based aid.",
                }
            ],
        }

    monkeypatch.setattr(student_routes.student_service, "get_student", fake_get_student)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["student"]["id"] == "student-1"
    assert payload["student"]["recommendation"]["nextBestAction"] == payload["student"]["nextBestAction"]
    assert payload["student"]["application"]["status"] == "Submitted"
    assert payload["student"]["financialAid"]["fafsa"]["aidYear"] == "2026-2027"
    assert payload["student"]["scholarshipOptions"][0]["matchScore"] == 88
    assert payload["student"]["scholarshipOffers"][0]["sourceType"] == "Institutional"
    assert captured["student_id"] == "student-1"


def test_get_student_returns_404_when_missing(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(student_routes.student_service, "get_student", lambda tenant_id, student_id, authorization=None: None)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/missing-student")

    assert response.status_code == 404


def test_student_360_scholarship_helpers_normalize_state_payload():
    service = Student360Service()
    state = {
        "scholarship_options": [
            {
                "id": "academic-merit",
                "name": "Academic Merit Scholarship",
                "amount": "$6,500",
                "match_score": "88",
                "evidence": ["Transcript GPA is 3.72.", ""],
            }
        ],
        "scholarship_offers": [
            {
                "id": "offer-1",
                "name": "Academic Merit Scholarship",
                "source_type": "institutional",
                "amount": "5000",
                "offered_at": "2026-06-15",
                "renewable": "true",
            },
            {
                "id": "offer-2",
                "name": "Community Foundation Award",
                "sourceType": "External",
                "amount": "1,500.50",
                "offeredAt": "2026-06-10T00:00:00Z",
                "renewable": False,
            },
        ],
    }

    options = service._build_scholarship_options(
        state=state,
        student=SimpleNamespace(latest_cumulative_gpa=3.2),
        transcripts=[],
        prospect=None,
        program_name="Nursing BSN",
    )
    offers = service._build_scholarship_offers(state)
    aid = service._build_financial_aid_summary(state={}, milestones=[], scholarship_offers=offers)

    assert options[0].amount == 6500
    assert options[0].matchScore == 88
    assert options[0].evidence == ["Transcript GPA is 3.72."]
    assert offers[0].sourceType == "Institutional"
    assert offers[0].amount == 5000
    assert offers[0].offeredAt == "2026-06-15T00:00:00Z"
    assert offers[0].renewable is True
    assert offers[1].sourceType == "External"
    assert offers[1].amount == 1500.5
    assert aid.scholarshipAmount == 6500.5


def test_patch_student_updates_program(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_update_program(db, tenant_id, actor_user_id, student_id, program_name):
        captured["student_id"] = student_id
        captured["program_name"] = program_name
        captured["actor_user_id"] = actor_user_id
        return {
            "id": "STU-123",
            "program": program_name,
            "degreeProgram": program_name,
            "stage": "Applicant",
        }

    monkeypatch.setattr(student_routes.student_service, "update_student_program", fake_update_program)

    client = TestClient(_build_test_app())
    response = client.patch(
        "/api/v1/students/STU-123",
        json={"program": "BS Computer Science", "degreeProgram": "BS Computer Science"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "STU-123"
    assert payload["program"] == "BS Computer Science"
    assert payload["degreeProgram"] == "BS Computer Science"
    assert payload["stage"] == "Applicant"
    assert captured["student_id"] == "STU-123"


def test_post_student_next_action_records_work_state(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_record_next_action(db, tenant_id, actor_user_id, student_id, payload):
        captured["student_id"] = student_id
        captured["action_type"] = payload.actionType
        captured["note"] = payload.note
        return {
            "id": "STU-123",
            "nextAction": payload.nextAction,
            "nextFollowUpAt": payload.nextFollowUpAt,
            "lastContactedAt": payload.lastContactedAt,
            "contactOutcome": payload.contactOutcome,
            "lastActivity": payload.lastActivity,
        }

    monkeypatch.setattr(student_routes.student_service, "record_next_action", fake_record_next_action)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/students/STU-123/next-action",
        json={
            "actionType": "contacted",
            "note": "Student asked about transcript status.",
            "nextAction": "Follow up on missing transcript",
            "contactOutcome": "contacted",
            "lastContactedAt": "2026-06-19T15:30:00.000Z",
            "nextFollowUpAt": "2026-06-20T14:00:00.000Z",
            "lastActivity": "Just now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nextAction"] == "Follow up on missing transcript"
    assert payload["contactOutcome"] == "contacted"
    assert captured["student_id"] == "STU-123"
    assert captured["action_type"] == "contacted"


def test_post_student_interaction_returns_saved_interaction(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_create_interaction(db, tenant_id, actor_user_id, student_id, payload):
        captured["student_id"] = student_id
        captured["type"] = payload.type
        captured["outcome"] = payload.outcome
        return {
            "interaction": {
                "id": "int-123",
                "type": payload.type,
                "outcome": payload.outcome,
                "title": payload.title,
                "note": payload.note,
                "description": payload.description,
                "nextAction": payload.nextAction,
                "nextFollowUpAt": payload.nextFollowUpAt,
                "occurredAt": payload.occurredAt,
                "actor": payload.actor,
                "source": payload.source,
            }
        }

    monkeypatch.setattr(student_routes.student_service, "create_student_interaction", fake_create_interaction)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/students/STU-123/interactions",
        json={
            "type": "call",
            "outcome": "reached_student",
            "title": "Call",
            "note": "Student asked about transcript status.",
            "description": "Student asked about transcript status.",
            "nextAction": "Request updated transcript",
            "nextFollowUpAt": "2026-06-22T15:00:00.000Z",
            "occurredAt": "2026-06-19T18:30:00.000Z",
            "actor": "Elian Brooks",
            "source": "student_360",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction"]["id"] == "int-123"
    assert payload["interaction"]["nextAction"] == "Request updated transcript"
    assert captured == {"student_id": "STU-123", "type": "call", "outcome": "reached_student"}


def test_get_student_interactions_returns_items(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.student_service,
        "list_student_interactions",
        lambda tenant_id, student_id: {
            "items": [
                {
                    "id": "int-123",
                    "type": "call",
                    "outcome": "reached_student",
                    "title": "Call",
                    "note": "Student asked about transcript status.",
                    "description": "Student asked about transcript status.",
                    "nextAction": "Request updated transcript",
                    "nextFollowUpAt": "2026-06-22T15:00:00.000Z",
                    "occurredAt": "2026-06-19T18:30:00.000Z",
                    "actor": "Elian Brooks",
                    "source": "student_360",
                }
            ]
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/STU-123/interactions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "int-123"
    assert payload["items"][0]["actor"] == "Elian Brooks"


def test_patch_student_interaction_returns_updated_interaction(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_update_interaction(db, tenant_id, actor_user_id, student_id, interaction_id, payload):
        captured["student_id"] = student_id
        captured["interaction_id"] = interaction_id
        captured["next_action"] = payload.nextAction
        return {
            "interaction": {
                "id": interaction_id,
                "type": "call",
                "outcome": "needs_follow_up",
                "title": "Call",
                "note": "Updated note.",
                "description": "Updated note.",
                "nextAction": payload.nextAction,
                "nextFollowUpAt": "2026-06-22T15:00:00.000Z",
                "occurredAt": "2026-06-19T18:30:00.000Z",
                "actor": "Elian Brooks",
                "source": "student_360",
            }
        }

    monkeypatch.setattr(student_routes.student_service, "update_student_interaction", fake_update_interaction)

    client = TestClient(_build_test_app())
    response = client.patch(
        "/api/v1/students/STU-123/interactions/int-123",
        json={"outcome": "needs_follow_up", "nextAction": "Request updated transcript"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["interaction"]["id"] == "int-123"
    assert payload["interaction"]["outcome"] == "needs_follow_up"
    assert captured == {
        "student_id": "STU-123",
        "interaction_id": "int-123",
        "next_action": "Request updated transcript",
    }


def test_student_counselor_extension_routes(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.student_service,
        "log_student_communication",
        lambda **kwargs: {"communication": {"id": "int-1", "channel": kwargs["payload"]["channel"], "status": "logged"}},
    )
    monkeypatch.setattr(
        student_routes.student_service,
        "create_student_handoff",
        lambda **kwargs: {"handoff": {"id": "handoff-1", "targetTeam": kwargs["payload"]["targetTeam"], "status": "Open"}},
    )
    monkeypatch.setattr(
        student_routes.student_service,
        "get_post_admit_readiness",
        lambda tenant_id, student_id: {"studentId": student_id, "milestones": [{"id": "registration_status", "status": "Not started"}]},
    )
    monkeypatch.setattr(
        student_routes.student_service,
        "update_post_admit_milestone",
        lambda **kwargs: {"milestone": {"id": kwargs["milestone_id"], "status": kwargs["payload"]["status"]}},
    )

    client = TestClient(_build_test_app())

    communication = client.post("/api/v1/students/STU-123/communications/log", json={"channel": "email", "message": "Hello"})
    handoff = client.post("/api/v1/students/STU-123/handoffs", json={"targetTeam": "Financial Aid"})
    readiness = client.get("/api/v1/students/STU-123/post-admit-readiness")
    milestone = client.post("/api/v1/students/STU-123/milestones/registration_status/status", json={"status": "Complete"})

    assert communication.status_code == 200
    assert communication.json()["communication"]["status"] == "logged"
    assert handoff.status_code == 200
    assert handoff.json()["handoff"]["targetTeam"] == "Financial Aid"
    assert readiness.status_code == 200
    assert readiness.json()["milestones"][0]["id"] == "registration_status"
    assert milestone.status_code == 200
    assert milestone.json()["milestone"]["status"] == "Complete"


def test_get_student_timeline_returns_events(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_get_timeline(tenant_id, student_id, authorization=None):
        captured["student_id"] = student_id
        return {
            "events": [
                {
                    "id": "evt-1",
                    "type": "checklist",
                    "title": "Official transcript marked complete",
                    "description": "Updated checklist item.",
                    "occurredAt": "2026-06-04T15:30:00Z",
                    "actor": {"id": "usr-1", "name": "Elian Brooks", "type": "user"},
                    "source": "checklist",
                    "status": "complete",
                    "entity": {"type": "student_checklist_item", "id": "chk-1"},
                    "sensitivityTier": "standard",
                }
            ]
        }

    monkeypatch.setattr(student_routes.student_service, "get_student_timeline", fake_get_timeline)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["type"] == "checklist"
    assert captured["student_id"] == "student-1"


def test_student_identifier_variants_strip_leading_zeros():
    assert Student360Service()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
    assert AdmissionsOpsService()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
    assert OperationsService()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
