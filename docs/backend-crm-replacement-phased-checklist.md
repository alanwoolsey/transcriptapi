# Backend CRM Replacement Phased Checklist

Last checked: 2026-06-21

This checklist translates the CRM replacement roadmap into backend deliverables and marks what the current `transcriptapi` backend already has. Status is conservative: `[x]` means implemented in code and covered by existing tests or clearly wired routes; `[~]` means partially implemented, placeholder-backed, or frontend-compatible but not yet complete; `[ ]` means not implemented or not verified.

## Evidence Reviewed

- Routes: `app/api/*_routes.py`
- Models: `app/db/models.py`, `app/models/*.py`
- Services: `app/services/*_service.py`
- Migrations: `alembic/versions/*`
- Tests: `tests/test_*`

## Backend Principles

- [~] Every endpoint is tenant-scoped. Most protected routes use `AuthenticatedTenantContext`; public transcript/prospect-style routes still need a full audit.
- [~] Every protected endpoint enforces auth. Auth dependency exists and is broadly used.
- [~] Every endpoint rejects cross-tenant entity access. Core services query by `tenant_id`; needs systematic endpoint-by-endpoint verification.
- [~] Every write action creates an audit event. Many writes audit, but coverage is incomplete.
- [~] Every operational action can appear in Student 360 timeline. Student timeline includes documents, checklist, trust, decisions, interactions, handoffs/tasks, milestones, and audit events; not all new operational actions are normalized into a dedicated timeline read model.
- [~] Every blocker can appear in Today's Work. Checklist, trust, decision readiness, projected work, follow-ups, and handoff-like items are partially surfaced.
- [~] Every stage, owner, checklist, document, trust, communication, handoff, review, and milestone change is reportable. Reporting exists but is not complete enough for every event type.
- [x] Backend returns `401` for expired/invalid token. `app/api/dependencies.py` maps token verifier failures to 401.
- [~] Backend returns consistent JSON errors using `detail` or `message`. FastAPI `detail` is standard; some service payloads still return varied shapes.

## Phase 0: Company, IP, And Partner Foundation

### Tenant / Partner Metadata

- [~] Tenant table exists.
- [ ] Tenant legal owner fields.
- [ ] Reseller/channel attribution fields.
- [ ] Partner mode flag.
- [ ] External partner account IDs.
- [ ] White-label configuration ownership metadata.
- [ ] Data processing agreement / contract metadata fields.

### Audit / Compliance Foundation

- [x] Durable `audit_events` table exists.
- [~] Actor, tenant, entity type, entity ID, action, timestamp, correlation ID exist.
- [ ] Before/after structured audit fields.
- [~] Request/correlation ID support exists on audit rows but is not systematically propagated.
- [ ] API request log for partner endpoints.
- [ ] Audit export endpoint.
- [ ] `GET /api/v1/audit/events`
- [ ] `GET /api/v1/audit/events/export`

## Phase 1: Core Admissions CRM Replacement

### 1. Admissions Pipeline

Canonical stage support:

- [x] Inquiry.
- [x] Prospect.
- [x] Applicant.
- [x] Incomplete.
- [x] Complete.
- [ ] Ready for Review as canonical pipeline stage.
- [ ] Decisioned.
- [x] Admitted.
- [x] Deposited/Committed.
- [x] Registered.
- [ ] Denied.
- [ ] Waitlisted.
- [ ] Deferred.
- [ ] Withdrawn.
- [ ] Cancelled.
- [ ] Inactive.
- [ ] Admitted with condition.

Backend tasks:

- [~] Canonical stage mapping exists in `app/services/pipeline_status.py`.
- [ ] Lifecycle stage enum/config table.
- [ ] Stage transition validation.
- [ ] Stage history table.
- [~] Stage transition audit events. Generic audit exists, no dedicated stage history flow.
- [~] Student list filters include stage and related fields.
- [~] Funnel reporting exists in dashboard/roadmap placeholder form.
- [~] Today's Work bucket generation uses projected state plus counselor buckets.
- [ ] `POST /api/v1/students/{studentId}/stage`
- [ ] `GET /api/v1/students/{studentId}/stage-history`

