from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.prospect_service import ProspectService


def test_build_work_item_maps_prospect_to_phase2_bucket():
    service = ProspectService()
    prospect_id = uuid4()
    prospect = SimpleNamespace(
        id=prospect_id,
        first_name="Mira",
        last_name="Holloway",
        population="transfer",
        lifecycle_stage="inquiry",
        status="fit_ready",
        question=None,
        program_interest="BS Nursing Transfer",
        prior_institution="River County College",
        updated_at=datetime.now(timezone.utc),
    )
    action = SimpleNamespace(code="start_application", label="Start application")
    fit = SimpleNamespace(fit_score=88)
    owner = SimpleNamespace(id=uuid4(), display_name="Elian Brooks")

    item = service._build_work_item(prospect, action, fit, owner)

    assert item.studentId == f"pro_{prospect_id}"
    assert item.reasonToAct.code == "high_fit_prospect"
    assert item.queueGroup == "started_not_submitted"
    assert item.suggestedAction.code == "start_application"


def test_build_work_item_maps_duplicate_candidate_bucket():
    service = ProspectService()
    prospect = SimpleNamespace(
        id=uuid4(),
        first_name="Duplicate",
        last_name="Lead",
        population="transfer",
        lifecycle_stage="duplicate_candidate",
        status="duplicate_candidate",
        question=None,
        program_interest=None,
        prior_institution=None,
        updated_at=datetime.now(timezone.utc),
    )
    action = SimpleNamespace(code="resolve_duplicate", label="Resolve duplicate")

    item = service._build_work_item(prospect, action, None, None)

    assert item.reasonToAct.code == "duplicate_candidate"
    assert item.queueGroup == "duplicate_candidate"
