from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedTenantContext, require_permission
from app.db import get_db
from app.models.decision_models import DecisionStatusUpdateRequest, DecisionStatusUpdateResponse
from app.models.operations_models import ActionResponse
from app.models.roadmap_models import (
    ChecklistTemplatePayload,
    ConnectorConfigPayload,
    ConnectorMappingsPayload,
    InteractionPayload,
    ItemResponse,
    ItemsResponse,
    RoadmapActionRequest,
    RoadmapActionResponse,
)
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.decision_service import DecisionNotFoundError, DecisionService, DecisionValidationError
from app.services.operations_service import OperationsService
from app.services.roadmap_service import RoadmapNotFoundError, RoadmapService, RoadmapValidationError

router = APIRouter(tags=["roadmap"])
roadmap_service = RoadmapService()
operations_service = OperationsService()
admissions_ops_service = AdmissionsOpsService()
decision_service = DecisionService()


def _handle_errors(fn):
    try:
        return fn()
    except RoadmapNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoadmapValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/checklist/templates", response_model=ItemsResponse)
def list_checklist_templates(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_roles_view")),
) -> ItemsResponse:
    return roadmap_service.list_checklist_templates(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.post("/checklist/templates", response_model=ItemResponse)
def create_checklist_template(
    payload: ChecklistTemplatePayload,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_scopes_manage")),
) -> ItemResponse:
    return ItemResponse(item=roadmap_service.create_checklist_template(auth_context.tenant.id, auth_context.user.id, payload))


@router.patch("/checklist/templates/{template_id}", response_model=ItemResponse)
def update_checklist_template(
    template_id: str,
    payload: ChecklistTemplatePayload,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_scopes_manage")),
) -> ItemResponse:
    return _handle_errors(lambda: ItemResponse(item=roadmap_service.update_checklist_template(auth_context.tenant.id, auth_context.user.id, template_id, payload)))


@router.post("/checklist/templates/{template_id}/publish", response_model=ItemResponse)
def publish_checklist_template(
    template_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_scopes_manage")),
) -> ItemResponse:
    return _handle_errors(lambda: ItemResponse(item=roadmap_service.publish_checklist_template(auth_context.tenant.id, auth_context.user.id, template_id)))


@router.post("/students/{student_id}/checklist/generate", response_model=RoadmapActionResponse)
def generate_student_checklist(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("edit_checklist")),
) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.generate_student_checklist(auth_context.tenant.id, auth_context.user.id, student_id))


@router.post("/students/{student_id}/interactions", response_model=ItemResponse)
def create_student_interaction(
    student_id: str,
    payload: InteractionPayload,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> ItemResponse:
    return _handle_errors(lambda: ItemResponse(item=roadmap_service.create_interaction(auth_context.tenant.id, auth_context.user.id, student_id, payload)))


@router.get("/identity/duplicates", response_model=ItemsResponse)
def list_duplicates(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("merge_duplicates")),
) -> ItemsResponse:
    return roadmap_service.list_duplicates(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.get("/identity/duplicates/{candidate_id}", response_model=ItemResponse)
def get_duplicate(
    candidate_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("merge_duplicates")),
) -> ItemResponse:
    return _handle_errors(lambda: roadmap_service.get_duplicate(auth_context.tenant.id, candidate_id))


@router.post("/identity/duplicates/{candidate_id}/merge", response_model=RoadmapActionResponse)
def merge_duplicate(
    candidate_id: str,
    payload: RoadmapActionRequest = RoadmapActionRequest(),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("merge_duplicates")),
) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_duplicate(auth_context.tenant.id, auth_context.user.id, candidate_id, "merge", payload))


@router.post("/identity/duplicates/{candidate_id}/dismiss", response_model=RoadmapActionResponse)
def dismiss_duplicate(
    candidate_id: str,
    payload: RoadmapActionRequest = RoadmapActionRequest(),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("merge_duplicates")),
) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_duplicate(auth_context.tenant.id, auth_context.user.id, candidate_id, "dismiss", payload))