### 2. Student 360 Backend Contract

`GET /api/v1/students/{studentId}` currently includes:

- [x] Profile fields.
- [~] Application fields. Prospect/application-adjacent fields exist; no durable application model.
- [x] Program/degree.
- [x] Owner.
- [x] Source.
- [x] Population.
- [x] Checklist.
- [x] Documents/transcripts.
- [x] Interactions.
- [~] Communications. Communication logs are stored as interaction records; no separate communication model/table.
- [x] Handoffs. Backed by `StudentTask` metadata.
- [x] Post-admit milestones. Backed by `StudentEnrollmentMilestone`.
- [x] Recruitment source fields. Stored in counselor state metadata.
- [~] Review state. Decision/readiness surfaces exist, no full review model.
- [x] Decision state.
- [x] Trust/fraud summary.
- [ ] Audit availability flag.
- [x] `lastContactedAt`
- [x] `nextFollowUpAt`
- [x] `nextAction`
- [x] `contactOutcome`
- [x] `interactions`
- [~] `communications`
- [x] `handoffs`
- [x] `postAdmitMilestones`
- [x] `territory`
- [x] `sourceSchool`
- [x] `partnerSchool`
- [x] `trustSummary`
- [~] `reviewSummary`
- [x] `decisionSummary`

Suggested endpoints:

- [x] `GET /api/v1/students`
- [ ] `POST /api/v1/students`
- [x] `GET /api/v1/students/{studentId}`
- [x] `PATCH /api/v1/students/{studentId}`

### 3. Today's Work Backend

Queues:

- [~] New inquiries.
- [x] Overdue follow-ups.
- [x] Incomplete applications.
- [~] Missing transcript.
- [~] Missing requirement.
- [~] Documents needing review.
- [x] Trust exceptions.
- [x] Ready for review.
- [~] Decision pending.
- [~] Admitted no deposit.
- [~] Deposited not registered.
- [x] Open handoffs.

Endpoints and work item shape:

- [x] `GET /api/v1/work/counselor/today`
- [ ] `GET /api/v1/work/counselor/today/board`
- [x] Work item includes `id`, `studentId`, `studentName`, `pipelineStatus`, `program`, `owner`, `lastContactedAt`, `nextFollowUpAt`, `nextAction`, `priority`, `reasonToAct`, `blockingItems`, `routeHint`.
- [~] Work item includes `blocker` and `dueAt`. Available indirectly in blockers/follow-up but not normalized on every item.
- [~] Generate work items from student stage, checklist, interactions, handoffs, trust, review, and milestones. Projection supports several inputs; interactions/handoffs/milestones are partially folded into counselor buckets.
- [~] Include SLA aging.
- [ ] Include deep link target metadata where possible.
- [~] Refresh projection after relevant writes.
- [x] Work projection rebuild job exists.

### 4. Interactions And Activities

Models and endpoints:

- [x] `student_interactions`.
- [~] `interaction_notes`. Notes are embedded in `student_interactions` and legacy `student_notes`; no separate interaction-notes table.
- [~] `student_timeline_events` view/read model. Timeline is built dynamically.
- [x] `GET /api/v1/students/{studentId}/interactions`
- [x] `POST /api/v1/students/{studentId}/interactions`
- [x] `PATCH /api/v1/students/{studentId}/interactions/{interactionId}`
- [x] `GET /api/v1/students/{studentId}/timeline`

Interaction fields:

- [x] Type.
- [ ] Direction.
- [x] Outcome.
- [x] Title.
- [x] Note/description.
- [x] Next action.
- [x] Next follow-up.
- [x] Actor.
- [x] Occurred at.
- [~] Source. Stored as string; source enum not enforced.

Audit:

- [x] Interaction created.
- [x] Interaction edited.
- [~] Note created. Legacy notes audit exists in some flows; no dedicated interaction-note audit for all notes.
- [x] Next follow-up changed.

### 5. Ownership And Next Action

