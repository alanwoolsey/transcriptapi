# Pre-SIS Lifecycle Data Model Checklist

This checklist tracks the planned evolution from a transcript/admissions operations model toward a full pre-SIS student lifecycle model.

## Phase 0 - Baseline And Design

- [x] Keep `docs/data-model.json` as the current schema snapshot.
- [ ] Add an architecture note describing the target pre-SIS lifecycle model.
- [ ] Confirm naming conventions for `application_id`, status fields, snapshots, and source/provenance fields.
- [ ] Decide which existing student-level fields remain as convenience rollups.
- [ ] Identify frontend/API response shapes that must remain backward compatible.
- [ ] Review current Alembic head and create a migration sequencing plan.

## Phase 1 - Core Admissions Backbone

- [x] Add `applications`.
- [x] Add `application_status_history`.
- [x] Add `admissions_decisions`.
- [x] Add `student_program_interests`.
- [x] Add `student_contact_methods`.
- [x] Add `student_addresses`.
- [x] Add SQLAlchemy models for the new tables.
- [x] Add Alembic migration for the new tables.
- [x] Add indexes for tenant, student, application status, term, and program lookups.
- [x] Add Pydantic request/response models for application records.
- [x] Add service functions for creating and updating applications.
- [x] Add route coverage for application list/detail/create/update.
- [ ] Add tests for application creation, status movement, and decision creation.

## Phase 1 Backfill

- [ ] Backfill one default application for existing students where application context can be inferred.
- [ ] Link existing decision/readiness data to the default application where safe.
- [ ] Preserve existing student summary behavior after backfill.
- [ ] Add idempotency checks for the backfill.
- [ ] Add migration/backfill verification queries.

## Phase 2 - Application-Aware Existing Work

- [x] Add nullable `application_id` to `student_checklists`.
- [x] Add `checklist_type` to `student_checklists`.
- [x] Replace single-student checklist uniqueness with application-aware uniqueness.
- [ ] Add or update checklist service logic to resolve checklist scope by application.
- [x] Add `application_id` to `decision_packets`.
- [ ] Clarify decision packet snapshot fields, either by renaming or adding `*_snapshot` fields.
- [x] Add `application_documents` join table.
- [ ] Link documents, uploads, transcripts, and checklist evidence to applications where appropriate.
- [x] Add `application_readiness` for application-level readiness.
- [x] Keep student-level readiness as a rollup/projection.
- [ ] Add tests for multiple applications per student with distinct checklists and decisions.

## Phase 3 - Student Lifecycle Completeness

- [x] Add `student_relationships`.
- [x] Add `student_education_history`.
- [x] Add `student_test_scores`.
- [x] Add `student_deposits`.
- [x] Add `student_scholarships`.
- [x] Add `student_financial_aid_status`.
- [x] Add models and migrations for the new lifecycle tables.
- [ ] Add service support for education history before transcript receipt.
- [ ] Add service support for official and self-reported test scores.
- [ ] Add API models/routes as needed for student 360 detail.
- [ ] Add tests for contacts, addresses, relationships, education history, and scores.

## Phase 4 - SIS Handoff Layer

- [x] Add `sis_connections`.
- [x] Add `sis_field_mappings`.
- [x] Add `sis_exports`.
- [x] Add `sis_export_events`.
- [x] Add `external_system_identifiers`.
- [ ] Define supported `sis_system` values.
- [ ] Define supported `export_type` values.
- [ ] Add validation for required SIS fields before export.
- [ ] Add payload/response persistence for export attempts.
- [ ] Add retry-safe export status transitions.
- [ ] Add tests for successful export, failed export, retry, and external ID persistence.

## Phase 5 - Teams, Users, And RBAC Cleanup

- [x] Add `teams`.
- [x] Add `team_memberships`.
- [ ] Replace text `owner_team_id` usage with UUID team references over time.
- [ ] Review `app_users.email` global uniqueness assumptions.
- [ ] Review `tenant_user_memberships.user_id` uniqueness and remove if multi-tenant users are required.
- [ ] Add nullable `tenant_id` to roles if tenant custom roles are needed.
- [ ] Add `role_type` for system versus tenant custom roles.
- [ ] Update RBAC services and tests for team and tenant role behavior.

## Phase 6 - History, Provenance, And Reporting Quality

- [x] Add `student_score_history`.
- [ ] Decide whether current score tables remain as current-state projections.
- [ ] Standardize confidence fields as `NUMERIC(5,4)` from `0.0000` to `1.0000`.
- [ ] Standardize score fields as integer `0-100`.
- [ ] Standardize GPA fields as `NUMERIC(5,3)` or `NUMERIC(5,2)`.
- [ ] Standardize credit fields as `NUMERIC(8,2)`.
- [x] Add `student_profile_facts` for field-level provenance.
- [x] Track source type, source ID, confidence, verified status, and effective timestamp for profile facts.
- [ ] Identify high-value status fields to convert from free text to reference/config tables.
- [ ] Add reporting tests for status consistency and score history.

## Reference Data And Configuration

- [x] Add `terms`.
- [x] Add `campuses`.
- [x] Add `modalities`.
- [x] Add `student_types`.
- [x] Add `populations`.
- [x] Add `lifecycle_stages`.
- [x] Add `decision_codes`.
- [x] Add `checklist_item_types`.
- [x] Add `source_categories`.
- [x] Add `interaction_types`.
- [x] Add `task_types`.
- [ ] Decide which reference tables are global, tenant-owned, or mixed.

## Communication And Engagement

- [x] Add `communication_templates`.
- [x] Add `communication_messages`.
- [x] Add `communication_events`.
- [x] Add `student_communication_preferences`.
- [x] Link communication records to student and application where applicable.
- [x] Track sent, delivered, opened, clicked, replied, bounced, and opted-out events.

## Forms And Application Engine Linkage

- [x] Add `form_submissions`.
- [x] Add `form_submission_answers`.
- [x] Add `application_form_submissions`.
- [x] Store durable references to forms managed by crtfy Content or another form engine.
- [x] Link submitted forms to application checklist/readiness where applicable.

## Verification Gates

- [ ] Existing transcript upload and processing tests pass.
- [x] Existing prospect import tests pass.
- [x] Existing student 360 tests pass.
- [x] Existing decision workflow tests pass.
- [ ] Existing trust/workflow/agent tests pass.
- [ ] New migrations apply cleanly on an empty database.
- [ ] New migrations apply cleanly on a database with seeded/demo data.
- [ ] Backfills are idempotent.
- [x] Generated schema snapshot can be refreshed after each phase.
