from __future__ import annotations

import re
import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AppUser,
    AuditEvent,
    Institution,
    Program,
    Prospect,
    ProspectApiCredential,
    ProspectAssignmentRule,
    ProspectFitResult,
    ProspectImportBatch,
    ProspectImportException,
    ProspectImportRow,
    ProspectImportSource,
    ProspectImportTemplate,
    ProspectNextAction,
    ProspectScheduledImport,
    ProspectSourceReference,
    ProspectTranscriptUpload,
    ProspectWebhookEvent,
    Student,
    StudentAssignment,
    StudentIdentifier,
    StudentSource,
)
from app.db.session import get_session_factory
from app.models.ops_models import WorkItemOwner, WorkItemReason, WorkTodayItemResponse
from app.models.prospect_models import (
    ProspectConvertResponse,
    ProspectCounselor,
    ProspectFitResponse,
    ProspectApiCredentialListResponse,
    ProspectApiCredentialRequest,
    ProspectApiCredentialResponse,
    ProspectApiImportRequest,
    ProspectApiImportResponse,
    ProspectAssignmentRuleListResponse,
    ProspectAssignmentRuleRequest,
    ProspectAssignmentRuleResponse,
    ProspectImportErrorFileResponse,
    ProspectImportExceptionListResponse,
    ProspectImportExceptionResolveRequest,
    ProspectImportExceptionResponse,
    ProspectImportBatchListResponse,
    ProspectImportBatchResponse,
    ProspectImportConfirmResponse,
    ProspectImportCounts,
    ProspectImportIssue,
    ProspectImportPreviewResponse,
    ProspectImportPreviewRow,
    ProspectImportRowsRequest,
    ProspectImportTemplateListResponse,
    ProspectImportTemplateRequest,
    ProspectImportTemplateResponse,
    ProspectScheduledImportListResponse,
    ProspectScheduledImportRequest,
    ProspectScheduledImportResponse,
    ProspectSourceReportingResponse,
    ProspectImportSourceCreateRequest,
    ProspectImportSourceListResponse,
    ProspectImportSourceResponse,
    ProspectInquiryRequest,
    ProspectInquiryResponse,
    ProspectNextStep,
    ProspectProgramFit,
    ProspectRecordResponse,
    ProspectSignal,
    ProspectUploadResponse,
    ProspectUploadStatusResponse,
)
from app.services.pipeline_status import canonical_pipeline_status


class ProspectNotFoundError(Exception):
    pass


class ProspectValidationError(Exception):
    pass