- [x] `POST /api/v1/students/{studentId}/next-action`
- [x] Persist owner ID.
- [x] Persist next action.
- [x] Persist next follow-up date.
- [x] Persist last contacted date.
- [x] Persist contact outcome.
- [~] Persist blocker. Handoffs/tasks include blocker metadata, next-action does not normalize blocker field.
- [~] Persist priority. Priority exists in work state, not next-action history.
- [~] Ownership assignment. Stored on `Student.advisor_user_id` and projection, no dedicated assignment table.
- [ ] Ownership history.
- [~] Next action history. Audits and task/interactions exist, no dedicated next-action history table.
- [~] Owner changed audit. Some assignment updates audit through next-action metadata, not dedicated.
- [x] Next action changed audit.
- [x] Follow-up changed audit.

## Phase 2: Applicant Portal Replacement

### 1. Prospect Portal

- [x] Prospect model.
- [~] Inquiry model. Prospect inquiry is represented by `Prospect`.
- [ ] Contact preference.
- [x] Consent.
- [x] Source attribution.
- [~] `POST /api/v1/portal/inquiries`. Existing route is `POST /api/v1/prospects/inquiries`.
- [ ] `GET /api/v1/portal/inquiries/{inquiryId}`
- [~] `POST /api/v1/portal/inquiries/{inquiryId}/convert`. Existing route is `POST /api/v1/prospects/{prospectId}/convert-application`.
- [x] Persist inquiry form.
- [~] Deduplicate against existing students.
- [x] Create or update Student 360.
- [x] Preserve source attribution.
- [x] Create timeline event.
- [x] Add new inquiry to Today's Work.

### 2. Application Portal

- [ ] Application.
- [ ] Application answer.
- [~] Application requirement. Checklist templates/items exist, not full application requirements.
- [ ] Application status history.
- [~] Applicant profile. Student/prospect profile exists.
- [ ] Application draft/save state.
- [ ] `POST /api/v1/portal/applications`
- [ ] `GET /api/v1/portal/applications/{applicationId}`
- [ ] `PATCH /api/v1/portal/applications/{applicationId}`
- [ ] `POST /api/v1/portal/applications/{applicationId}/submit`
- [ ] `POST /api/v1/portal/applications/{applicationId}/documents`
- [ ] Configurable application form.
- [ ] Save and resume.
- [ ] Submit application.
- [~] Checklist status.
- [~] Missing item visibility.
- [x] Document upload exists for transcript routes.
- [ ] Parent/family placeholder fields.
- [ ] Payment placeholder fields.

### 3. Portal Admin / White Label

- [ ] Portal branding.
- [ ] Portal content.
- [ ] Custom fields.
- [~] Program list.
- [~] Requirement templates/checklist rules.
- [ ] Application deadlines.
- [ ] Status messages.
- [ ] Confirmation pages.
- [ ] Partner mode.
- [ ] `GET /api/v1/admin/portal/config`
- [ ] `PATCH /api/v1/admin/portal/config`
- [ ] `GET /api/v1/portal/config`

### 4. Partner API Layer

- [ ] Partner auth.
- [ ] Partner rate limits.
- [ ] Partner audit logs.
- [ ] Partner usage tracking.
- [ ] External application ID mapping.
- [ ] Webhook delivery and retry.
- [ ] Partner application/document/readiness/trust/transcript/portal-link/webhook endpoints.

## Phase 3: Transcript Extraction And Document Intelligence

### 1. Extraction Provider Abstraction

- [~] Extraction provider config. Local/Textract/Bedrock config exists, not tenant provider registry.
- [x] Extraction run via `transcript_parse_runs`.
- [x] Normalized document result returned by pipeline/mapper.
- [x] Extracted transcript.
- [x] Extracted course row.
- [x] Extraction warning/error.
- [~] Evidence/page reference. Bounding boxes/page references are partially supported.
- [x] Existing Python extraction engine is the extraction path.
- [x] Freedom C# engine is not in scope.
- [ ] Future partner engines, only if needed later.
- [~] `POST /api/v1/documents/{documentId}/extract`. Existing reprocess routes cover similar flow.
- [ ] `GET /api/v1/documents/{documentId}/extraction-runs`
- [~] `GET /api/v1/documents/{documentId}/normalized-result`. Run-details/exception-summary are available, not exact endpoint.
- [x] `POST /api/v1/documents/{documentId}/reprocess-upload`