@router.get("/students/{student_id}/transfer-evidence")
def get_transfer_evidence(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> dict[str, Any]:
    return _handle_errors(lambda: roadmap_service.transfer_evidence(auth_context.tenant.id, student_id))


@router.get("/transfer/articulation-gaps", response_model=ItemsResponse)
def list_articulation_gaps(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_decision_packet")),
) -> ItemsResponse:
    return roadmap_service.list_articulation_gaps(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.post("/transfer/articulation-gaps/{gap_id}/route", response_model=RoadmapActionResponse)
def route_articulation_gap(
    gap_id: str,
    payload: RoadmapActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_decision_packet")),
) -> RoadmapActionResponse:
    return roadmap_service.route_articulation_gap(auth_context.tenant.id, auth_context.user.id, gap_id, payload)


@router.get("/transfer/specialist-queue", response_model=ItemsResponse)
def transfer_specialist_queue(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_decision_packet")),
) -> ItemsResponse:
    return roadmap_service.specialist_queue(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.post("/decisions/{decision_id}/release", response_model=DecisionStatusUpdateResponse)
def release_decision(
    decision_id: UUID,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("release_decision")),
    db: Session = Depends(get_db),
) -> DecisionStatusUpdateResponse:
    return _update_decision_status(db, auth_context, decision_id, "Released")


@router.post("/decisions/{decision_id}/hold", response_model=DecisionStatusUpdateResponse)
def hold_decision(
    decision_id: UUID,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("finalize_decision")),
    db: Session = Depends(get_db),
) -> DecisionStatusUpdateResponse:
    return _update_decision_status(db, auth_context, decision_id, "Needs evidence")


@router.post("/decisions/{decision_id}/reopen", response_model=DecisionStatusUpdateResponse)
def reopen_decision(
    decision_id: UUID,
    auth_context: AuthenticatedTenantContext = Depends(require_permission("finalize_decision")),
    db: Session = Depends(get_db),
) -> DecisionStatusUpdateResponse:
    return _update_decision_status(db, auth_context, decision_id, "Ready for review")


def _update_decision_status(db: Session, auth_context: AuthenticatedTenantContext, decision_id: UUID, status: str) -> DecisionStatusUpdateResponse:
    try:
        return decision_service.update_status(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            decision_id=decision_id,
            payload=DecisionStatusUpdateRequest(status=status),
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DecisionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/students/{student_id}/yield/interventions", response_model=RoadmapActionResponse)
def yield_intervention(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_deposit_status"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_status(auth_context.tenant.id, auth_context.user.id, student_id, "yield_intervention", payload))


@router.post("/students/{student_id}/yield/follow-up", response_model=RoadmapActionResponse)
def yield_follow_up(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_deposit_status"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_status(auth_context.tenant.id, auth_context.user.id, student_id, "yield_follow_up", payload))


@router.post("/students/{student_id}/deposit", response_model=RoadmapActionResponse)
def student_deposit(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("update_deposit_status"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_status(auth_context.tenant.id, auth_context.user.id, student_id, "deposit", payload))


@router.get("/milestones/templates", response_model=ItemsResponse)
def milestone_templates(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_deposit_status"))) -> ItemsResponse:
    return roadmap_service.milestone_templates(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.post("/milestones/templates", response_model=ItemResponse)
def create_milestone_template(payload: dict[str, Any], auth_context: AuthenticatedTenantContext = Depends(require_permission("update_deposit_status"))) -> ItemResponse:
    return ItemResponse(item=roadmap_service.create_milestone_template(auth_context.tenant.id, auth_context.user.id, payload))


@router.post("/students/{student_id}/milestones/{milestone_id}/status", response_model=RoadmapActionResponse)
def update_milestone_status(student_id: str, milestone_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("update_deposit_status"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_milestone(auth_context.tenant.id, auth_context.user.id, student_id, milestone_id, payload))


@router.post("/students/{student_id}/melt/interventions", response_model=RoadmapActionResponse)
def melt_intervention(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_melt_risk"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_status(auth_context.tenant.id, auth_context.user.id, student_id, "melt_intervention", payload))


@router.get("/handoff", response_model=ItemsResponse)
def handoff(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> ItemsResponse:
    return roadmap_service.list_queue_from_students(auth_context.tenant.id, "handoff", q=q, limit=limit, offset=offset)


@router.get("/students/{student_id}/handoff")
def student_handoff(student_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> dict[str, Any]:
    return _handle_errors(lambda: roadmap_service.student_handoff(auth_context.tenant.id, student_id))


@router.post("/students/{student_id}/handoff/status", response_model=RoadmapActionResponse)
def update_handoff_status(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.update_student_status(auth_context.tenant.id, auth_context.user.id, student_id, "handoff", payload))


@router.get("/handoffs")
def list_handoffs(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
) -> dict[str, Any]:
    return roadmap_service.list_handoffs(auth_context.tenant.id, limit=limit, offset=offset)


@router.post("/handoffs/{handoff_id}/status")
def update_global_handoff_status(
    handoff_id: str,
    payload: dict[str, Any],
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return roadmap_service.update_handoff_status(db, auth_context.tenant.id, auth_context.user.id, handoff_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sync-errors", response_model=ItemsResponse)
def sync_errors(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemsResponse:
    return roadmap_service.sync_errors(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.post("/sync-errors/{error_id}/retry", response_model=RoadmapActionResponse)
def retry_sync_error(error_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> RoadmapActionResponse:
    return roadmap_service.sync_error_action(auth_context.tenant.id, auth_context.user.id, error_id, "retry")


@router.post("/sync-errors/{error_id}/acknowledge", response_model=RoadmapActionResponse)
def acknowledge_sync_error(error_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> RoadmapActionResponse:
    return roadmap_service.sync_error_action(auth_context.tenant.id, auth_context.user.id, error_id, "acknowledged")


@router.get("/connectors", response_model=ItemsResponse)
def connectors(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemsResponse:
    return roadmap_service.connectors(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.get("/connectors/{connector_id}", response_model=ItemResponse)
def connector(connector_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemResponse:
    return _handle_errors(lambda: roadmap_service.connector(auth_context.tenant.id, connector_id))


@router.post("/connectors/{connector_id}/connect", response_model=RoadmapActionResponse)
def connect_connector(connector_id: str, payload: ConnectorConfigPayload, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> RoadmapActionResponse:
    return roadmap_service.connect_connector(auth_context.tenant.id, auth_context.user.id, connector_id, payload)


@router.post("/connectors/{connector_id}/test", response_model=RoadmapActionResponse)
def test_connector(connector_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> RoadmapActionResponse:
    return roadmap_service.test_connector(auth_context.tenant.id, auth_context.user.id, connector_id)


@router.get("/connectors/{connector_id}/mappings", response_model=ItemResponse)
def connector_mappings(connector_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemResponse:
    return roadmap_service.connector_mappings(auth_context.tenant.id, connector_id)


@router.patch("/connectors/{connector_id}/mappings", response_model=ItemResponse)
def save_connector_mappings(connector_id: str, payload: ConnectorMappingsPayload, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemResponse:
    return roadmap_service.save_connector_mappings(auth_context.tenant.id, auth_context.user.id, connector_id, payload)


@router.get("/communication/templates")
def communication_templates(auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> dict[str, Any]:
    return roadmap_service.communication_templates(auth_context.tenant.id)


@router.get("/sync/runs", response_model=ItemsResponse)
def sync_runs(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> ItemsResponse:
    return roadmap_service.sync_errors(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.get("/implementation/readiness")
def implementation_readiness(auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> dict[str, Any]:
    return roadmap_service.implementation_readiness(auth_context.tenant.id)


@router.post("/implementation/checklist/{item_id}/status", response_model=RoadmapActionResponse)
def implementation_checklist_status(item_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("manage_integrations"))) -> RoadmapActionResponse:
    return roadmap_service.implementation_checklist_status(auth_context.tenant.id, auth_context.user.id, item_id, payload)


@router.get("/reporting/operational")
def reporting_operational(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.reporting(auth_context.tenant.id, "operational", q=q, limit=limit, offset=offset)


@router.get("/reporting/outcomes")
def reporting_outcomes(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.reporting(auth_context.tenant.id, "outcomes", q=q, limit=limit, offset=offset)


@router.get("/reporting/benchmarks")
def reporting_benchmarks(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.reporting(auth_context.tenant.id, "benchmarks", q=q, limit=limit, offset=offset)


@router.get("/reporting/drilldown")
def reporting_drilldown(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.reporting(auth_context.tenant.id, "drilldown", q=q, limit=limit, offset=offset)


@router.get("/reporting/funnel")
def reporting_funnel(
    dateRange: str | None = Query(default=None),
    counselor: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    program: str | None = Query(default=None),
    population: str | None = Query(default=None),
    source: str | None = Query(default=None),
    territory: str | None = Query(default=None),
    pipelineStage: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards")),
) -> dict[str, Any]:
    return roadmap_service.counselor_reporting(
        auth_context.tenant.id,
        "funnel",
        {
            "dateRange": dateRange,
            "counselor": counselor,
            "owner": owner,
            "program": program,
            "population": population,
            "source": source,
            "territory": territory,
            "pipelineStage": pipelineStage,
        },
    )


@router.get("/reporting/stage-aging")
def reporting_stage_aging(auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.counselor_reporting(auth_context.tenant.id, "stage-aging", {})


@router.get("/reporting/counselor-workload")
def reporting_counselor_workload(auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.counselor_reporting(auth_context.tenant.id, "counselor-workload", {})


@router.get("/reporting/handoffs")
def reporting_handoffs(auth_context: AuthenticatedTenantContext = Depends(require_permission("view_dashboards"))) -> dict[str, Any]:
    return roadmap_service.counselor_reporting(auth_context.tenant.id, "handoffs", {})


@router.get("/recruitment/events")
def recruitment_events(auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> dict[str, Any]:
    return roadmap_service.recruitment_events(auth_context.tenant.id)


@router.post("/recruitment/events/{event_id}/attendees")
def add_recruitment_attendee(event_id: str, payload: dict[str, Any], auth_context: AuthenticatedTenantContext = Depends(require_permission("view_student_360"))) -> dict[str, Any]:
    return _handle_errors(lambda: roadmap_service.add_recruitment_attendee(auth_context.tenant.id, auth_context.user.id, event_id, payload))


@router.get("/graduate/program-queues", response_model=ItemsResponse)
def graduate_program_queues(q: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), auth_context: AuthenticatedTenantContext = Depends(require_permission("view_decision_packet"))) -> ItemsResponse:
    return roadmap_service.graduate_program_queues(auth_context.tenant.id, q=q, limit=limit, offset=offset)


@router.get("/graduate/applicants/{student_id}/packet")
def graduate_packet(student_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("view_decision_packet"))) -> dict[str, Any]:
    return _handle_errors(lambda: roadmap_service.graduate_packet(auth_context.tenant.id, student_id))


@router.post("/graduate/applicants/{student_id}/rubric", response_model=RoadmapActionResponse)
def graduate_rubric(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("recommend_decision"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.graduate_action(auth_context.tenant.id, auth_context.user.id, student_id, "rubric", payload))


@router.post("/graduate/applicants/{student_id}/committee-recommendation", response_model=RoadmapActionResponse)
def graduate_committee_recommendation(student_id: str, payload: RoadmapActionRequest, auth_context: AuthenticatedTenantContext = Depends(require_permission("recommend_decision"))) -> RoadmapActionResponse:
    return _handle_errors(lambda: roadmap_service.graduate_action(auth_context.tenant.id, auth_context.user.id, student_id, "committee_recommendation", payload))


@router.get("/graduate/departments/{department_id}/permissions")
def graduate_department_permissions(department_id: str, auth_context: AuthenticatedTenantContext = Depends(require_permission("admin_scopes_manage"))) -> dict[str, Any]:
    return roadmap_service.graduate_department_permissions(auth_context.tenant.id, department_id)