class ProspectService:
    VALID_LIFECYCLE_STAGES = {"prospect", "inquiry", "applicant", "withdrawn", "duplicate_candidate"}
    VALID_STATUSES = {
        "new",
        "needs_follow_up",
        "transcript_received",
        "fit_ready",
        "application_started",
        "converted",
        "duplicate_candidate",
        "archived",
    }
    VALID_UPLOAD_STATUSES = {"received", "processing", "fit_ready", "needs_review", "failed"}
    VALID_ACTION_CODES = {
        "start_application",
        "upload_transcript",
        "schedule_counselor",
        "answer_question",
        "review_transfer_fit",
        "resolve_duplicate",
    }
    IMPORT_FIELDS = {
        "firstName",
        "lastName",
        "email",
        "mobilePhone",
        "phone",
        "addressLine1",
        "city",
        "state",
        "postalCode",
        "externalSourceId",
        "highSchool",
        "highSchoolGradYear",
        "academicInterest",
        "entryTerm",
        "studentType",
        "lifecycleStage",
        "sourceDetail",
        "ignore",
    }
    SOURCE_STAGE_DEFAULTS = {
        "college_board_search": "prospect",
        "search_list": "prospect",
        "college_fair": "inquiry",
        "rfi": "inquiry",
        "form": "inquiry",
        "event": "inquiry",
        "application_start": "application_started",
        "application_submit": "application_submitted",
        "athletic_recruit": "prospect",
        "partner_referral": "inquiry",
    }

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def list_import_sources(self, db: Session, *, tenant_id: UUID) -> ProspectImportSourceListResponse:
        sources = db.execute(
            select(ProspectImportSource)
            .where(ProspectImportSource.tenant_id == tenant_id, ProspectImportSource.is_active.is_(True))
            .order_by(ProspectImportSource.name.asc())
        ).scalars().all()
        return ProspectImportSourceListResponse(sources=[self._serialize_import_source(source) for source in sources])

    def create_import_source(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectImportSourceCreateRequest,
    ) -> ProspectImportSourceResponse:
        name = self._required_text(payload.name, "Source name is required.")
        source_type = self._normalize_source_type(payload.sourceType)
        existing = db.execute(
            select(ProspectImportSource).where(ProspectImportSource.tenant_id == tenant_id, func.lower(ProspectImportSource.name) == name.lower()).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            raise ProspectValidationError("A prospect source with this name already exists.")
        source = ProspectImportSource(
            tenant_id=tenant_id,
            name=name,
            source_type=source_type,
            source_category=self._blank_to_none(payload.sourceCategory) or "recruitment",
            default_lifecycle_stage=self._blank_to_none(payload.defaultLifecycleStage) or self._stage_for_source(source_type),
            default_population=self._normalize_population(payload.defaultPopulation or payload.defaultStudentType or "prospect"),
            default_student_type=self._normalize_student_type(payload.defaultStudentType),
            default_entry_term=self._normalize_entry_term(payload.defaultEntryTerm),
            default_mapping_json=self._clean_mapping(payload.defaultMapping),
            is_active=True,
            created_by_user_id=actor_user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return self._serialize_import_source(source)

    def preview_import_rows(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        payload: ProspectImportRowsRequest,
    ) -> ProspectImportPreviewResponse:
        source = self._resolve_import_source(db, tenant_id, payload.sourceId)
        mapping = self._clean_mapping(payload.mapping or (source.default_mapping_json if source else {}))
        source_type = self._normalize_source_type(payload.sourceType or (source.source_type if source else "manual_import"))
        source_category = self._blank_to_none(payload.sourceCategory) or (source.source_category if source else "recruitment")
        preview_rows, counts, issues = self._preview_rows(db, tenant_id, payload.rows, mapping, source, source_type, source_category)
        return ProspectImportPreviewResponse(counts=counts, rows=preview_rows, issues=issues)

    def import_rows(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectImportRowsRequest,
    ) -> ProspectImportConfirmResponse:
        source = self._resolve_import_source(db, tenant_id, payload.sourceId)
        mapping = self._clean_mapping(payload.mapping or (source.default_mapping_json if source else {}))
        source_type = self._normalize_source_type(payload.sourceType or (source.source_type if source else "manual_import"))
        source_category = self._blank_to_none(payload.sourceCategory) or (source.source_category if source else "recruitment")
        preview_rows, counts, issues = self._preview_rows(db, tenant_id, payload.rows, mapping, source, source_type, source_category)
        batch_id = uuid4()
        now = datetime.now(timezone.utc)
        batch = ProspectImportBatch(
            id=batch_id,
            tenant_id=tenant_id,
            source_id=source.id if source else None,
            filename=self._safe_filename(payload.filename or "prospects.csv"),
            uploaded_by_user_id=actor_user_id,
            status="completed",
            import_mode=self._blank_to_none(payload.importMode) or "create_or_update",
            mapping_json=mapping,
            metadata_json={"issues": [issue.model_dump() for issue in issues], "sourceDetail": payload.sourceDetail},
            total_rows=counts.total,
            new_count=counts.new,
            matched_count=counts.matched,
            duplicate_count=counts.duplicates,
            error_count=counts.errors,
            skipped_count=counts.skipped,
            created_at=now,
            completed_at=now,
        )
        db.add(batch)

        created = 0
        updated = 0
        for row in preview_rows:
            record = self._map_import_row(payload.rows[row.rowNumber - 1], mapping)
            row_model = ProspectImportRow(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_id=source.id if source else None,
                row_number=row.rowNumber,
                raw_json=dict(payload.rows[row.rowNumber - 1] or {}),
                normalized_json=record,
                status=row.action,
                matched_student_id=self._uuid_or_none(row.matchedStudentId),
                matched_prospect_id=self._uuid_or_none(row.matchedProspectId.replace("pro_", "") if row.matchedProspectId else None),
                match_confidence=self._match_confidence_from_preview(row),
                error_messages_json=[issue.message for issue in row.issues],
                created_at=now,
            )
            db.add(row_model)
            db.flush()
            for issue in row.issues:
                if issue.severity in {"error", "warning"}:
                    db.add(
                        ProspectImportException(
                            tenant_id=tenant_id,
                            batch_id=batch_id,
                            row_id=row_model.id,
                            exception_type=self._exception_type_for_issue(issue),
                            severity=issue.severity,
                            status="open" if issue.severity == "error" else "review",
                            message=issue.message,
                            metadata_json={"code": issue.code, "field": issue.field, "rowNumber": row.rowNumber},
                            created_at=now,
                        )
                    )
            if row.action in {"error", "duplicate", "skip"}:
                continue
            result = self._upsert_import_record(
                db,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                batch_id=batch_id,
                source=source,
                source_type=source_type,
                source_category=source_category,
                source_detail=payload.sourceDetail,
                record=record,
                raw_record=dict(payload.rows[row.rowNumber - 1] or {}),
            )
            row_model.status = result
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
        batch.created_count = created
        batch.updated_count = updated
        counts.created = created
        counts.updated = updated
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect_import_batch",
            entity_id=batch_id,
            action="prospect_import_completed",
            metadata={"filename": batch.filename, "created": created, "updated": updated, "errors": counts.errors},
        )
        db.commit()
        return ProspectImportConfirmResponse(batchId=str(batch_id), counts=counts, status="completed", issues=issues)

    def list_import_batches(self, db: Session, *, tenant_id: UUID, limit: int = 25) -> ProspectImportBatchListResponse:
        rows = db.execute(
            select(ProspectImportBatch, ProspectImportSource, AppUser)
            .outerjoin(ProspectImportSource, ProspectImportSource.id == ProspectImportBatch.source_id)
            .outerjoin(AppUser, AppUser.id == ProspectImportBatch.uploaded_by_user_id)
            .where(ProspectImportBatch.tenant_id == tenant_id)
            .order_by(ProspectImportBatch.created_at.desc())
            .limit(limit)
        ).all()
        return ProspectImportBatchListResponse(
            imports=[self._serialize_import_batch(batch, source, user) for batch, source, user in rows]
        )

    def list_import_templates(self, db: Session, *, tenant_id: UUID) -> ProspectImportTemplateListResponse:
        templates = db.execute(
            select(ProspectImportTemplate).where(ProspectImportTemplate.tenant_id == tenant_id).order_by(ProspectImportTemplate.updated_at.desc())
        ).scalars().all()
        return ProspectImportTemplateListResponse(templates=[self._serialize_template(template) for template in templates])

    def create_import_template(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectImportTemplateRequest,
    ) -> ProspectImportTemplateResponse:
        template = ProspectImportTemplate(
            tenant_id=tenant_id,
            name=self._required_text(payload.name, "Template name is required."),
            source_type=self._normalize_source_type(payload.sourceType),
            source_detail=self._blank_to_none(payload.sourceDetail),
            default_lifecycle_stage=self._blank_to_none(payload.defaultLifecycleStage),
            field_mappings_json=self._clean_mapping(payload.fieldMappings),
            normalization_rules_json=dict(payload.normalizationRules or {}),
            dedupe_rules_json=dict(payload.dedupeRules or {}),
            assignment_rules_json=dict(payload.assignmentRules or {}),
            campaign_rules_json=dict(payload.campaignRules or {}),
            validation_rules_json=dict(payload.validationRules or {}),
            created_by_user_id=actor_user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return self._serialize_template(template)

    def list_assignment_rules(self, db: Session, *, tenant_id: UUID) -> ProspectAssignmentRuleListResponse:
        rules = db.execute(
            select(ProspectAssignmentRule)
            .where(ProspectAssignmentRule.tenant_id == tenant_id)
            .order_by(ProspectAssignmentRule.priority.asc(), ProspectAssignmentRule.created_at.desc())
        ).scalars().all()
        return ProspectAssignmentRuleListResponse(rules=[self._serialize_assignment_rule(rule) for rule in rules])

    def create_assignment_rule(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        payload: ProspectAssignmentRuleRequest,
    ) -> ProspectAssignmentRuleResponse:
        source = self._resolve_import_source(db, tenant_id, payload.sourceId) if payload.sourceId else None
        rule = ProspectAssignmentRule(
            tenant_id=tenant_id,
            source_id=source.id if source else None,
            name=self._required_text(payload.name, "Rule name is required."),
            field=self._required_text(payload.field, "Rule field is required."),
            operator=self._blank_to_none(payload.operator) or "equals",
            value=self._required_text(payload.value, "Rule value is required."),
            owner_user_id=self._uuid_or_none(payload.ownerUserId),
            owner_team_id=self._blank_to_none(payload.ownerTeamId),
            territory=self._blank_to_none(payload.territory),
            priority=payload.priority,
            active=payload.active,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return self._serialize_assignment_rule(rule)

    def list_scheduled_imports(self, db: Session, *, tenant_id: UUID) -> ProspectScheduledImportListResponse:
        schedules = db.execute(
            select(ProspectScheduledImport).where(ProspectScheduledImport.tenant_id == tenant_id).order_by(ProspectScheduledImport.created_at.desc())
        ).scalars().all()
        return ProspectScheduledImportListResponse(schedules=[self._serialize_schedule(schedule) for schedule in schedules])

    def create_scheduled_import(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        payload: ProspectScheduledImportRequest,
    ) -> ProspectScheduledImportResponse:
        source = self._resolve_import_source(db, tenant_id, payload.sourceId) if payload.sourceId else None
        schedule = ProspectScheduledImport(
            tenant_id=tenant_id,
            source_id=source.id if source else None,
            mapping_template_id=self._uuid_or_none(payload.mappingTemplateId),
            delivery_method=(payload.deliveryMethod or "sftp").strip().lower(),
            inbound_folder=self._blank_to_none(payload.inboundFolder),
            schedule=self._blank_to_none(payload.schedule),
            import_mode=self._blank_to_none(payload.importMode) or "create_or_update",
            failure_notification_email=self._blank_to_none(payload.failureNotificationEmail),
            status=self._blank_to_none(payload.status) or "active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        return self._serialize_schedule(schedule)

    def list_api_credentials(self, db: Session, *, tenant_id: UUID) -> ProspectApiCredentialListResponse:
        credentials = db.execute(
            select(ProspectApiCredential).where(ProspectApiCredential.tenant_id == tenant_id).order_by(ProspectApiCredential.created_at.desc())
        ).scalars().all()
        return ProspectApiCredentialListResponse(credentials=[self._serialize_api_credential(credential) for credential in credentials])

    def create_api_credential(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectApiCredentialRequest,
    ) -> ProspectApiCredentialResponse:
        api_key = f"crtfy_{secrets.token_urlsafe(32)}"
        credential = ProspectApiCredential(
            tenant_id=tenant_id,
            source_id=self._uuid_or_none(payload.sourceId),
            name=self._required_text(payload.name, "API credential name is required."),
            key_prefix=api_key[:14],
            key_hash=hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
            active=True,
            created_by_user_id=actor_user_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(credential)
        db.commit()
        db.refresh(credential)
        response = self._serialize_api_credential(credential)
        response.apiKey = api_key
        return response

    def list_import_exceptions(self, db: Session, *, tenant_id: UUID) -> ProspectImportExceptionListResponse:
        exceptions = db.execute(
            select(ProspectImportException)
            .where(ProspectImportException.tenant_id == tenant_id)
            .order_by(ProspectImportException.created_at.desc())
            .limit(100)
        ).scalars().all()
        return ProspectImportExceptionListResponse(exceptions=[self._serialize_exception(exception) for exception in exceptions])

    def resolve_import_exception(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        exception_id: str,
        payload: ProspectImportExceptionResolveRequest,
    ) -> ProspectImportExceptionResponse:
        exception_uuid = self._parse_uuid(exception_id, "exception identifier")
        exception = db.execute(
            select(ProspectImportException).where(ProspectImportException.tenant_id == tenant_id, ProspectImportException.id == exception_uuid).limit(1)
        ).scalar_one_or_none()
        if exception is None:
            raise ProspectNotFoundError("Import exception not found.")
        exception.status = "resolved"
        exception.resolution = payload.resolution
        exception.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(exception)
        return self._serialize_exception(exception)

    def api_import(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectApiImportRequest,
    ) -> ProspectApiImportResponse:
        row = self._api_payload_to_row(payload)
        mapping = {key: key for key in row.keys()}
        import_payload = ProspectImportRowsRequest(
            sourceId=payload.sourceId,
            filename=f"{payload.sourceType or 'api_import'}.json",
            sourceName=payload.sourceName,
            sourceType=payload.sourceType,
            sourceCategory="api",
            sourceDetail=payload.sourceDetail,
            mapping=mapping,
            rows=[row],
            importMode="create_or_update",
        )
        result = self.import_rows(db, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=import_payload)
        db.add(
            ProspectWebhookEvent(
                tenant_id=tenant_id,
                source_id=self._uuid_or_none(payload.sourceId),
                event_type=payload.sourceType or "api_import",
                status=result.status,
                payload_json=payload.model_dump(),
                result_json=result.model_dump(),
                received_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        return ProspectApiImportResponse(batchId=result.batchId, status=result.status, counts=result.counts, issues=result.issues)

    def get_source_reporting(self, db: Session, *, tenant_id: UUID) -> ProspectSourceReportingResponse:
        source_rows = db.execute(
            select(Prospect.source, Prospect.lifecycle_stage, func.count(Prospect.id))
            .where(Prospect.tenant_id == tenant_id)
            .group_by(Prospect.source, Prospect.lifecycle_stage)
        ).all()
        by_source: dict[str, dict[str, object]] = {}
        for source, stage, count in source_rows:
            bucket = by_source.setdefault(source or "Unknown", {"source": source or "Unknown", "prospects": 0, "inquiries": 0, "applications": 0, "admits": 0, "deposits": 0})
            bucket["prospects"] = int(bucket["prospects"]) + int(count)
            if stage == "inquiry":
                bucket["inquiries"] = int(bucket["inquiries"]) + int(count)
            if "application" in (stage or "") or stage == "applicant":
                bucket["applications"] = int(bucket["applications"]) + int(count)
        for bucket in by_source.values():
            prospects = max(1, int(bucket["prospects"]))
            bucket["conversionRate"] = round((int(bucket["applications"]) / prospects) * 100, 1)
        import_rows = db.execute(
            select(ProspectImportBatch, ProspectImportSource)
            .outerjoin(ProspectImportSource, ProspectImportSource.id == ProspectImportBatch.source_id)
            .where(ProspectImportBatch.tenant_id == tenant_id)
            .order_by(ProspectImportBatch.created_at.desc())
            .limit(25)
        ).all()
        performance = [
            {
                "batchId": str(batch.id),
                "source": source.name if source else "Manual import",
                "createdAt": batch.created_at.isoformat(),
                "total": batch.total_rows,
                "created": batch.created_count,
                "updated": batch.updated_count,
                "duplicates": batch.duplicate_count,
                "errors": batch.error_count,
            }
            for batch, source in import_rows
        ]
        trend = [
            {"batchId": item["batchId"], "date": item["createdAt"], "duplicates": item["duplicates"], "errors": item["errors"]}
            for item in performance
        ]
        return ProspectSourceReportingResponse(
            sources=list(by_source.values()),
            importPerformance=performance,
            duplicateAndErrorTrend=trend,
            totals={
                "sources": len(by_source),
                "imports": len(performance),
                "errors": sum(int(item["errors"]) for item in performance),
                "duplicates": sum(int(item["duplicates"]) for item in performance),
            },
        )

    def get_import_error_file(self, db: Session, *, tenant_id: UUID, batch_id: str) -> ProspectImportErrorFileResponse:
        batch_uuid = self._parse_uuid(batch_id, "batch identifier")
        rows = db.execute(
            select(ProspectImportRow)
            .where(ProspectImportRow.tenant_id == tenant_id, ProspectImportRow.batch_id == batch_uuid, ProspectImportRow.status.in_(["error", "duplicate", "exception"]))
            .order_by(ProspectImportRow.row_number.asc())
        ).scalars().all()
        lines = ["rowNumber,status,messages,raw"]
        for row in rows:
            messages = "; ".join(str(message) for message in row.error_messages_json or [])
            raw = str(row.raw_json or {}).replace('"', '""')
            lines.append(f'{row.row_number},{row.status},"{messages}","{raw}"')
        return ProspectImportErrorFileResponse(filename=f"prospect-import-errors-{batch_id}.csv", content="\n".join(lines))

    def create_inquiry(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectInquiryRequest,
    ) -> ProspectInquiryResponse:
        self._validate_inquiry(payload)
        now = datetime.now(timezone.utc)
        email = self._normalize_email(payload.email)
        owner = self._default_owner(db, tenant_id, actor_user_id)
        duplicate_student = self._find_duplicate_student(db, tenant_id, email, payload.phone)
        prospect = self._find_duplicate_prospect(db, tenant_id, email, payload.phone, payload.externalReferenceId)
        duplicate_candidate = duplicate_student is not None and (prospect is None or prospect.student_id != duplicate_student.id)

        if prospect is None:
            prospect = Prospect(
                tenant_id=tenant_id,
                first_name=payload.firstName.strip(),
                last_name=payload.lastName.strip(),
                email=email,
                population=self._normalize_population(payload.population),
                lifecycle_stage="duplicate_candidate" if duplicate_candidate else "inquiry",
                status="duplicate_candidate" if duplicate_candidate else "new",
                owner_user_id=owner.id if owner else actor_user_id,
                source=payload.source.strip() or "manual_entry",
                source_category=payload.sourceCategory.strip() or "direct",
                consent_captured=payload.consent,
                created_at=now,
                updated_at=now,
            )
            db.add(prospect)
            db.flush()

        prospect.first_name = payload.firstName.strip()
        prospect.last_name = payload.lastName.strip()
        prospect.email = email
        prospect.phone = self._blank_to_none(payload.phone)
        prospect.population = self._normalize_population(payload.population)
        prospect.program_interest = self._blank_to_none(payload.programInterest)
        prospect.term_interest = self._blank_to_none(payload.termInterest)
        prospect.prior_institution = self._blank_to_none(payload.priorInstitution)
        prospect.source = payload.source.strip() or prospect.source
        prospect.source_category = payload.sourceCategory.strip() or prospect.source_category
        prospect.campaign = self._blank_to_none(payload.campaign)
        prospect.consent_captured = payload.consent
        prospect.question = self._blank_to_none(payload.question)
        prospect.owner_user_id = prospect.owner_user_id or (owner.id if owner else actor_user_id)
        prospect.student_id = prospect.student_id or (duplicate_student.id if duplicate_student else None)
        prospect.lifecycle_stage = "duplicate_candidate" if duplicate_candidate else "inquiry"
        prospect.status = self._initial_status(payload, duplicate_candidate)
        prospect.updated_at = now

        db.add(
            ProspectSourceReference(
                tenant_id=tenant_id,
                prospect_id=prospect.id,
                source=prospect.source,
                source_category=prospect.source_category,
                campaign=prospect.campaign,
                external_reference_id=self._blank_to_none(payload.externalReferenceId),
                metadata_json={
                    "transcriptUploadId": payload.transcriptUploadId,
                    "transcriptFilename": payload.transcriptFilename,
                },
                captured_at=now,
            )
        )

        upload = self._resolve_upload(db, tenant_id, payload.transcriptUploadId, email)
        if upload is not None:
            upload.prospect_id = prospect.id
            upload.status = "fit_ready"
            upload.updated_at = now

        fit = self._upsert_fit_result(db, tenant_id, prospect, upload)
        action = self._upsert_next_action(db, tenant_id, prospect, fit, owner)
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect",
            entity_id=prospect.id,
            action="prospect_inquiry_created",
            metadata={"email": email, "status": prospect.status, "duplicateCandidate": duplicate_candidate},
        )
        db.commit()
        return ProspectInquiryResponse(prospect=self._serialize_prospect(db, tenant_id, prospect, fit, action, upload))

    def create_transcript_upload(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        email: str,
        population: str,
        program_interest: str | None,
        term_interest: str | None,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ProspectUploadResponse:
        if not content:
            raise ProspectValidationError("Transcript upload file is required.")
        normalized_email = self._normalize_email(email)
        safe_filename = self._safe_filename(filename)
        upload = ProspectTranscriptUpload(
            tenant_id=tenant_id,
            prospect_id=None,
            email=normalized_email,
            filename=safe_filename,
            content_type=content_type or "application/octet-stream",
            file_size=len(content),
            storage_uri="pending",
            status="received",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(upload)
        db.flush()
        storage_uri = self._store_upload(tenant_id, upload.id, safe_filename, content)
        upload.storage_uri = storage_uri
        upload.status = "fit_ready"
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect_transcript_upload",
            entity_id=upload.id,
            action="prospect_transcript_uploaded",
            metadata={
                "email": normalized_email,
                "population": population,
                "programInterest": program_interest,
                "termInterest": term_interest,
                "filename": safe_filename,
            },
        )
        db.commit()
        return ProspectUploadResponse(uploadId=self._public_id("upl", upload.id), status=upload.status, filename=upload.filename)

    def get_upload_status(self, tenant_id: UUID, upload_id: str) -> ProspectUploadStatusResponse:
        session_factory = self.session_factory()
        with session_factory() as db:
            upload = self._get_upload(db, tenant_id, upload_id)
            return ProspectUploadStatusResponse(
                uploadId=self._public_id("upl", upload.id),
                status=upload.status,
                processingRunId=(str(upload.processing_run_id) if upload.processing_run_id else None),
                message=self._upload_status_message(upload.status),
            )

    def get_fit(self, tenant_id: UUID, prospect_id: str) -> ProspectFitResponse:
        session_factory = self.session_factory()
        with session_factory() as db:
            prospect = self._get_prospect(db, tenant_id, prospect_id)
            fit = self._latest_fit(db, tenant_id, prospect.id)
            action = self._latest_action(db, tenant_id, prospect.id)
            return ProspectFitResponse(
                programFit=self._serialize_fit(fit),
                missingItems=list(fit.missing_items_json or []) if fit else self._missing_items(prospect),
                signals=[ProspectSignal(**item) for item in list(fit.signals_json or [])] if fit else self._signals(prospect),
                nextStep=self._serialize_next_step(action),
            )

    def convert_application(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        prospect_id: str,
    ) -> ProspectConvertResponse:
        prospect = self._get_prospect(db, tenant_id, prospect_id)
        if prospect.status == "converted" and prospect.student_id:
            return ProspectConvertResponse(studentId=str(prospect.student_id), prospectId=self._public_id("pro", prospect.id), status=prospect.status)

        student = self._find_duplicate_student(db, tenant_id, prospect.email, prospect.phone)
        if student is None and prospect.student_id is not None:
            student = db.execute(
                select(Student).where(Student.tenant_id == tenant_id, Student.id == prospect.student_id).limit(1)
            ).scalar_one_or_none()
        if student is None:
            student = self._create_student_from_prospect(db, tenant_id, prospect)

        prospect.student_id = student.id
        prospect.lifecycle_stage = "applicant"
        prospect.status = "converted"
        prospect.updated_at = datetime.now(timezone.utc)
        for action in db.execute(
            select(ProspectNextAction).where(
                ProspectNextAction.tenant_id == tenant_id,
                ProspectNextAction.prospect_id == prospect.id,
                ProspectNextAction.status == "open",
            )
        ).scalars().all():
            action.status = "completed"
            action.completed_at = datetime.now(timezone.utc)
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect",
            entity_id=prospect.id,
            action="prospect_converted_to_application",
            metadata={"studentId": str(student.id)},
        )
        db.commit()
        return ProspectConvertResponse(studentId=str(student.id), prospectId=self._public_id("pro", prospect.id), status=prospect.status)

    def get_today_work_items(self, tenant_id: UUID, *, limit: int = 50) -> list[WorkTodayItemResponse]:
        session_factory = self.session_factory()
        with session_factory() as db:
            rows = db.execute(
                select(Prospect, ProspectNextAction, ProspectFitResult, AppUser)
                .join(ProspectNextAction, ProspectNextAction.prospect_id == Prospect.id)
                .outerjoin(ProspectFitResult, ProspectFitResult.prospect_id == Prospect.id)
                .outerjoin(AppUser, AppUser.id == Prospect.owner_user_id)
                .where(
                    Prospect.tenant_id == tenant_id,
                    ProspectNextAction.tenant_id == tenant_id,
                    ProspectNextAction.status == "open",
                    Prospect.status.in_(["new", "needs_follow_up", "transcript_received", "fit_ready", "duplicate_candidate"]),
                )
                .order_by(Prospect.updated_at.desc())
                .limit(limit)
            ).all()
            seen: set[UUID] = set()
            items: list[WorkTodayItemResponse] = []
            for prospect, action, fit, owner in rows:
                if prospect.id in seen:
                    continue
                seen.add(prospect.id)
                items.append(self._build_work_item(prospect, action, fit, owner))
            return items

    def _preview_rows(
        self,
        db: Session,
        tenant_id: UUID,
        rows: list[dict],
        mapping: dict[str, str],
        source: ProspectImportSource | None,
        source_type: str,
        source_category: str,
    ) -> tuple[list[ProspectImportPreviewRow], ProspectImportCounts, list[ProspectImportIssue]]:
        counts = ProspectImportCounts(total=len(rows))
        preview_rows: list[ProspectImportPreviewRow] = []
        issues: list[ProspectImportIssue] = []
        seen_keys: set[str] = set()
        for index, raw_row in enumerate(rows, start=1):
            record = self._map_import_row(raw_row, mapping)
            row_issues = self._validate_import_record(index, record)
            key = self._dedupe_key(record)
            if key and key in seen_keys:
                row_issues.append(self._issue(index, "warning", "duplicate_in_file", "Another row in this file has the same email, phone, or external ID."))
                counts.duplicates += 1
            if key:
                seen_keys.add(key)
            if any(issue.code == "missing_contact" for issue in row_issues):
                counts.missingContact += 1
            if any(issue.code == "invalid_email" for issue in row_issues):
                counts.invalidEmail += 1
            if any(issue.code == "invalid_phone" for issue in row_issues):
                counts.invalidPhone += 1
            if not self._blank_to_none(record.get("academicInterest")):
                counts.missingAcademicInterest += 1
            matched_student, matched_prospect = self._find_import_matches(db, tenant_id, record)
            if any(issue.severity == "error" for issue in row_issues):
                action = "error"
                counts.errors += 1
                counts.skipped += 1
            elif matched_student or matched_prospect:
                action = "update"
                counts.matched += 1
            else:
                action = "create"
                counts.new += 1
            stage = self._normalize_lifecycle_stage(record.get("lifecycleStage"), source, source_type)
            preview = ProspectImportPreviewRow(
                rowNumber=index,
                action=action,
                firstName=self._blank_to_none(record.get("firstName")),
                lastName=self._blank_to_none(record.get("lastName")),
                email=self._blank_to_none(record.get("email")),
                phone=self._normalized_phone(record.get("mobilePhone") or record.get("phone")),
                academicInterest=self._blank_to_none(record.get("academicInterest")),
                entryTerm=self._normalize_entry_term(record.get("entryTerm") or (source.default_entry_term if source else None)),
                lifecycleStage=stage,
                matchedStudentId=str(matched_student.id) if matched_student else None,
                matchedProspectId=self._public_id("pro", matched_prospect.id) if matched_prospect else None,
                issues=row_issues,
            )
            preview_rows.append(preview)
            issues.extend(row_issues)
        return preview_rows, counts, issues

    def _upsert_import_record(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        batch_id: UUID,
        source: ProspectImportSource | None,
        source_type: str,
        source_category: str,
        source_detail: str | None,
        record: dict[str, str | None],
        raw_record: dict | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        first_name = self._blank_to_none(record.get("firstName")) or ""
        last_name = self._blank_to_none(record.get("lastName")) or ""
        email = self._blank_to_none(record.get("email"))
        phone = self._normalized_phone(record.get("mobilePhone") or record.get("phone"))
        external_id = self._blank_to_none(record.get("externalSourceId"))
        source_name = source.name if source else (source_detail or source_type)
        stage = self._normalize_lifecycle_stage(record.get("lifecycleStage"), source, source_type)
        population = self._normalize_population(record.get("studentType") or (source.default_population if source else None) or "prospect")
        program_interest, program = self._normalize_program_interest(db, tenant_id, record.get("academicInterest"))
        entry_term = self._normalize_entry_term(record.get("entryTerm") or (source.default_entry_term if source else None))
        student, prospect = self._find_import_matches(db, tenant_id, record)
        created = student is None
        if student is None:
            student = Student(
                tenant_id=tenant_id,
                external_student_id=external_id,
                first_name=first_name,
                last_name=last_name,
                preferred_name=first_name,
                email=email,
                phone=phone,
                city=self._blank_to_none(record.get("city")),
                state=self._blank_to_none(record.get("state")),
                country="US",
                target_program_id=program.id if program else None,
                current_stage=canonical_pipeline_status(stage),
                risk_level="low",
                summary=f"Imported from {source_name}.",
                latest_activity_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(student)
            db.flush()
        else:
            self._fill_student_from_import(student, record, program, stage, now)
        self._capture_student_source(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            source_name=source_name,
            source_type=source_type,
            source_detail=source_detail,
            batch_id=batch_id,
            raw_record=raw_record or {},
            now=now,
        )
        self._apply_assignment_rules(db, tenant_id, student, source, record, source_name, now)
        if external_id:
            self._ensure_student_identifier(db, tenant_id, student.id, external_id, source_name)
        if email:
            normalized_email = self._normalize_email(email)
            if prospect is None:
                prospect = self._find_duplicate_prospect(db, tenant_id, normalized_email, phone, external_id)
            if prospect is None:
                prospect = Prospect(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    first_name=first_name,
                    last_name=last_name,
                    email=normalized_email,
                    phone=phone,
                    population=population,
                    program_interest=program_interest,
                    term_interest=entry_term,
                    prior_institution=self._blank_to_none(record.get("highSchool")),
                    lifecycle_stage=stage,
                    status=self._status_for_stage(stage),
                    owner_user_id=actor_user_id,
                    source=source_name,
                    source_category=source_category,
                    campaign=source_detail,
                    consent_captured=False,
                    created_at=now,
                    updated_at=now,
                )
                db.add(prospect)
                db.flush()
            else:
                prospect.student_id = prospect.student_id or student.id
                prospect.first_name = first_name or prospect.first_name
                prospect.last_name = last_name or prospect.last_name
                prospect.phone = phone or prospect.phone
                prospect.population = population or prospect.population
                prospect.program_interest = program_interest or prospect.program_interest
                prospect.term_interest = entry_term or prospect.term_interest
                prospect.prior_institution = self._blank_to_none(record.get("highSchool")) or prospect.prior_institution
                prospect.lifecycle_stage = stage or prospect.lifecycle_stage
                prospect.status = self._status_for_stage(prospect.lifecycle_stage)
                prospect.source = source_name
                prospect.source_category = source_category
                prospect.campaign = source_detail or prospect.campaign
                prospect.updated_at = now
            db.add(
                ProspectSourceReference(
                    tenant_id=tenant_id,
                    prospect_id=prospect.id,
                    source=source_name,
                    source_category=source_category,
                    campaign=source_detail,
                    external_reference_id=external_id,
                    metadata_json={
                        "batchId": str(batch_id),
                        "entryTerm": entry_term,
                        "studentType": population,
                        "highSchoolGradYear": self._blank_to_none(record.get("highSchoolGradYear")),
                    },
                    captured_at=now,
                )
            )
        return "created" if created else "updated"

    def _map_import_row(self, raw_row: dict, mapping: dict[str, str]) -> dict[str, str | None]:
        record: dict[str, str | None] = {}
        for source_field, target_field in mapping.items():
            if not target_field or target_field == "ignore":
                continue
            value = raw_row.get(source_field)
            record[target_field] = str(value).strip() if value is not None and str(value).strip() else None
        return record

    def _validate_import_record(self, row_number: int, record: dict[str, str | None]) -> list[ProspectImportIssue]:
        issues: list[ProspectImportIssue] = []
        if not self._blank_to_none(record.get("firstName")):
            issues.append(self._issue(row_number, "error", "missing_first_name", "First name is required.", "firstName"))
        if not self._blank_to_none(record.get("lastName")):
            issues.append(self._issue(row_number, "error", "missing_last_name", "Last name is required.", "lastName"))
        email = self._blank_to_none(record.get("email"))
        phone = self._blank_to_none(record.get("mobilePhone") or record.get("phone"))
        external_id = self._blank_to_none(record.get("externalSourceId"))
        address = self._blank_to_none(record.get("addressLine1")) or self._blank_to_none(record.get("city")) or self._blank_to_none(record.get("state"))
        high_school_pair = self._blank_to_none(record.get("highSchool")) and self._blank_to_none(record.get("highSchoolGradYear"))
        if not any([email, phone, external_id, address, high_school_pair]):
            issues.append(self._issue(row_number, "error", "missing_contact", "At least one contact or identifying field is required."))
        if email and not self._is_valid_email(email):
            issues.append(self._issue(row_number, "error", "invalid_email", "Email address is invalid.", "email"))
        if phone and not self._is_valid_phone(phone):
            issues.append(self._issue(row_number, "warning", "invalid_phone", "Phone number looks invalid.", "mobilePhone"))
        if not self._blank_to_none(record.get("academicInterest")):
            issues.append(self._issue(row_number, "warning", "missing_academic_interest", "Academic interest is missing.", "academicInterest"))
        return issues

    def _find_import_matches(self, db: Session, tenant_id: UUID, record: dict[str, str | None]) -> tuple[Student | None, Prospect | None]:
        email = self._blank_to_none(record.get("email"))
        phone = self._normalized_phone(record.get("mobilePhone") or record.get("phone"))
        external_id = self._blank_to_none(record.get("externalSourceId"))
        student_predicates = []
        if email and self._is_valid_email(email):
            student_predicates.append(func.lower(Student.email) == email.lower())
        if phone:
            student_predicates.append(Student.phone == phone)
        if external_id:
            student_predicates.append(Student.external_student_id == external_id)
            linked_student_id = db.execute(
                select(StudentIdentifier.student_id).where(StudentIdentifier.tenant_id == tenant_id, StudentIdentifier.identifier_value == external_id).limit(1)
            ).scalar_one_or_none()
            if linked_student_id is not None:
                student_predicates.append(Student.id == linked_student_id)
        student = (
            db.execute(select(Student).where(Student.tenant_id == tenant_id, or_(*student_predicates)).limit(1)).scalar_one_or_none()
            if student_predicates
            else None
        )
        prospect = None
        if email and self._is_valid_email(email):
            prospect = self._find_duplicate_prospect(db, tenant_id, email.lower(), phone, external_id)
        return student, prospect

    def _serialize_import_source(self, source: ProspectImportSource) -> ProspectImportSourceResponse:
        return ProspectImportSourceResponse(
            id=str(source.id),
            name=source.name,
            sourceType=source.source_type,
            sourceCategory=source.source_category,
            defaultLifecycleStage=source.default_lifecycle_stage,
            defaultPopulation=source.default_population,
            defaultStudentType=source.default_student_type,
            defaultEntryTerm=source.default_entry_term,
            defaultMapping=dict(source.default_mapping_json or {}),
            isActive=source.is_active,
            createdAt=source.created_at.isoformat() if source.created_at else None,
        )

    def _serialize_import_batch(self, batch: ProspectImportBatch, source: ProspectImportSource | None, user: AppUser | None) -> ProspectImportBatchResponse:
        return ProspectImportBatchResponse(
            batchId=str(batch.id),
            filename=batch.filename,
            sourceId=str(source.id) if source else None,
            sourceName=source.name if source else None,
            uploadedBy=user.display_name if user else None,
            createdAt=batch.created_at.isoformat(),
            completedAt=batch.completed_at.isoformat() if batch.completed_at else None,
            status=batch.status,
            importMode=batch.import_mode,
            mapping=dict(batch.mapping_json or {}),
            counts=ProspectImportCounts(
                total=batch.total_rows,
                new=batch.new_count,
                matched=batch.matched_count,
                duplicates=batch.duplicate_count,
                errors=batch.error_count,
                created=batch.created_count,
                updated=batch.updated_count,
                skipped=batch.skipped_count,
            ),
        )

    def _serialize_template(self, template: ProspectImportTemplate) -> ProspectImportTemplateResponse:
        return ProspectImportTemplateResponse(
            id=str(template.id),
            name=template.name,
            sourceType=template.source_type,
            sourceDetail=template.source_detail,
            defaultLifecycleStage=template.default_lifecycle_stage,
            fieldMappings=dict(template.field_mappings_json or {}),
            normalizationRules=dict(template.normalization_rules_json or {}),
            dedupeRules=dict(template.dedupe_rules_json or {}),
            assignmentRules=dict(template.assignment_rules_json or {}),
            campaignRules=dict(template.campaign_rules_json or {}),
            validationRules=dict(template.validation_rules_json or {}),
            createdAt=template.created_at.isoformat() if template.created_at else None,
            updatedAt=template.updated_at.isoformat() if template.updated_at else None,
        )

    def _serialize_assignment_rule(self, rule: ProspectAssignmentRule) -> ProspectAssignmentRuleResponse:
        return ProspectAssignmentRuleResponse(
            id=str(rule.id),
            sourceId=str(rule.source_id) if rule.source_id else None,
            name=rule.name,
            field=rule.field,
            operator=rule.operator,
            value=rule.value,
            ownerUserId=str(rule.owner_user_id) if rule.owner_user_id else None,
            ownerTeamId=rule.owner_team_id,
            territory=rule.territory,
            priority=rule.priority,
            active=rule.active,
            createdAt=rule.created_at.isoformat() if rule.created_at else None,
        )

    def _serialize_schedule(self, schedule: ProspectScheduledImport) -> ProspectScheduledImportResponse:
        return ProspectScheduledImportResponse(
            id=str(schedule.id),
            sourceId=str(schedule.source_id) if schedule.source_id else None,
            mappingTemplateId=str(schedule.mapping_template_id) if schedule.mapping_template_id else None,
            deliveryMethod=schedule.delivery_method,
            inboundFolder=schedule.inbound_folder,
            schedule=schedule.schedule,
            importMode=schedule.import_mode,
            failureNotificationEmail=schedule.failure_notification_email,
            status=schedule.status,
            lastRunAt=schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            nextRunAt=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            createdAt=schedule.created_at.isoformat() if schedule.created_at else None,
        )

    def _serialize_api_credential(self, credential: ProspectApiCredential) -> ProspectApiCredentialResponse:
        return ProspectApiCredentialResponse(
            id=str(credential.id),
            sourceId=str(credential.source_id) if credential.source_id else None,
            name=credential.name,
            keyPrefix=credential.key_prefix,
            apiKey=None,
            active=credential.active,
            createdAt=credential.created_at.isoformat() if credential.created_at else None,
        )

    def _serialize_exception(self, exception: ProspectImportException) -> ProspectImportExceptionResponse:
        return ProspectImportExceptionResponse(
            id=str(exception.id),
            batchId=str(exception.batch_id) if exception.batch_id else None,
            rowId=str(exception.row_id) if exception.row_id else None,
            exceptionType=exception.exception_type,
            severity=exception.severity,
            status=exception.status,
            message=exception.message,
            assignedToUserId=str(exception.assigned_to_user_id) if exception.assigned_to_user_id else None,
            resolution=exception.resolution,
            metadata=dict(exception.metadata_json or {}),
            createdAt=exception.created_at.isoformat() if exception.created_at else None,
            resolvedAt=exception.resolved_at.isoformat() if exception.resolved_at else None,
        )

    def _resolve_import_source(self, db: Session, tenant_id: UUID, source_id: str | None) -> ProspectImportSource | None:
        if not source_id:
            return None
        try:
            source_uuid = UUID(source_id)
        except ValueError as exc:
            raise ProspectValidationError("Invalid source identifier.") from exc
        source = db.execute(
            select(ProspectImportSource).where(ProspectImportSource.tenant_id == tenant_id, ProspectImportSource.id == source_uuid).limit(1)
        ).scalar_one_or_none()
        if source is None:
            raise ProspectNotFoundError("Prospect import source not found.")
        return source

    def _clean_mapping(self, mapping: dict[str, str] | None) -> dict[str, str]:
        clean: dict[str, str] = {}
        for key, value in (mapping or {}).items():
            source_key = str(key).strip()
            target = str(value).strip() if value is not None else "ignore"
            if source_key and target in self.IMPORT_FIELDS:
                clean[source_key] = target
        return clean

    def _normalize_source_type(self, value: str | None) -> str:
        return (value or "manual_import").strip().lower().replace("-", "_").replace(" ", "_")

    def _stage_for_source(self, source_type: str | None) -> str:
        return self.SOURCE_STAGE_DEFAULTS.get(self._normalize_source_type(source_type), "prospect")

    def _normalize_lifecycle_stage(self, value: str | None, source: ProspectImportSource | None, source_type: str | None) -> str:
        stage = self._blank_to_none(value) or (source.default_lifecycle_stage if source else None) or self._stage_for_source(source_type)
        return stage.strip().lower().replace("-", "_").replace(" ", "_")

    def _status_for_stage(self, stage: str) -> str:
        if stage in {"application_started", "applicant_started"}:
            return "application_started"
        if stage in {"application_submitted", "applicant_submitted"}:
            return "fit_ready"
        if stage == "duplicate_candidate":
            return "duplicate_candidate"
        return "new"

    def _normalize_student_type(self, value: str | None) -> str | None:
        normalized = self._blank_to_none(value)
        if not normalized:
            return None
        key = normalized.lower().replace("-", " ").replace("_", " ")
        aliases = {
            "first year": "first_year",
            "first time freshman": "first_year",
            "freshman": "first_year",
            "transfer": "transfer",
            "graduate": "graduate",
            "adult learner": "adult_learner",
            "adult": "adult_learner",
            "online": "online",
            "international": "international",
            "dual enrollment": "dual_enrollment",
            "dual credit": "dual_enrollment",
            "non degree": "non_degree",
            "non-degree": "non_degree",
            "certificate": "certificate",
            "readmit": "readmit",
        }
        return aliases.get(key, key.replace(" ", "_"))

    def _normalize_entry_term(self, value: str | None) -> str | None:
        term = self._blank_to_none(value)
        if not term:
            return None
        compact = re.sub(r"[^A-Za-z0-9]", "", term).lower()
        match = re.fullmatch(r"(fa|fall|sp|spring|su|summer)(\d{2,4})", compact) or re.fullmatch(r"(\d{2,4})(fa|fall|sp|spring|su|summer)", compact)
        if match:
            first, second = match.groups()
            if first.isdigit():
                year_text, season_text = first, second
            else:
                season_text, year_text = first, second
            season = {"fa": "Fall", "fall": "Fall", "sp": "Spring", "spring": "Spring", "su": "Summer", "summer": "Summer"}.get(season_text, season_text.title())
            year = int(year_text)
            if year < 100:
                year += 2000
            return f"{season} {year}"
        return term

    def _normalize_program_interest(self, db: Session, tenant_id: UUID, value: str | None) -> tuple[str | None, Program | None]:
        interest = self._blank_to_none(value)
        if not interest:
            return None, None
        pattern = f"%{interest}%"
        program = db.execute(
            select(Program).where(Program.tenant_id == tenant_id, or_(Program.name.ilike(pattern), Program.program_code.ilike(pattern))).limit(1)
        ).scalar_one_or_none()
        return (program.program_code or program.name, program) if program else (interest, None)

    def _fill_student_from_import(self, student: Student, record: dict[str, str | None], program: Program | None, stage: str, now: datetime) -> None:
        student.first_name = self._blank_to_none(record.get("firstName")) or student.first_name
        student.last_name = self._blank_to_none(record.get("lastName")) or student.last_name
        student.preferred_name = student.preferred_name or student.first_name
        student.email = self._blank_to_none(record.get("email")) or student.email
        student.phone = self._normalized_phone(record.get("mobilePhone") or record.get("phone")) or student.phone
        student.city = self._blank_to_none(record.get("city")) or student.city
        student.state = self._blank_to_none(record.get("state")) or student.state
        student.external_student_id = self._blank_to_none(record.get("externalSourceId")) or student.external_student_id
        student.target_program_id = program.id if program else student.target_program_id
        student.current_stage = canonical_pipeline_status(stage) or student.current_stage
        student.latest_activity_at = now
        student.updated_at = now

    def _ensure_student_identifier(self, db: Session, tenant_id: UUID, student_id: UUID, external_id: str, source: str) -> None:
        existing = db.execute(
            select(StudentIdentifier).where(
                StudentIdentifier.tenant_id == tenant_id,
                StudentIdentifier.student_id == student_id,
                StudentIdentifier.identifier_value == external_id,
            ).limit(1)
        ).scalar_one_or_none()
        if existing is None:
            db.add(StudentIdentifier(tenant_id=tenant_id, student_id=student_id, identifier_type="external_source_id", identifier_value=external_id, source=source))

    def _capture_student_source(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        student_id: UUID,
        source_name: str,
        source_type: str,
        source_detail: str | None,
        batch_id: UUID,
        raw_record: dict,
        now: datetime,
    ) -> None:
        existing = db.execute(
            select(StudentSource)
            .where(
                StudentSource.tenant_id == tenant_id,
                StudentSource.student_id == student_id,
                StudentSource.source_name == source_name,
                StudentSource.source_batch_id == batch_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            existing_source = db.execute(
                select(StudentSource).where(StudentSource.tenant_id == tenant_id, StudentSource.student_id == student_id).limit(1)
            ).scalar_one_or_none()
            db.add(
                StudentSource(
                    tenant_id=tenant_id,
                    student_id=student_id,
                    source_name=source_name,
                    source_type=source_type,
                    source_detail=source_detail,
                    source_batch_id=batch_id,
                    primary_source=existing_source is None,
                    raw_source_json=raw_record,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        else:
            existing.last_seen_at = now
            existing.raw_source_json = raw_record

    def _apply_assignment_rules(
        self,
        db: Session,
        tenant_id: UUID,
        student: Student,
        source: ProspectImportSource | None,
        record: dict[str, str | None],
        source_name: str,
        now: datetime,
    ) -> None:
        rules = db.execute(
            select(ProspectAssignmentRule)
            .where(
                ProspectAssignmentRule.tenant_id == tenant_id,
                ProspectAssignmentRule.active.is_(True),
                or_(ProspectAssignmentRule.source_id.is_(None), ProspectAssignmentRule.source_id == (source.id if source else None)),
            )
            .order_by(ProspectAssignmentRule.priority.asc())
        ).scalars().all()
        matched_rule = next((rule for rule in rules if self._assignment_rule_matches(rule, record)), None)
        if matched_rule is None:
            return
        student.advisor_user_id = matched_rule.owner_user_id or student.advisor_user_id
        db.add(
            StudentAssignment(
                tenant_id=tenant_id,
                student_id=student.id,
                owner_user_id=matched_rule.owner_user_id,
                owner_team_id=matched_rule.owner_team_id,
                territory=matched_rule.territory,
                assignment_reason=f"Matched {matched_rule.name} from {source_name}.",
                assigned_by_rule_id=matched_rule.id,
                assigned_at=now,
            )
        )

    def _assignment_rule_matches(self, rule: ProspectAssignmentRule, record: dict[str, str | None]) -> bool:
        left = str(record.get(rule.field) or "").strip().lower()
        right = (rule.value or "").strip().lower()
        if rule.operator == "contains":
            return right in left
        if rule.operator == "starts_with":
            return left.startswith(right)
        if rule.operator == "in":
            return left in {part.strip().lower() for part in right.split(",")}
        return left == right

    def _match_confidence_from_preview(self, row: ProspectImportPreviewRow) -> int:
        if row.matchedStudentId or row.matchedProspectId:
            return 95 if row.email else 80
        if row.action == "duplicate":
            return 65
        return 0

    def _exception_type_for_issue(self, issue: ProspectImportIssue) -> str:
        if issue.code == "duplicate_in_file":
            return "possible_duplicate"
        if issue.code in {"missing_first_name", "missing_last_name", "missing_contact"}:
            return "missing_required_field"
        if issue.code in {"invalid_email", "invalid_phone"}:
            return "invalid_contact_info"
        if issue.code == "missing_academic_interest":
            return "program_mapping_unknown"
        return "import_validation"

    def _api_payload_to_row(self, payload: ProspectApiImportRequest) -> dict[str, str | None]:
        person = payload.person or {}
        interest = payload.interest or {}
        tracking = payload.tracking or {}
        return {
            "firstName": self._value_from(person, "firstName", "first_name", "givenName", "given_name"),
            "lastName": self._value_from(person, "lastName", "last_name", "familyName", "family_name"),
            "email": self._value_from(person, "email"),
            "mobilePhone": self._value_from(person, "mobilePhone", "phone", "phoneNumber"),
            "externalSourceId": self._value_from(tracking, "externalSourceId", "externalId", "id"),
            "academicInterest": self._value_from(interest, "academicInterest", "program", "major"),
            "entryTerm": self._value_from(interest, "entryTerm", "term"),
            "studentType": self._value_from(interest, "studentType", "population"),
            "lifecycleStage": payload.lifecycleStage,
            "sourceDetail": payload.sourceDetail,
            "highSchool": self._value_from(person, "highSchool"),
            "highSchoolGradYear": self._value_from(person, "highSchoolGradYear", "gradYear"),
            "city": self._value_from(person, "city"),
            "state": self._value_from(person, "state"),
        }

    def _value_from(self, payload: dict, *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _uuid_or_none(self, value: str | UUID | None) -> UUID | None:
        if value is None or value == "":
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _parse_uuid(self, value: str, label: str) -> UUID:
        try:
            return UUID(str(value).replace("pro_", ""))
        except ValueError as exc:
            raise ProspectValidationError(f"Invalid {label}.") from exc

    def _dedupe_key(self, record: dict[str, str | None]) -> str | None:
        email = self._blank_to_none(record.get("email"))
        if email:
            return f"email:{email.lower()}"
        phone = self._normalized_phone(record.get("mobilePhone") or record.get("phone"))
        if phone:
            return f"phone:{phone}"
        external_id = self._blank_to_none(record.get("externalSourceId"))
        if external_id:
            return f"external:{external_id.lower()}"
        return None

    def _normalized_phone(self, value: str | None) -> str | None:
        phone = self._blank_to_none(value)
        if not phone:
            return None
        digits = re.sub(r"\D+", "", phone)
        return digits if len(digits) >= 7 else phone

    def _is_valid_phone(self, value: str) -> bool:
        digits = re.sub(r"\D+", "", value or "")
        return 7 <= len(digits) <= 15

    def _is_valid_email(self, value: str) -> bool:
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (value or "").strip().lower()))

    def _issue(self, row_number: int, severity: str, code: str, message: str, field: str | None = None) -> ProspectImportIssue:
        return ProspectImportIssue(rowNumber=row_number, severity=severity, code=code, message=message, field=field)

    def _required_text(self, value: str | None, message: str) -> str:
        normalized = self._blank_to_none(value)
        if not normalized:
            raise ProspectValidationError(message)
        return normalized

    def _validate_inquiry(self, payload: ProspectInquiryRequest) -> None:
        required = [payload.firstName, payload.lastName, payload.email, payload.population, payload.source, payload.sourceCategory]
        if any(not value or not str(value).strip() for value in required):
            raise ProspectValidationError("First name, last name, email, population, source, and source category are required.")
        if not payload.consent:
            raise ProspectValidationError("Consent is required to create a follow-up-capable prospect.")
        self._normalize_email(payload.email)

    def _normalize_email(self, email: str) -> str:
        normalized = (email or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ProspectValidationError("A valid email is required.")
        return normalized

    def _normalize_population(self, population: str) -> str:
        normalized = (population or "").strip().lower().replace("-", "_").replace(" ", "_")
        return normalized or "prospect"

    def _initial_status(self, payload: ProspectInquiryRequest, duplicate_candidate: bool) -> str:
        if duplicate_candidate:
            return "duplicate_candidate"
        if payload.transcriptUploadId or payload.transcriptFilename:
            return "fit_ready"
        if payload.question and payload.question.strip():
            return "needs_follow_up"
        return "new"

    def _find_duplicate_prospect(self, db: Session, tenant_id: UUID, email: str, phone: str | None, external_reference_id: str | None) -> Prospect | None:
        predicates = [func.lower(Prospect.email) == email.lower()]
        if phone and phone.strip():
            predicates.append(Prospect.phone == phone.strip())
        if external_reference_id and external_reference_id.strip():
            source_ref = db.execute(
                select(ProspectSourceReference.prospect_id)
                .where(
                    ProspectSourceReference.tenant_id == tenant_id,
                    ProspectSourceReference.external_reference_id == external_reference_id.strip(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if source_ref is not None:
                predicates.append(Prospect.id == source_ref)
        return db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id, or_(*predicates)).limit(1)).scalar_one_or_none()

    def _find_duplicate_student(self, db: Session, tenant_id: UUID, email: str, phone: str | None) -> Student | None:
        predicates = [func.lower(Student.email) == email.lower()]
        if phone and phone.strip():
            predicates.append(Student.phone == phone.strip())
        return db.execute(select(Student).where(Student.tenant_id == tenant_id, or_(*predicates)).limit(1)).scalar_one_or_none()

    def _resolve_upload(self, db: Session, tenant_id: UUID, upload_id: str | None, email: str) -> ProspectTranscriptUpload | None:
        if not upload_id:
            return None
        upload = self._get_upload(db, tenant_id, upload_id)
        if upload.email.lower() != email.lower():
            raise ProspectValidationError("Transcript upload does not belong to this prospect email.")
        return upload

    def _get_upload(self, db: Session, tenant_id: UUID, upload_id: str) -> ProspectTranscriptUpload:
        resolved_id = self._parse_public_id(upload_id, "upl")
        upload = db.execute(
            select(ProspectTranscriptUpload).where(ProspectTranscriptUpload.tenant_id == tenant_id, ProspectTranscriptUpload.id == resolved_id).limit(1)
        ).scalar_one_or_none()
        if upload is None:
            raise ProspectNotFoundError("Transcript upload not found.")
        return upload

    def _get_prospect(self, db: Session, tenant_id: UUID, prospect_id: str) -> Prospect:
        resolved_id = self._parse_public_id(prospect_id, "pro")
        prospect = db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id, Prospect.id == resolved_id).limit(1)).scalar_one_or_none()
        if prospect is None:
            raise ProspectNotFoundError("Prospect not found.")
        return prospect

    def _parse_public_id(self, value: str, prefix: str) -> UUID:
        normalized = value.strip()
        if normalized.startswith(f"{prefix}_"):
            normalized = normalized[len(prefix) + 1 :]
        try:
            return UUID(normalized)
        except ValueError as exc:
            raise ProspectValidationError(f"Invalid {prefix} identifier.") from exc

    def _public_id(self, prefix: str, value: UUID) -> str:
        return f"{prefix}_{value}"

    def _upsert_fit_result(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        upload: ProspectTranscriptUpload | None,
    ) -> ProspectFitResult:
        now = datetime.now(timezone.utc)
        existing = self._latest_fit(db, tenant_id, prospect.id)
        program = prospect.program_interest or "Admissions fit preview"
        fit_score = self._fit_score(prospect, upload)
        transfer_credits = self._transfer_credits(prospect, upload)
        confidence = 0.82 if upload else 0.62
        missing_items = self._missing_items(prospect)
        signals = [signal.model_dump() for signal in self._signals(prospect)]
        if existing is None:
            existing = ProspectFitResult(tenant_id=tenant_id, prospect_id=prospect.id, program=program, fit_score=fit_score, confidence=confidence)
            db.add(existing)
        existing.transcript_upload_id = upload.id if upload else existing.transcript_upload_id
        existing.program = program
        existing.fit_score = fit_score
        existing.confidence = confidence
        existing.transfer_credits = transfer_credits
        existing.estimated_completion = "2.1 years" if prospect.population == "transfer" else "3.8 years"
        existing.scholarship_potential = "$8.5k-$11k" if fit_score >= 85 else ("$3k-$6k" if fit_score >= 70 else None)
        existing.missing_items_json = missing_items
        existing.signals_json = signals
        existing.computed_at = now
        return existing

    def _upsert_next_action(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        fit: ProspectFitResult,
        owner: AppUser | None,
    ) -> ProspectNextAction:
        code, label = self._next_action(prospect, fit)
        action = db.execute(
            select(ProspectNextAction).where(
                ProspectNextAction.tenant_id == tenant_id,
                ProspectNextAction.prospect_id == prospect.id,
                ProspectNextAction.status == "open",
            ).limit(1)
        ).scalar_one_or_none()
        if action is None:
            action = ProspectNextAction(tenant_id=tenant_id, prospect_id=prospect.id, status="open", created_at=datetime.now(timezone.utc))
            db.add(action)
        action.code = code
        action.label = label
        action.url = f"/apply?prospectId={self._public_id('pro', prospect.id)}" if code == "start_application" else None
        action.owner_user_id = prospect.owner_user_id or (owner.id if owner else None)
        return action

    def _next_action(self, prospect: Prospect, fit: ProspectFitResult) -> tuple[str, str]:
        if prospect.status == "duplicate_candidate":
            return ("resolve_duplicate", "Resolve duplicate")
        if prospect.question:
            return ("answer_question", "Answer prospect question")
        if fit.fit_score >= 80:
            return ("start_application", "Start application")
        if prospect.status in {"transcript_received", "fit_ready"}:
            return ("review_transfer_fit", "Review transfer fit")
        return ("upload_transcript", "Upload transcript")

    def _latest_fit(self, db: Session, tenant_id: UUID, prospect_id: UUID) -> ProspectFitResult | None:
        return db.execute(
            select(ProspectFitResult)
            .where(ProspectFitResult.tenant_id == tenant_id, ProspectFitResult.prospect_id == prospect_id)
            .order_by(ProspectFitResult.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_action(self, db: Session, tenant_id: UUID, prospect_id: UUID) -> ProspectNextAction | None:
        return db.execute(
            select(ProspectNextAction)
            .where(ProspectNextAction.tenant_id == tenant_id, ProspectNextAction.prospect_id == prospect_id, ProspectNextAction.status == "open")
            .order_by(ProspectNextAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _serialize_prospect(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        fit: ProspectFitResult | None,
        action: ProspectNextAction | None,
        upload: ProspectTranscriptUpload | None,
    ) -> ProspectRecordResponse:
        owner = db.execute(select(AppUser).where(AppUser.id == prospect.owner_user_id).limit(1)).scalar_one_or_none() if prospect.owner_user_id else None
        latest_upload = upload or db.execute(
            select(ProspectTranscriptUpload)
            .where(ProspectTranscriptUpload.tenant_id == tenant_id, ProspectTranscriptUpload.prospect_id == prospect.id)
            .order_by(ProspectTranscriptUpload.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return ProspectRecordResponse(
            prospectId=self._public_id("pro", prospect.id),
            studentId=(str(prospect.student_id) if prospect.student_id else None),
            studentName=f"{prospect.first_name} {prospect.last_name}".strip(),
            status=prospect.status,
            population=prospect.population,
            programInterest=prospect.program_interest,
            termInterest=prospect.term_interest,
            source=prospect.source,
            programFit=self._serialize_fit(fit),
            nextStep=self._serialize_next_step(action),
            counselor=ProspectCounselor(
                id=(str(owner.id) if owner else None),
                name=(owner.display_name if owner else "Admissions counselor"),
                email=(owner.email if owner else None),
            ),
            transcriptStatus=(latest_upload.status if latest_upload else None),
            missingItems=list(fit.missing_items_json or []) if fit else self._missing_items(prospect),
            signals=[ProspectSignal(**item) for item in list(fit.signals_json or [])] if fit else self._signals(prospect),
        )

    def _serialize_fit(self, fit: ProspectFitResult | None) -> ProspectProgramFit | None:
        if fit is None:
            return None
        return ProspectProgramFit(
            program=fit.program,
            fitScore=fit.fit_score,
            confidence=float(fit.confidence),
            transferCredits=fit.transfer_credits,
            estimatedCompletion=fit.estimated_completion,
            scholarshipPotential=fit.scholarship_potential,
        )

    def _serialize_next_step(self, action: ProspectNextAction | None) -> ProspectNextStep | None:
        if action is None:
            return None
        return ProspectNextStep(code=action.code, label=action.label, url=action.url)

    def _build_work_item(self, prospect: Prospect, action: ProspectNextAction, fit: ProspectFitResult | None, owner: AppUser | None) -> WorkTodayItemResponse:
        reason_code = self._reason_code(prospect, fit)
        queue_group = self._queue_group(prospect, reason_code)
        pipeline_status = canonical_pipeline_status(prospect.lifecycle_stage)
        return WorkTodayItemResponse(
            id=f"prospect_{prospect.id.hex[:12]}",
            studentId=self._public_id("pro", prospect.id),
            studentName=f"{prospect.first_name} {prospect.last_name}".strip(),
            population=prospect.population,
            stage=pipeline_status,
            pipelineStatus=pipeline_status,
            completionPercent=0,
            section="attention",
            priority="urgent" if queue_group in {"new_inquiries", "duplicate_candidate"} else "today",
            priorityScore=86 if fit and fit.fit_score >= 80 else 72,
            owner=WorkItemOwner(id=(str(owner.id) if owner else None), name=(owner.display_name if owner else "Unassigned")),
            reasonToAct=WorkItemReason(code=reason_code, label=self._reason_label(reason_code)),
            suggestedAction=WorkItemReason(code=action.code, label=action.label),
            readiness={"state": prospect.status, "label": self._title_case(prospect.status), "tone": "medium"},
            blockingItems=[],
            checklistSummary=None,
            program=prospect.program_interest or "Program interest pending",
            institutionGoal=prospect.prior_institution or "Prior institution pending",
            risk="Medium" if prospect.status == "duplicate_candidate" else "Low",
            lastActivity=self._relative_time(prospect.updated_at),
            nextAction=action.label,
            currentOwnerAgent=None,
            currentStage=prospect.lifecycle_stage,
            recommendedAgent="document_agent" if action.code in {"upload_transcript", "review_transfer_fit"} else "decision_agent",
            queueGroup=queue_group,
            updatedAt=prospect.updated_at.isoformat() if prospect.updated_at else None,
        )

    def _reason_code(self, prospect: Prospect, fit: ProspectFitResult | None) -> str:
        if prospect.status == "duplicate_candidate":
            return "duplicate_candidate"
        if prospect.question:
            return "question_needs_answer"
        if prospect.status in {"transcript_received", "fit_ready"} and fit and fit.fit_score >= 80:
            return "high_fit_prospect"
        if prospect.status in {"transcript_received", "fit_ready"}:
            return "transcript_first_lead"
        return "new_inquiry"

    def _queue_group(self, prospect: Prospect, reason_code: str) -> str:
        if reason_code == "duplicate_candidate":
            return "duplicate_candidate"
        if reason_code == "new_inquiry":
            return "new_inquiries"
        if reason_code == "question_needs_answer":
            return "no_first_touch"
        return "started_not_submitted"

    def _reason_label(self, reason_code: str) -> str:
        labels = {
            "new_inquiry": "New inquiry needs first touch",
            "transcript_first_lead": "Transcript-first lead needs review",
            "high_fit_prospect": "High-fit prospect is ready for application follow-up",
            "question_needs_answer": "Prospect question needs counselor response",
            "duplicate_candidate": "Duplicate candidate needs resolution",
        }
        return labels.get(reason_code, self._title_case(reason_code))

    def _create_student_from_prospect(self, db: Session, tenant_id: UUID, prospect: Prospect) -> Student:
        institution = self._ensure_institution(db, tenant_id, prospect.prior_institution)
        program = self._ensure_program(db, tenant_id, institution.id if institution else None, prospect.program_interest)
        student = Student(
            tenant_id=tenant_id,
            external_student_id=None,
            first_name=prospect.first_name,
            last_name=prospect.last_name,
            preferred_name=prospect.first_name,
            email=prospect.email,
            phone=prospect.phone,
            target_program_id=(program.id if program else None),
            target_institution_id=(institution.id if institution else None),
            advisor_user_id=prospect.owner_user_id,
            current_stage="applicant",
            risk_level="medium" if prospect.status == "duplicate_candidate" else "low",
            summary=f"Converted from prospect inquiry sourced by {prospect.source}.",
            latest_activity_at=datetime.now(timezone.utc),
        )
        db.add(student)
        db.flush()
        return student

    def _ensure_institution(self, db: Session, tenant_id: UUID, name: str | None) -> Institution | None:
        if not name:
            return None
        institution = db.execute(select(Institution).where(Institution.tenant_id == tenant_id, Institution.name == name).limit(1)).scalar_one_or_none()
        if institution is None:
            institution = Institution(tenant_id=tenant_id, name=name, country="US")
            db.add(institution)
            db.flush()
        return institution

    def _ensure_program(self, db: Session, tenant_id: UUID, institution_id: UUID | None, name: str | None) -> Program | None:
        if not name:
            return None
        program = db.execute(select(Program).where(Program.tenant_id == tenant_id, Program.institution_id == institution_id, Program.name == name).limit(1)).scalar_one_or_none()
        if program is None:
            program = Program(tenant_id=tenant_id, institution_id=institution_id, name=name, is_active=True)
            db.add(program)
            db.flush()
        return program

    def _default_owner(self, db: Session, tenant_id: UUID, actor_user_id: UUID) -> AppUser | None:
        return db.execute(
            select(AppUser)
            .where(AppUser.tenant_id == tenant_id, AppUser.id == actor_user_id, AppUser.is_active.is_(True))
            .limit(1)
        ).scalar_one_or_none() or db.execute(
            select(AppUser).where(AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True)).order_by(AppUser.created_at.asc()).limit(1)
        ).scalar_one_or_none()

    def _fit_score(self, prospect: Prospect, upload: ProspectTranscriptUpload | None) -> int:
        score = 68
        if prospect.population == "transfer":
            score += 12
        if upload is not None:
            score += 8
        if prospect.program_interest:
            score += 5
        return max(40, min(95, score))

    def _transfer_credits(self, prospect: Prospect, upload: ProspectTranscriptUpload | None) -> int | None:
        if prospect.population != "transfer":
            return None
        return 42 if upload else 24

    def _missing_items(self, prospect: Prospect) -> list[str]:
        items = ["Application form"]
        if prospect.status not in {"transcript_received", "fit_ready", "converted"}:
            items.insert(0, "Unofficial transcript")
        items.append("Official transcript")
        return items

    def _signals(self, prospect: Prospect) -> list[ProspectSignal]:
        signals = [
            ProspectSignal(label="Population", value=prospect.population),
            ProspectSignal(label="Source", value=prospect.source),
        ]
        if prospect.campaign:
            signals.append(ProspectSignal(label="Campaign", value=prospect.campaign))
        if prospect.prior_institution:
            signals.append(ProspectSignal(label="Prior institution", value=prospect.prior_institution))
        return signals

    def _store_upload(self, tenant_id: UUID, upload_id: UUID, filename: str, content: bytes) -> str:
        root = Path(settings.document_storage_dir).resolve() / "prospects" / str(tenant_id) / str(upload_id)
        root.mkdir(parents=True, exist_ok=True)
        target = root / filename
        target.write_bytes(content)
        return str(target)

    def _safe_filename(self, filename: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "transcript.pdf").strip("._")
        return cleaned or "transcript.pdf"

    def _upload_status_message(self, status: str) -> str:
        return {
            "received": "Transcript upload was received.",
            "processing": "Transcript processing is in progress.",
            "fit_ready": "Fit preview is ready.",
            "needs_review": "Transcript needs review.",
            "failed": "Transcript processing failed.",
        }.get(status, "Transcript upload status is available.")

    def _write_audit_event(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        action: str,
        metadata: dict,
    ) -> None:
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                category="ProspectPortal",
                action=action,
                success=True,
                error_message=None,
                payload_json={"metadata_json": metadata},
                correlation_id=None,
                source="ProspectService",
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _blank_to_none(self, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    def _title_case(self, value: str | None) -> str:
        return (value or "").replace("_", " ").title()

    def _relative_time(self, value: datetime | None) -> str:
        if value is None:
            return "Unknown"
        delta = datetime.now(timezone.utc) - value
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 3600:
            return f"{max(1, seconds // 60)} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} hours ago"
        return f"{seconds // 86400} days ago"
