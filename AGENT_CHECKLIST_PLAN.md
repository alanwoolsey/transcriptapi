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
- [ ] Add common agent result envelope and status model.
- [x] Add internal API/admin endpoints for invoking and inspecting agent runs.
- [ ] Add structured logging and correlation IDs for agent executions.

## Phase 1: Document Agent

- [ ] Define `DocumentAgent` responsibilities and input/output schema.
- [ ] Wrap transcript extraction as Strands tools.
- [ ] Wrap persistence completion and failure handling as Strands tools.
- [ ] Wrap checklist linking and student context lookup as Strands tools.
- [x] Add transcript reprocessing tool for failed transcripts.
- [x] Add document exception summaries with explainable agent reasoning.
- [ ] Add tests for successful parse, failed parse, and recovery flows.
- [x] Persist uploaded transcript bytes so stored-file reprocessing is possible.

## Phase 2: Trust Agent

- [ ] Define `TrustAgent` responsibilities and input/output schema.
- [ ] Wrap identity match, trust flags, and document history as Strands tools.
- [ ] Add trust case creation, escalation, and resolution tools.
- [ ] Add explicit progression blocking/unblocking workflow.
- [ ] Add explainable trust summaries for UI consumption.
- [ ] Add tests for mismatch, fraud block, and false-positive resolution flows.

## Phase 3: Decision Agent

- [ ] Define `DecisionAgent` responsibilities and input/output schema.
- [ ] Wrap decision packet assembly as Strands tools.
- [ ] Expose readiness, trust status, and supporting evidence tools.
- [ ] Return structured recommendations with confidence and rationale.
- [ ] Keep finalization human-approved in the first release.
- [ ] Add tests for recommendation generation and packet completeness.

## Phase 4: Work State Projection

- [x] Stop recalculating work state on every `/work/*` read.
- [x] Add `student_work_state` projection table.
- [x] Emit projection refreshes on transcript completion/failure, checklist change, document match, and trust change.
- [x] Build projector service to update work state asynchronously.
- [x] Refactor `/api/v1/work/summary` and `/api/v1/work/items` to read projections only.
- [x] Re-profile work endpoints after projection cutover.
- [x] Add explicit work-projection status and rebuild endpoints.
- [x] Add chunked work-projection rebuild flow for large tenants.

## Phase 5: Orchestrator Agent

- [ ] Define `OrchestratorAgent` responsibilities and input/output schema.
- [ ] Expose projected work queue, ownership, and priority tools.
- [ ] Add handoff tools to route work to document, trust, and decision agents.
- [ ] Add daily prioritization and queue grouping logic.
- [ ] Add Today’s Work API surfaces backed by agent-safe projections.
- [ ] Add tests for prioritization and routing behavior.

## Phase 6: Lifecycle Agent

- [ ] Define `LifecycleAgent` responsibilities and input/output schema.
- [ ] Add admit-to-deposit cohort tools.
- [ ] Add deposit likelihood and melt risk scoring tools.
- [ ] Add intervention and outreach action tools.
- [ ] Add tests for lifecycle recommendations and intervention logging.

## Data and Schema Follow-Up

- [x] Dedupe `document_checklist_links`.
- [x] Add a unique index for `(tenant_id, document_id, checklist_item_id)`.
- [ ] Add migration for agent-run persistence tables.
- [x] Add migration for projected work-state tables.

## Performance Follow-Up

- [x] Profile `/api/v1/work/items`.
- [x] Confirm the current bottleneck is tenant-wide recalculation and repeated SQL execution.
- [x] Reduce one redundant transcript-confidence lookup in the current path.
- [x] Remove tenant-wide sync from `/api/v1/documents/exceptions`.
- [ ] Replace synchronous recomputation with event-driven projections.
- [ ] Profile again after projection rollout.

## Transcript Reliability Follow-Up

- [x] Fix vertical high school transcript parsing for four-digit year headers.
- [x] Reprocess failed transcript `4d067228-d3b8-4cc4-93ab-1a5436dbfe84`.
- [x] Clear stale failure notes on successful transcript completion.
- [x] Add an admin reprocess endpoint for failed transcripts.
- [ ] Add regression coverage for additional sample transcript layouts.

## Current Build Slice

- [x] Plan committed to repo
- [x] Strands config added
- [x] Base `app/agents/` scaffold added
- [x] Agent persistence schema
- [x] First working `DocumentAgent` execution path