### 2. Document Queue

- [x] Uploaded.
- [x] Processing.
- [x] Processed/completed.
- [x] Needs review.
- [x] Matched.
- [x] Unmatched.
- [x] Exception.
- [~] Rejected.
- [~] Duplicate.
- [x] Trust flagged.
- [x] `GET /api/v1/documents/queue`
- [x] `GET /api/v1/documents/exceptions`
- [~] `POST /api/v1/documents/{documentId}/status`. Confirm/reject/quarantine/release routes exist, not generic status endpoint.
- [ ] `POST /api/v1/documents/{documentId}/replace`
- [ ] `POST /api/v1/documents/{documentId}/approve-extraction`

### 3. Transcript Viewer Data

- [x] `GET /api/v1/documents/{documentId}/content`
- [ ] `GET /api/v1/documents/{documentId}/transcript-view`
- [x] Original document content streaming endpoint.
- [x] Extracted fields.
- [x] Extracted courses.
- [x] Confidence.
- [~] Evidence references.
- [ ] Correction state.
- [x] Extraction run metadata.

### 4. Checklist Automation

- [x] Mark transcript received.
- [~] Determine official/unofficial status.
- [x] Determine college/high school transcript.
- [x] Update GPA when present.
- [~] Update test scores when present.
- [ ] Update course prerequisites when configured.
- [x] Resolve missing transcript checklist item.
- [x] Write timeline event.
- [~] Recompute Today's Work.

## Phase 4: Trust And Fraud Center

### Transcript Fraud API Integration

- [ ] Fraud API base URL/auth config.
- [ ] Tenant-level fraud policy config.
- [ ] Timeout/retry config.
- [ ] Fraud check feature flag.
- [ ] Fraud API request contract finalized.
- [ ] Trigger fraud API call after upload/extraction.
- [ ] Store fraud request metadata/raw response/provider run/schema version.
- [ ] Retry transient failures.
- [ ] Fraud unavailable hard-failure state.
- [ ] `POST /api/v1/documents/{documentId}/fraud-check`
- [ ] `GET /api/v1/documents/{documentId}/fraud-checks`

### Normalized Trust Result / Workflow

- [~] Trust result. `TrustFlag` and trust summaries exist, not full normalized schema.
- [ ] Fraud check run/raw response models.
- [~] Trust signal. Trust flags carry reason/severity/evidence-like metadata.
- [~] Trust case. Trust routes and flags exist, no dedicated rich case model.
- [x] If clear/requires review/blocked, trust state can be represented.
- [x] Trust exception appears in Today's Work.
- [x] Trust summary appears in Student 360.
- [x] Trust status included in decision/readiness contexts.
- [~] Trust reporting.
- [x] Trust case workflow endpoints exist for cases, assign, quarantine, replacement, resolve, block/clear decision.
- [~] Safe wording/sensitivity. RBAC sensitivity tiers exist and Student 360 redacts trust detail for unauthorized users.
- [~] Trust audit events exist in trust workflows, not full fraud API audit sequence.
- [ ] Document fraud expansion beyond transcripts.

## Phase 5: Review, Reader, And Decision Studio

### Ready For Review

- [~] Review queue item. `/api/v1/review-ready` exists in operations routes, but not full model.
- [~] Review assignment. Decision assignment exists.
- [ ] Review due date/SLA.
- [~] Review status.
- [x] Required checklist complete input.
- [x] Documents processed input.
- [x] Trust clear/reviewed input.
- [~] Application submitted input.
- [~] Program requirements met input.

### Reader Packet

- [x] Decision packet.
- [x] Review note.
- [~] Review rubric.
- [~] Review score.
- [x] Reviewer recommendation.
- [x] `GET /api/v1/decisions/{decisionId}/snapshot`
- [~] `GET /api/v1/decisions/{decisionId}/packet`. Decision detail/snapshot exist; exact packet endpoint not present.
- [x] `POST /api/v1/decisions/{decisionId}/review`
- [x] `POST /api/v1/decisions/{decisionId}/recommendation`
- [x] Packet includes profile, documents, transcript summary, extracted courses, trust status, checklist readiness, notes, recommendation.
- [~] Application answers/scoring/rubric.

