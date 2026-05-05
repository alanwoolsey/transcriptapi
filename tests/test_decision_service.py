from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.db.models import AuditEvent, DecisionPacketEvent, DecisionPacketNote
from app.models.decision_models import DecisionEvidence, DecisionTrustSummary
from app.services.decision_service import DecisionService


class _FakeSession:
    def __init__(self):
        self.added: list[object] = []
        self.committed = False
        self.refreshed: list[object] = []

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def refresh(self, value):
        self.refreshed.append(value)


def test_review_recommendation_persists_snapshot_audit_artifact():
    tenant_id = uuid4()
    actor_user_id = uuid4()
    packet_id = uuid4()
    packet = SimpleNamespace(
        id=packet_id,
        status="Draft",
        readiness="Ready for review",
        updated_at=None,
    )
    snapshot = SimpleNamespace(
        model_dump=lambda mode="json": {
            "decisionId": str(packet_id),
            "status": "Draft",
            "readiness": "Ready for review",
            "student": {"id": "student-1", "name": "Avery Carter", "email": None, "externalId": None},
            "program": {"id": None, "name": "Nursing transfer review"},
            "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
            "evidence": {"institution": "Harbor Gate University", "gpa": 3.42, "creditsEarned": 42, "parserConfidence": 0.96, "documentCount": 3},
            "trust": {"status": "Clear", "signals": []},
        }
    )
    session = _FakeSession()
    service = DecisionService(session_factory=lambda: None)
    service._get_or_create_packet = lambda db, tenant_id, actor_user_id, decision_id: packet
    service._build_snapshot_from_packet = lambda db, packet: snapshot

    response = service.review_recommendation(
        db=session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        decision_id=packet_id,
        payload=SimpleNamespace(action="accept_recommendation", note="Recommendation accepted after manual review."),
    )

    assert response.action == "accept_recommendation"
    assert response.status == "Approved"
    assert response.snapshotVersion
    assert packet.status == "Approved"
    assert packet.readiness == "Approved"
    assert session.committed is True
    assert len(session.refreshed) == 1

    note = next(item for item in session.added if isinstance(item, DecisionPacketNote))
    assert note.body == "Recommendation accepted after manual review."

    event = next(item for item in session.added if isinstance(item, DecisionPacketEvent))
    assert event.event_type == "recommendation_reviewed"

    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.action == "recommendation_reviewed"
    assert audit.payload_json["review_action"] == "accept_recommendation"
    assert audit.payload_json["snapshot_version"] == response.snapshotVersion
    assert audit.payload_json["snapshot"]["recommendation"]["fit"] == 92


class _AuditResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ReadSession:
    def __init__(self, audit_event):
        self.audit_event = audit_event

    def execute(self, _statement):
        return _AuditResult(self.audit_event)


class _FakeDecisionAgent:
    def __init__(self):
        self.context = None
        self.payload = None
        self.owner_student_id = None

    def record_recommendation(self, *, context, payload, owner_student_id):
        self.context = context
        self.payload = payload
        self.owner_student_id = owner_student_id
        return SimpleNamespace(payload={"runId": "run-1"})


def test_latest_reviewed_snapshot_reads_persisted_audit_artifact():
    decision_id = uuid4()
    actor_user_id = uuid4()
    audit = SimpleNamespace(
        payload_json={
            "review_action": "accept_recommendation",
            "snapshot_version": "4d0f13d56a1c2b33",
            "snapshot": {
                "decisionId": str(decision_id),
                "status": "Draft",
                "readiness": "Ready for review",
                "student": {"id": "student-1", "name": "Avery Carter", "email": None, "externalId": None},
                "program": {"id": None, "name": "Nursing transfer review"},
                "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
                "evidence": {"institution": "Harbor Gate University", "gpa": 3.42, "creditsEarned": 42, "parserConfidence": 0.96, "documentCount": 3},
                "trust": {"status": "Clear", "signals": []},
            },
        },
        occurred_at=None,
        actor_user_id=actor_user_id,
    )
    session = _ReadSession(audit)
    service = DecisionService(session_factory=lambda: None)

    result = service._latest_reviewed_snapshot(session, tenant_id=uuid4(), decision_id=decision_id)

    assert result is not None
    assert result.action == "accept_recommendation"
    assert result.snapshotVersion == "4d0f13d56a1c2b33"
    assert result.reviewedByUserId == str(actor_user_id)
    assert result.snapshot["recommendation"]["fit"] == 92


