from types import SimpleNamespace
from uuid import uuid4

from app.models.ops_models import WorkItemOwner, WorkItemReason, WorkTodayItemResponse
from app.services.admissions_ops_service import AdmissionsOpsService


def test_recommend_today_agent_prefers_trust_when_exception_signals_are_active():
    service = AdmissionsOpsService()

    recommended_agent, reason = service._recommend_today_agent(
        SimpleNamespace(section="exceptions", suggested_action_code="review_trust"),
        SimpleNamespace(current_owner_agent="document_agent"),
        document_run=None,
        trust_run=SimpleNamespace(output_json={"code": "trust_case_blocked"}),
        decision_run=None,
    )

    assert recommended_agent == "trust_agent"
    assert "Trust-related blockers" in reason


def test_recommend_today_agent_prefers_decision_when_student_is_ready():
    service = AdmissionsOpsService()

    recommended_agent, reason = service._recommend_today_agent(
        SimpleNamespace(section="ready", suggested_action_code="review_recommendation"),
        SimpleNamespace(current_owner_agent="document_agent"),
        document_run=None,
        trust_run=None,
        decision_run=SimpleNamespace(output_json={"code": "decision_recommendation_generated"}),
    )

    assert recommended_agent == "decision_agent"
    assert "ready for decision review" in reason


def test_group_today_work_items_groups_by_recommended_agent_bucket():
    service = AdmissionsOpsService()

    groups = service._group_today_work_items(
        [
            WorkTodayItemResponse(
                id="work-1",
                studentId="student-1",
                studentName="A",
                section="exceptions",
                priority="urgent",
                owner=WorkItemOwner(id=None, name="Owner"),
                reasonToAct=WorkItemReason(code="trust_block", label="Trust block"),
                suggestedAction=WorkItemReason(code="review_trust", label="Review trust"),
                recommendedAgent="trust_agent",
                queueGroup="trust_review",
            ),
            WorkTodayItemResponse(
                id="work-2",
                studentId="student-2",
                studentName="B",
                section="ready",
                priority="urgent",
                owner=WorkItemOwner(id=None, name="Owner"),
                reasonToAct=WorkItemReason(code="ready_for_decision", label="Ready for decision"),
                suggestedAction=WorkItemReason(code="review_recommendation", label="Review recommendation"),
                recommendedAgent="decision_agent",
                queueGroup="decision_review",
            ),
            WorkTodayItemResponse(
                id="work-3",
                studentId="student-3",
                studentName="C",
                section="ready",
                priority="today",
                owner=WorkItemOwner(id=None, name="Owner"),
                reasonToAct=WorkItemReason(code="ready_for_decision", label="Ready for decision"),
                suggestedAction=WorkItemReason(code="review_recommendation", label="Review recommendation"),
                recommendedAgent="decision_agent",
                queueGroup="decision_review",
            ),
        ]
    )

    assert [group.key for group in groups] == ["trust_review", "decision_review"]
    assert groups[0].total == 1
    assert groups[1].total == 2
    assert groups[0].routeHint is not None
    assert groups[0].routeHint.nextAgent == "trust_agent"
    assert groups[1].routeHint is not None
    assert groups[1].routeHint.nextAgent == "decision_agent"


def test_build_agent_run_result_requires_normalized_payload():
    service = AdmissionsOpsService()

    result = service._build_agent_run_result(
        {
            "status": "completed",
            "code": "today_work_prioritized",
            "message": "Today's work prioritized and grouped.",
            "error": None,
            "metrics": {"totalStudents": 3},
            "artifacts": {"groupKeys": ["decision_review"]},
        }
    )

    assert result is not None
    assert result.code == "today_work_prioritized"
    assert result.metrics["totalStudents"] == 3


def test_board_snapshot_from_run_uses_persisted_snapshot_when_present():
    service = AdmissionsOpsService()

    board = service._board_snapshot_from_run(
        SimpleNamespace(
            output_json={
                "artifacts": {
                    "boardSnapshot": {
                        "groups": [
                            {
                                "key": "decision_review",
                                "label": "Decision Review",
                                "total": 1,
                                "routeHint": {
                                    "nextAgent": "decision_agent",
                                    "reason": "These students are ready for recommendation or decision review.",
                                    "actionLabel": "Route to decision review",
                                },
                                "items": [],
                            }
                        ],
                        "total": 1,
                    }
                }
            }
        )
    )

    assert board.total == 1
    assert board.groups[0].key == "decision_review"
    assert board.groups[0].routeHint is not None
    assert board.groups[0].routeHint.nextAgent == "decision_agent"


def test_projected_work_items_query_pushes_filters_into_sql():
    service = AdmissionsOpsService()
    tenant_id = uuid4()
    owner_id = uuid4()

    stmt = service._projected_work_items_query(
        tenant_id,
        section="ready",
        population="transfer",
        owner=str(owner_id),
        priority="urgent",
        aging_bucket=None,
        q="nursing",
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "student_work_state" in compiled
    assert "section = 'ready'" in compiled
    assert "population = 'transfer'" in compiled
    assert "priority = 'urgent'" in compiled
    assert "owner_user_id" in compiled
    assert "student_name" in compiled
    assert "institution_goal" in compiled
    assert "reason_label" in compiled