### Decision Studio

- [x] `GET /api/v1/decisions`
- [~] `POST /api/v1/decisions/{decisionId}/release`. Status route can set status; exact release endpoint missing.
- [~] `POST /api/v1/decisions/{decisionId}/hold`. Status route can set status; exact hold endpoint missing.
- [ ] `POST /api/v1/decisions/{decisionId}/letter`
- [x] Decision recommendation.
- [x] Decision blockers.
- [x] Final decision/status update.
- [~] Decision release permission check.
- [ ] Decision letter/template placeholder.
- [x] Decision audit.
- [ ] Batch release.

## Phase 6: Communications Control Plane

- [ ] Communication provider model.
- [ ] Tenant communication provider config.
- [~] Communication template. Default/settings-backed templates exist, no table.
- [~] Communication log. Stored as `student_interactions` of type `communication`.
- [ ] Provider delivery event.
- [ ] Consent/opt-out record.
- [x] Log-only provider behavior.
- [ ] SMTP/email provider.
- [ ] SMS provider.
- [ ] HubSpot provider.
- [ ] Computer Instruments provider.
- [ ] Jenzabar/SIS communication provider.
- [x] `GET /api/v1/communication/templates`
- [x] `POST /api/v1/students/{studentId}/communications/log`
- [ ] `POST /api/v1/students/{studentId}/communications/send`
- [ ] `POST /api/v1/communication/provider-callbacks/{provider}`
- [~] Communication log fields. Channel/template/subject/message/status/provider metadata are returned by log response, but persistence is through interaction fields plus payload metadata.
- [ ] HubSpot integration path.

## Phase 7: Governed AI Built Into Workflow

- [ ] AI prompt template model.
- [x] AI/agent run model exists (`agent_runs`, `agent_actions`).
- [ ] AI source citation/reference model.
- [ ] AI policy decision model.
- [ ] AI approval state.
- [~] AI audit event. Agent runs/actions exist; explicit governance audit is missing.
- [ ] AI student summary endpoint.
- [ ] AI next-best-action endpoint.
- [ ] AI draft-communication endpoint.
- [ ] AI trust-case explanation endpoint.
- [ ] AI run approve/reject endpoints.
- [~] Tenant scope/RBAC/sensitivity enforced for existing protected agent-backed flows.
- [ ] Store source data/prompt/template/policy decision/approval state for governed external-facing AI.

## Phase 8: Yield, Deposit, Melt, And Enrollment Readiness

### Yield / Melt Boards

- [x] `GET /api/v1/yield`
- [~] `POST /api/v1/students/{studentId}/deposit-status`. Deposit route exists as `/api/v1/students/{studentId}/deposit`.
- [x] `GET /api/v1/melt`
- [~] Yield/melt backend tasks are partially represented by queues, yield/melt scores, milestones, and handoffs.

### Post-Admit Milestones

- [x] `GET /api/v1/students/{studentId}/post-admit-readiness`
- [x] `POST /api/v1/students/{studentId}/milestones/{milestoneId}/status`
- [x] Financial aid package.
- [x] Scholarship.
- [x] Deposit.
- [x] Housing.
- [x] Orientation.
- [x] Advising.
- [x] Registration.
- [x] Bursar/account.
- [x] International docs.
- [x] Veteran benefits.
- [x] Accessibility.
- [~] Integration placeholders for SIS/financial aid/housing/orientation/bursar exist as placeholder metadata.

### Cross-Office Handoffs

- [x] `GET /api/v1/handoffs`
- [x] `POST /api/v1/students/{studentId}/handoffs`
- [x] `POST /api/v1/handoffs/{handoffId}/status`
- [x] Target teams can be stored as free text.
- [~] Handoff targets are not normalized into a target-team table.

## Phase 9: Reporting, ROI, And Executive Control

### Core Reporting Endpoints

