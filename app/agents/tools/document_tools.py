from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.models import DocumentUpload
from app.db.session import get_session_factory
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.pipeline import TranscriptPipeline
from app.services.persistence import TranscriptPersistenceService


class TranscriptExtractionTool:
    action_type = "parse_transcript"
    tool_name = "parse_transcript"

    def __init__(self, pipeline: TranscriptPipeline | None = None) -> None:
        self.pipeline = pipeline or TranscriptPipeline()

    def parse_content(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        requested_document_type: str,
        use_bedrock: bool,
    ) -> dict[str, Any]:
        return self.pipeline.process(
            filename,
            content,
            content_type,
            requested_document_type=requested_document_type,
            use_bedrock=use_bedrock,
        )

    def parse_file(
        self,
        *,
        filename: str,
        file_path: str,
        content_type: str,
        requested_document_type: str,
        use_bedrock: bool,
    ) -> dict[str, Any]:
        return self.parse_content(
            filename=filename,
            content=Path(file_path).read_bytes(),
            content_type=content_type,
            requested_document_type=requested_document_type,
            use_bedrock=use_bedrock,
        )

    def as_strands_tool(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def parse_transcript(
            filename: str,
            content_type: str,
            requested_document_type: str,
            use_bedrock: bool,
            file_path: str,
        ) -> dict[str, Any]:
            """Parse a transcript file and return the API-shaped response payload."""
            return self.parse_file(
                filename=filename,
                file_path=file_path,
                content_type=content_type,
                requested_document_type=requested_document_type,
                use_bedrock=use_bedrock,
            )

        return parse_transcript


class DocumentPersistenceTool:
    complete_action_type = "persist_transcript"
    complete_tool_name = "complete_processing_upload"
    fail_action_type = "fail_transcript_processing"
    fail_tool_name = "fail_processing_upload"

    def __init__(self, persistence: TranscriptPersistenceService | None = None) -> None:
        self.persistence = persistence or TranscriptPersistenceService()

    def complete_processing_upload(
        self,
        *,
        transcript_id: str,
        response_payload: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, Any]:
        return self.persistence.complete_processing_upload(
            transcript_id=transcript_id,
            response_payload=response_payload,
            tenant_id=tenant_id,
        )

    def fail_processing_upload(
        self,
        *,
        transcript_id: str,
        tenant_id: str,
        error_message: str,
    ) -> dict[str, Any]:
        self.persistence.fail_processing_upload(
            transcript_id=transcript_id,
            tenant_id=tenant_id,
            error_message=error_message,
        )
        return {
            "transcriptId": transcript_id,
            "tenantId": tenant_id,
            "status": "failed",
            "error": error_message,
        }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def complete_processing_upload(
            transcript_id: str,
            response_payload: dict[str, Any],
            tenant_id: str,
        ) -> dict[str, Any]:
            """Persist a successful transcript processing result."""
            return self.complete_processing_upload(
                transcript_id=transcript_id,
                response_payload=response_payload,
                tenant_id=tenant_id,
            )

        @tool
        def fail_processing_upload(transcript_id: str, tenant_id: str, error_message: str) -> dict[str, Any]:
            """Mark a transcript processing upload as failed."""
            return self.fail_processing_upload(
                transcript_id=transcript_id,
                tenant_id=tenant_id,
                error_message=error_message,
            )

        return [complete_processing_upload, fail_processing_upload]


class DocumentContextTool:
    lookup_action_type = "lookup_student_context"
    lookup_tool_name = "lookup_student_context"
    link_action_type = "link_checklist_item"
    link_tool_name = "link_transcript_checklist_item"

    def __init__(self, session_factory=None, admissions_ops_service: AdmissionsOpsService | None = None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.admissions_ops_service = admissions_ops_service or AdmissionsOpsService(session_factory=self.session_factory)

    def lookup_student_context(self, *, tenant_id: str, student_id: str) -> dict[str, Any]:
        session_factory = self.session_factory()
        with session_factory() as session:
            context = self.admissions_ops_service._ensure_student_state(session, UUID(tenant_id), student_id)
            return {
                "studentId": str(context.student.id),
                "studentExternalId": context.student.external_student_id,
                "studentName": self._student_name(context.student),
                "checklistId": str(context.checklist.id),
                "checklistStatus": context.checklist.status,
                "completionPercent": context.checklist.completion_percent,
                "readinessState": context.readiness.readiness_state,
                "blockingItemCount": context.readiness.blocking_item_count,
                "items": [
                    {
                        "id": str(item.id),
                        "code": item.code,
                        "label": item.label,
                        "status": item.status,
                        "required": item.required,
                    }
                    for item in context.items
                ],
            }

    def link_transcript_checklist_item(
        self,
        *,
        tenant_id: str,
        student_id: str,
        document_id: str,
        match_confidence: float | None = None,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        session_factory = self.session_factory()
        with session_factory() as session:
            context = self.admissions_ops_service._ensure_student_state(session, tenant_uuid, student_id)
            document = self.admissions_ops_service._resolve_document(session, tenant_uuid, document_id)
            if document is None:
                return {"status": "skipped", "code": "document_not_found", "documentId": document_id}

            item = self._choose_transcript_item(context.items)
            if item is None:
                return {
                    "status": "skipped",
                    "code": "checklist_item_not_found",
                    "studentId": str(context.student.id),
                    "documentId": str(document.id),
                }

            now = datetime.now(timezone.utc)
            match_status = self._match_status(match_confidence)
            link = self.admissions_ops_service._get_document_checklist_link(
                session,
                tenant_id=tenant_uuid,
                document_id=document.id,
                checklist_item_id=item.id,
            )
            if link is None:
                from app.db.models import DocumentChecklistLink

                link = DocumentChecklistLink(
                    tenant_id=tenant_uuid,
                    student_id=context.student.id,
                    document_id=document.id,
                    checklist_item_id=item.id,
                    linked_by="agent",
                )
                session.add(link)

            link.match_confidence = self.admissions_ops_service._to_decimal(match_confidence)
            link.match_status = match_status
            link.linked_at = now
            link.linked_by = "agent"

            item.source_document_id = document.id
            item.source_confidence = self.admissions_ops_service._to_decimal(match_confidence)
            item.received_at = item.received_at or self._document_uploaded_at(document) or now
            item.updated_by_user_id = UUID(actor_user_id) if actor_user_id else None
            item.updated_by_system = actor_user_id is None
            item.updated_at = now
            if match_status == "auto_completed":
                item.status = "complete"
                item.needs_review = False
                item.completed_at = now
            elif match_status == "needs_review":
                item.status = "needs_review"
                item.needs_review = True
                item.completed_at = None
            else:
                item.status = "received"
                item.needs_review = False
                item.completed_at = None

            recalculated = self.admissions_ops_service._recalculate_student_state(
                session,
                tenant_uuid,
                context.student,
                context.checklist,
                context.items,
                actor_user_id=(UUID(actor_user_id) if actor_user_id else None),
                actor_type=("user" if actor_user_id else "agent"),
            )
            session.commit()
            return {
                "status": "completed",
                "code": "checklist_item_linked",
                "studentId": str(context.student.id),
                "documentId": str(document.id),
                "checklistItemId": str(item.id),
                "checklistItemCode": item.code,
                "matchStatus": match_status,
                "matchConfidence": match_confidence,
                "readinessState": recalculated.readiness.readiness_state,
                "completionPercent": recalculated.checklist.completion_percent,
            }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def lookup_student_context(tenant_id: str, student_id: str) -> dict[str, Any]:
            """Load the student checklist and readiness context for document processing."""
            return self.lookup_student_context(tenant_id=tenant_id, student_id=student_id)

        @tool
        def link_transcript_checklist_item(
            tenant_id: str,
            student_id: str,
            document_id: str,
            match_confidence: float | None = None,
            actor_user_id: str | None = None,
        ) -> dict[str, Any]:
            """Link a transcript document to the student's transcript checklist item."""
            return self.link_transcript_checklist_item(
                tenant_id=tenant_id,
                student_id=student_id,
                document_id=document_id,
                match_confidence=match_confidence,
                actor_user_id=actor_user_id,
            )

        return [lookup_student_context, link_transcript_checklist_item]

    def _choose_transcript_item(self, items):
        transcript_items = [item for item in items if "transcript" in (item.code or "").lower()]
        if not transcript_items:
            return None
        return sorted(transcript_items, key=lambda item: (item.status == "complete", item.required is False, item.label.lower()))[0]

    def _match_status(self, confidence: float | None) -> str:
        if confidence is not None and confidence >= 0.9:
            return "auto_completed"
        if confidence is not None:
            return "needs_review"
        return "received"

    def _student_name(self, student) -> str:
        parts = [student.preferred_name or student.first_name, student.last_name]
        return " ".join(part for part in parts if part) or student.external_student_id or str(student.id)

    def _document_uploaded_at(self, document: DocumentUpload):
        return getattr(document, "uploaded_at", None)
