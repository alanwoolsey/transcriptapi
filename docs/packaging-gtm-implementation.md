# crtfyStudent Packaging, GTM, And Implementation

## Packages

### Package 1: crtfyStudent Operations

Promise: give admissions teams a single operational workspace for student records, checklist completion, document queues, today's work, admin roles, and execution reporting.

Primary users:
- Admissions counselors
- Document processors
- Admissions operations managers
- Implementation admins

Included capabilities:
- Student 360 admissions record
- Checklist and completion engine
- Document queue and exception handling
- Today's Work and counselor workbench
- Admin users, roles, scopes, and sensitivity settings
- Operational reporting

### Package 2: crtfyStudent Decision Intelligence

Promise: turn transcript, document, trust, and academic evidence into controlled decision packets with release gates and auditable recommendations.

Primary users:
- Reviewers and evaluators
- Registrar or transfer specialists
- Decision releasers
- Trust analysts

Included capabilities:
- Decision studio
- Transfer and academic evidence
- Trust and duplicate review
- Recommendation generation and review
- Decision release controls
- Decision audit timeline

### Package 3: crtfyStudent Yield And Handoff

Promise: help teams protect admitted-student yield, deposits, milestones, melt risk, and cross-office handoff before enrollment.

Primary users:
- Admissions counselors
- Yield managers
- Financial aid
- Registrar and student success teams

Included capabilities:
- Yield queue
- Deposit and melt workbench
- Milestone templates and ownership
- Handoff readiness
- Sync error retry and acknowledgement
- Yield and melt reporting

### Package 4: crtfyStudent Platform

Promise: provide the integration, configuration, security, and implementation foundation needed to operate crtfyStudent at institution scale.

Primary users:
- System admins
- IT and integration teams
- Executive sponsors
- Implementation leads

Included capabilities:
- Connector marketplace and status
- Connector mappings
- Sync observability
- Implementation readiness checklist
- Role and sensitivity governance
- Benchmark reporting

## 30/60/90-Day Implementation Plan

### Days 0-30: Foundation

- Confirm package scope and success metrics.
- Configure tenant, roles, sensitivity tiers, and user access.
- Load checklist templates by population, program, term, and student type.
- Configure document types and initial queue rules.
- Validate first connector or import path.
- Train admins and pilot users.

Exit criteria:
- Users can log in with correct roles.
- Student 360, checklist, document queue, and today's work return live data.
- Audit events are visible for writes.

### Days 31-60: Workflow Activation

- Turn on document-to-checklist matching.
- Configure trust, duplicate, decision, yield, and melt queues as applicable.
- Tune readiness rules and release gates.
- Validate reporting and work projections.
- Run pilot cases through each purchased workflow.
- Train counselors, processors, reviewers, and managers.

Exit criteria:
- Staff can complete a student from intake through the purchased workflow.
- Exceptions route to the right queue.
- Managers can explain queue volume and blockers.

### Days 61-90: Scale And Optimize

- Add remaining integrations and mappings.
- Expand program, department, or population-specific rules.
- Review benchmark and operational metrics.
- Tune intervention, handoff, and reporting workflows.
- Complete go-live readiness checklist.
- Transition to steady-state support.

Exit criteria:
- Connector health and sync errors are monitored.
- Queue ownership is clear.
- Leadership reporting supports operating reviews.

## Training Plan By Role

Admissions counselor:
- Student 360
- Checklist and readiness
- Today's Work
- Interactions
- Yield follow-up

Document processor:
- Uploads and batch uploads
- Document queue
- Exception summaries
- Checklist linking
- Reprocess, replacement, release, and quarantine

Reviewer/evaluator:
- Transfer evidence
- Decision packet detail
- Recommendation review
- Notes and timeline

Trust analyst:
- Trust case queue
- Transcript trust detail
- Block, unblock, escalate, assign, and resolve
- Redaction and sensitivity expectations

Manager/admin:
- Work summary and reporting
- User and role administration
- Checklist templates
- Sensitivity and scope settings
- Connector readiness

## Go-Live Readiness

- Tenant and CORS configuration confirmed.
- Authentication and tenant access validated.
- Admin roles assigned.
- Checklist templates published.
- Sample students loaded and validated.
- Document processing tested with success and exception paths.
- Trust and decision gates tested.
- Reporting reviewed with stakeholders.
- Connector status and sync error handling validated.
- Support owner and escalation path documented.