- [x] `GET /api/v1/reporting/overview`
- [x] `GET /api/v1/reporting/funnel`
- [x] `GET /api/v1/reporting/stage-aging`
- [x] `GET /api/v1/reporting/counselor-workload`
- [ ] `GET /api/v1/reporting/reviewer-workload`
- [ ] `GET /api/v1/reporting/documents`
- [ ] `GET /api/v1/reporting/extraction`
- [ ] `GET /api/v1/reporting/trust`
- [x] `GET /api/v1/reporting/handoffs`
- [ ] `GET /api/v1/reporting/source-performance`
- [ ] `GET /api/v1/reporting/roi`
- [~] Funnel, workload, and handoff metrics are placeholder/partial aggregations.
- [ ] ROI dashboard.
- [ ] CSV export.
- [ ] PDF snapshot.
- [ ] Scheduled email.
- [ ] API reporting export endpoint.

## Phase 10: Advanced Replacement Features

### Event Management

- [~] Event storage. Recruitment events are settings-backed, not a dedicated table.
- [~] Event attendee storage. Settings-backed.
- [ ] Event attendance endpoint.
- [ ] Event follow-up task generation.
- [~] Event source attribution.
- [x] `GET /api/v1/recruitment/events`
- [ ] `POST /api/v1/recruitment/events`
- [x] `POST /api/v1/recruitment/events/{eventId}/attendees`
- [ ] `POST /api/v1/recruitment/events/{eventId}/attendance`

### Territory Management

- [~] Territory stored as student metadata.
- [ ] Territory table.
- [ ] High school table.
- [ ] Partner school table.
- [ ] Transfer partner table.
- [ ] Recruiter assignment table.
- [ ] Territory endpoints.

### Duplicate Management

- [x] Duplicate candidate.
- [x] Merge decision/action.
- [ ] Source priority.
- [~] Merge audit trail.
- [~] `GET /api/v1/students/duplicates`. Existing route is under roadmap duplicates.
- [~] Merge/dismiss duplicate endpoints exist under roadmap routes.

### Data Import/Export

- [ ] CSV import.
- [ ] API import.
- [ ] SIS import.
- [ ] HubSpot import.
- [ ] Slate/Salesforce migration import.
- [ ] Export to SIS.
- [ ] Webhooks.
- [ ] Import/export/webhook endpoints.

### Admin Configuration

- [x] Roles.
- [x] Permissions.
- [~] Stages.
- [x] Checklist templates.
- [x] Programs.
- [~] Decision rules.
- [ ] Review rubrics.
- [ ] Portal branding.
- [~] Communication templates.
- [~] Fraud rules.
- [~] Integrations/connectors.

## Phase 11: Computer Instruments Integration

- [ ] Provider credentials.
- [ ] Tenant enablement.
- [ ] Consent rules.
- [ ] Quiet hours.
- [ ] Callback endpoint.
- [ ] Provider event signature verification.
- [ ] Computer Instruments send/callback/status endpoints.
- [ ] SMS send.
- [ ] Voice/call workflow.
- [ ] Reminders.
- [ ] Call outcomes.
- [ ] Bidirectional response status.
- [ ] Failed delivery.
- [ ] Opt-out/consent.
- [ ] Campaign enrollment from Today's Work.
- [ ] Student response updates.
- [ ] Timeline updates.
- [ ] Reporting attribution.

## Immediate Backend Fast-Track Priorities

1. [~] Add missing pipeline statuses and stage history. Status mapping exists; stage history is missing.
2. [x] Harden `GET /api/v1/students/{studentId}` to return core Student 360 arrays.
3. [x] Persist interactions, communications, handoffs, milestones, and next actions.
4. [x] Finish `GET /api/v1/work/counselor/today` for current frontend fallback removal.
5. [ ] Integrate transcript fraud API after upload/extraction.
6. [ ] Normalize fraud API JSON into trust result schema.
7. [~] Auto-create trust cases and decision blockers from fraud results. Trust flags/cases exist, but external fraud API pipeline is missing.
8. [~] Add backend timeline read model. Dynamic timeline exists; dedicated read model is missing.
9. [~] Add review assignment, rubric, and decision release models.
10. [~] Add reporting aggregations and CSV export. Partial aggregations exist; export missing.
11. [ ] Add applicant portal persistence.
12. [~] Add duplicate detection and migration/import tools. Duplicate workflow exists; migration/import tools missing.
