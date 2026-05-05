# Agent Checklist Plan

## Goal

Implement an agent-native admissions workflow using AWS Strands Agents on top of the existing transcript, trust, decision, and student services.

## Principles

- [ ] Keep business rules deterministic in Python services.
- [ ] Use Strands Agents for orchestration, tool selection, explanation, and handoff.
- [ ] Keep the database as the system of record.
- [ ] Persist every agent run, action, handoff, and status transition.
- [ ] Prefer event-driven projections over recalculating tenant-wide work state during reads.

## Phase 0: Foundation

- [x] Create a repo plan for the agent rollout.
- [x] Add Strands SDK dependencies and base config.
- [x] Create `app/agents/` scaffold for Strands runtime, agent builders, and tools.
- [x] Add agent persistence schema:
  `agent_runs`, `agent_actions`, `agent_handoffs`, `student_agent_state`
- [x] Add common agent result envelope and status model.
- [x] Add internal API/admin endpoints for invoking and inspecting agent runs.
- [x] Expose structured agent result envelopes on agent-run read APIs.
- [x] Expose structured agent result envelopes on agent-action read APIs.
- [x] Add structured logging and correlation IDs for agent executions.

## Phase 1: Document Agent

- [x] Define `DocumentAgent` responsibilities and input/output schema.
- [x] Wrap transcript extraction as Strands tools.
- [x] Wrap persistence completion and failure handling as Strands tools.
- [x] Wrap checklist linking and student context lookup as Strands tools.
- [x] Add transcript reprocessing tool for failed transcripts.
- [x] Add document exception summaries with explainable agent reasoning.
- [x] Add document-agent run details endpoint for one-call drawer reads.
- [x] Collapse document exception and run-details read paths onto a shared backend aggregator.
- [x] Add tests for successful parse, failed parse, and recovery flows.
- [x] Persist uploaded transcript bytes so stored-file reprocessing is possible.

## Phase 2: Trust Agent

- [x] Define `TrustAgent` responsibilities and input/output schema.
- [x] Wrap identity match, trust flags, and document history as Strands tools.
- [x] Add trust case creation, escalation, and resolution tools.
- [x] Add trust case escalation and resolution tools.
- [x] Add trust case assignment and ownership workflow.
- [x] Add explicit progression blocking/unblocking workflow.
- [x] Add explainable trust summaries for UI consumption.
- [x] Add tests for mismatch, fraud block, and false-positive resolution flows.

## Trust Slice

- [x] Add `TrustAgent` scaffold with normalized run/action result envelopes.
- [x] Instrument manual match confirm/reject and quarantine/release flows with trust-agent runs.
- [x] Expose trust-agent run/action details through transcript-scoped trust case reads.
- [x] Enrich trust queue rows with blocked state and latest trust-agent outcome fields.
- [x] Add explicit trust case resolve/escalate endpoints with normalized result codes.
- [x] Add trust case owner fields and assignment endpoint.
- [x] Add service-level trust lifecycle tests for block, unblock, and assignment flows.
- [x] Add service-level mismatch tests for manual match confirm/reject flows.

## Phase 3: Decision Agent

- [x] Define `DecisionAgent` responsibilities and input/output schema.
- [x] Wrap decision packet assembly as Strands tools.
- [x] Expose readiness, trust status, and supporting evidence tools.
- [x] Return structured recommendations with confidence and rationale.
- [x] Keep finalization human-approved in the first release.
- [x] Add tests for recommendation generation and packet completeness.

## Decision Slice

- [x] Add `DecisionAgent` scaffold with normalized run/action result envelopes.
- [x] Add explicit recommendation endpoint backed by `decision_agent`.
- [x] Expose latest decision-agent run and action details through decision-scoped reads.
- [x] Add reusable decision snapshot read model for agent context and future approval/orchestrator flows.
- [x] Add lightweight review action for accepting or sending back snapshot-backed recommendations.
- [x] Persist review artifacts with snapshot version for accepted or returned recommendations.
- [x] Expose the latest reviewed snapshot artifact on decision-scoped reads.

## Phase 4: Work State Projection

- [x] Stop recalculating work state on every `/work/*` read.
- [x] Add `student_work_state` projection table.
- [x] Emit projection refreshes on transcript completion/failure, checklist change, document match, and trust change.
- [x] Build projector service to update work state asynchronously.
- [x] Refactor `/api/v1/work/summary` and `/api/v1/work/items` to read projections only.
- [x] Re-profile work endpoints after projection cutover.
- [x] Add explicit work-projection status and rebuild endpoints.
- [x] Add chunked work-projection rebuild flow for large tenants.
- [x] Add one-call full work-projection rebuild trigger that loops chunks in the background.
- [x] Persist work-projection rebuild job state for polling and error reporting.
- [x] Add projection job history and retry endpoints for admin/ops visibility.
- [x] Add projection job cancellation and direct returned job IDs for queued rebuild flows.

## Phase 5: Orchestrator Agent

- [x] Define `OrchestratorAgent` responsibilities and input/output schema.
- [x] Expose projected work queue, ownership, and priority tools.
- [x] Add handoff tools to route work to document, trust, and decision agents.
- [x] Add backend next-agent recommendation for Today's Work routing.
- [x] Add daily prioritization and queue grouping logic.
- [x] Add persisted orchestrator run snapshots for Today's Work prioritization.
- [x] Add read endpoint for latest Today's Work orchestrator snapshot.
- [x] Add Today’s Work API surfaces backed by agent-safe projections.
- [x] Add tests for prioritization and routing behavior.

## Phase 6: Lifecycle Agent

- [x] Define `LifecycleAgent` responsibilities and input/output schema.
- [x] Add admit-to-deposit cohort tools.
- [x] Add deposit likelihood and melt risk scoring tools.
- [x] Add intervention and outreach action tools.
- [x] Add tests for lifecycle recommendations and intervention logging.

## Data and Schema Follow-Up

- [x] Dedupe `document_checklist_links`.
- [x] Add a unique index for `(tenant_id, document_id, checklist_item_id)`.
- [x] Add migration for agent-run persistence tables.
- [x] Add migration for projected work-state tables.

## Performance Follow-Up

- [x] Profile `/api/v1/work/items`.
- [x] Confirm the current bottleneck is tenant-wide recalculation and repeated SQL execution.
- [x] Reduce one redundant transcript-confidence lookup in the current path.
- [x] Remove tenant-wide sync from `/api/v1/documents/exceptions`.
- [x] Replace synchronous recomputation with event-driven projections.
- [x] Profile again after projection rollout.
- [x] Add stable warm-up and rebuild controls for projection operations.

## Transcript Reliability Follow-Up

- [x] Fix vertical high school transcript parsing for four-digit year headers.
- [x] Reprocess failed transcript `4d067228-d3b8-4cc4-93ab-1a5436dbfe84`.
- [x] Clear stale failure notes on successful transcript completion.
- [x] Add an admin reprocess endpoint for failed transcripts.
- [x] Add regression coverage for additional sample transcript layouts.

## Current Build Slice

- [x] Plan committed to repo
- [x] Strands config added
- [x] Base `app/agents/` scaffold added
- [x] Agent persistence schema
- [x] First working `DocumentAgent` execution path