def test_build_recommendation_adds_confidence_and_rationale():
    service = DecisionService(session_factory=lambda: None)

    recommendation = service._build_recommendation(
        fit=92,
        credit_estimate=38,
        reason="High-confidence transcript parse from Harbor Gate University with no active risk signals.",
        readiness="Ready for review",
        evidence=DecisionEvidence(
            institution="Harbor Gate University",
            gpa=3.42,
            creditsEarned=42,
            parserConfidence=0.96,
            documentCount=1,
        ),
        trust=DecisionTrustSummary(status="Clear", signals=[]),
    )

    assert recommendation.confidence == 100
    assert recommendation.rationale is not None
    assert recommendation.rationale[0] == "High-confidence transcript parse from Harbor Gate University with no active risk signals."
    assert "Parser confidence is 96%." in recommendation.rationale
    assert "No active trust signals are blocking review." in recommendation.rationale


def test_generate_recommendation_passes_complete_packet_to_agent():
    tenant_id = uuid4()
    actor_user_id = uuid4()
    packet_id = uuid4()
    student_id = uuid4()
    transcript_id = uuid4()
    packet = SimpleNamespace(
        id=packet_id,
        student_id=student_id,
        transcript_id=transcript_id,
        status="Draft",
        readiness="Ready for review",
        reason="High-confidence transcript parse from Harbor Gate University with no active risk signals.",
        fit_score=92,
        credit_estimate=38,
    )
    snapshot = SimpleNamespace(
        evidence=DecisionEvidence(
            institution="Harbor Gate University",
            gpa=3.42,
            creditsEarned=42,
            parserConfidence=0.96,
            documentCount=1,
        ),
        trust=DecisionTrustSummary(status="Clear", signals=[]),
    )
    service = DecisionService(session_factory=lambda: None)
    fake_agent = _FakeDecisionAgent()
    service.decision_agent = fake_agent
    service._get_or_create_packet = lambda db, tenant_id, actor_user_id, decision_id: packet
    service._build_snapshot_from_packet = lambda db, packet: snapshot

    response = service.generate_recommendation(
        db=SimpleNamespace(),
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        decision_id=packet_id,
    )

    assert response.agentRunId == "run-1"
    assert response.recommendation.fit == 92
    assert response.recommendation.creditEstimate == 38
    assert response.recommendation.confidence == 100
    assert response.recommendation.rationale is not None
    assert "Parser confidence is 96%." in response.recommendation.rationale
    assert fake_agent.context is not None
    assert fake_agent.context.correlation_id == f"decision-recommend:{packet_id}"
    assert fake_agent.payload is not None
    assert fake_agent.payload.decision_id == str(packet_id)
    assert fake_agent.payload.student_id == str(student_id)
    assert fake_agent.payload.transcript_id == str(transcript_id)
    assert fake_agent.payload.readiness == "Ready for review"
    assert fake_agent.payload.readiness_reason == packet.reason
    assert fake_agent.payload.trust_status == "Clear"
    assert fake_agent.payload.trust_signal_count == 0
    assert fake_agent.payload.active_trust_signal_count == 0
    assert fake_agent.payload.institution == "Harbor Gate University"
    assert fake_agent.payload.gpa == 3.42
    assert fake_agent.payload.credits_earned == 42
    assert fake_agent.payload.parser_confidence == 0.96
    assert fake_agent.payload.document_count == 1
    assert fake_agent.payload.confidence == 100
    assert fake_agent.payload.rationale == response.recommendation.rationale
    assert fake_agent.owner_student_id == student_id
