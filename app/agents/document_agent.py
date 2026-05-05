from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.base import (
    AgentExecutionContext,
    AgentResultEnvelope,
    AgentRunResult,
    StrandsAgentFactory,
    log_agent_execution_event,
)
from app.agents.tools import DocumentContextTool, DocumentPersistenceTool, TranscriptExtractionTool
from app.services.agent_run_service import AgentRunService
from app.services.persistence import TranscriptPersistenceService
from app.services.pipeline import TranscriptPipeline


@dataclass(slots=True)
class DocumentAgentInput:
    filename: str
    content_type: str
    requested_document_type: str
    use_bedrock: bool
    transcript_id: str | None = None


class DocumentAgent:
    def __init__(
        self,
        *,
        factory: StrandsAgentFactory | None = None,
        agent_run_service: AgentRunService | None = None,
        pipeline: TranscriptPipeline | None = None,
        transcript_extraction_tool: TranscriptExtractionTool | None = None,
        document_persistence_tool: DocumentPersistenceTool | None = None,
        document_context_tool: DocumentContextTool | None = None,
        persistence: TranscriptPersistenceService | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.agent_run_service = agent_run_service or AgentRunService()
        self.transcript_extraction_tool = transcript_extraction_tool or TranscriptExtractionTool(pipeline=pipeline)
        self.document_persistence_tool = document_persistence_tool or DocumentPersistenceTool(persistence=persistence)
        self.document_context_tool = document_context_tool or DocumentContextTool()

    def _build_success_envelope(
        self,
        *,
        payload: DocumentAgentInput,
        context: AgentExecutionContext,
        result_payload: dict[str, Any],
        persistence_result: dict[str, Any] | None = None,
    ) -> AgentResultEnvelope:
        courses = len(result_payload.get("courses") or [])
        return AgentResultEnvelope(
            status="completed",
            code="transcript_processed",
            message="Transcript parsed successfully.",
            metrics={
                "courses": courses,
                "use_bedrock": payload.use_bedrock,
            },
            artifacts={
                "documentId": result_payload.get("documentId"),
                "transcriptId": payload.transcript_id or (str(context.transcript_id) if context.transcript_id else None),
                "persistence": persistence_result or {},
            },
        )

    def _build_failure_envelope(
        self,
        *,
        payload: DocumentAgentInput,
        context: AgentExecutionContext,
        error_message: str,
    ) -> AgentResultEnvelope:
        return AgentResultEnvelope(
            status="failed",
            code="document_processing_failed",
            message="Transcript processing failed.",
            error=error_message,
            metrics={
                "use_bedrock": payload.use_bedrock,
            },
            artifacts={
                "transcriptId": payload.transcript_id or (str(context.transcript_id) if context.transcript_id else None),
            },
        )

    def _build_parse_action_envelope(
        self,
        *,
        payload: DocumentAgentInput,
        context: AgentExecutionContext,
        result_payload: dict[str, Any],
    ) -> AgentResultEnvelope:
        return AgentResultEnvelope(
            status="completed",
            code="transcript_parsed",
            message="Transcript parsing completed.",
            metrics={
                "courses": len(result_payload.get("courses") or []),
                "use_bedrock": payload.use_bedrock,
            },
            artifacts={
                "documentId": result_payload.get("documentId"),
                "transcriptId": payload.transcript_id or (str(context.transcript_id) if context.transcript_id else None),
            },
        )

    def _build_persist_action_envelope(
        self,
        *,
        payload: DocumentAgentInput,
        context: AgentExecutionContext,
        persistence_result: dict[str, Any],
        course_count: int,
    ) -> AgentResultEnvelope:
        return AgentResultEnvelope(
            status="completed",
            code="transcript_persisted",
            message="Transcript persistence completed.",
            metrics={
                "courses": course_count,
            },
            artifacts={
                "transcriptId": payload.transcript_id or (str(context.transcript_id) if context.transcript_id else None),
                "persistence": persistence_result,
            },
        )

    def build(self):
        return self.factory.create(
            system_prompt=(
                "You are the Document Agent for an admissions system. "
                "Your job is to turn uploaded documents into structured student evidence, "
                "escalate exceptions clearly, and never invent transcript facts."
            ),
            tools=[
                self.transcript_extraction_tool.as_strands_tool(),
                *self.document_persistence_tool.as_strands_tools(),
                *self.document_context_tool.as_strands_tools(),
            ],
        )

    def reprocess_file(
        self,
        *,
        context: AgentExecutionContext,
        payload: DocumentAgentInput,
        file_path: str,
        existing_run_id: UUID | None = None,
    ) -> AgentRunResult:
        return self.reprocess_content(
            context=context,
            payload=payload,
            content=Path(file_path).read_bytes(),
            existing_run_id=existing_run_id,
        )

    def reprocess_content(
        self,
        *,
        context: AgentExecutionContext,
        payload: DocumentAgentInput,
        content: bytes,
        existing_run_id: UUID | None = None,
    ) -> AgentRunResult:
        result_payload: dict[str, Any] | None = None
        log_agent_execution_event(
            "agent_run_started",
            agent_name="document_agent",
            context=context,
            status="running",
            triggerEvent="manual_reprocess",
            filename=payload.filename,
        )

        if not self.agent_run_service.is_enabled():
            result_payload = self.transcript_extraction_tool.parse_content(
                filename=payload.filename,
                content=content,
                content_type=payload.content_type,
                requested_document_type=payload.requested_document_type,
                use_bedrock=payload.use_bedrock,
            )
            result_envelope = self._build_success_envelope(
                payload=payload,
                context=context,
                result_payload=result_payload,
            )
            log_agent_execution_event(
                "agent_run_completed",
                agent_name="document_agent",
                context=context,
                status="completed",
                result_code=result_envelope.code,
                metrics=result_envelope.metrics,
            )
            return AgentRunResult(
                agent_name="document_agent",
                status="completed",
                message=result_envelope.message,
                result=result_envelope,
                payload={
                    "context": asdict(context),
                    "input": asdict(payload),
                    "summary": asdict(result_envelope),
                    "result": result_payload,
                },
            )

        session_factory = self.agent_run_service.session_factory()
        with session_factory() as session:
            with session.begin():
                if existing_run_id is None:
                    run = self.agent_run_service.create_run(
                        session,
                        tenant_id=context.tenant_id,
                        student_id=context.student_id,
                        transcript_id=context.transcript_id,
                        actor_user_id=context.actor_user_id,
                        correlation_id=context.correlation_id,
                        agent_name="document_agent",
                        agent_type="document",
                        trigger_event="manual_reprocess",
                        status="running",
                        input_json={
                            "context": asdict(context),
                            "input": asdict(payload),
                        },
                    )
                else:
                    run = self.agent_run_service.get_run(session, tenant_id=context.tenant_id, run_id=existing_run_id)
                    if run is None:
                        raise ValueError("Agent run not found.")
                    run.status = "running"
                    run.started_at = run.started_at or datetime.now(timezone.utc)
                    run.completed_at = None
                    run.input_json = {
                        "context": asdict(context),
                        "input": asdict(payload),
                    }
                    run.error_message = None
                    session.flush()
                run_id = run.id
                log_agent_execution_event(
                    "agent_run_persisted",
                    agent_name="document_agent",
                    context=context,
                    status="running",
                    run_id=run_id,
                    triggerEvent="manual_reprocess",
                )

        try:
            result_payload = self.transcript_extraction_tool.parse_content(
                filename=payload.filename,
                content=content,
                content_type=payload.content_type,
                requested_document_type=payload.requested_document_type,
                use_bedrock=payload.use_bedrock,
            )
            parse_envelope = self._build_parse_action_envelope(
                payload=payload,
                context=context,
                result_payload=result_payload,
            )
            log_agent_execution_event(
                "agent_action_completed",
                agent_name="document_agent",
                context=context,
                status="completed",
                run_id=run_id,
                action_type=self.transcript_extraction_tool.action_type,
                tool_name=self.transcript_extraction_tool.tool_name,
                result_code=parse_envelope.code,
                metrics=parse_envelope.metrics,
            )
            with session_factory() as session:
                with session.begin():
                    self.agent_run_service.record_action(
                        session,
                        tenant_id=context.tenant_id,
                        run_id=run_id,
                        student_id=context.student_id,
                        transcript_id=context.transcript_id,
                        action_type=self.transcript_extraction_tool.action_type,
                        tool_name=self.transcript_extraction_tool.tool_name,
                        status="completed",
                        input_json={"filename": payload.filename, "content_type": payload.content_type},
                        output_json=asdict(parse_envelope),
                    )
            if payload.transcript_id is None:
                raise ValueError("A transcript_id is required for document reprocessing.")
            persistence_result = self.document_persistence_tool.complete_processing_upload(
                transcript_id=payload.transcript_id,
                response_payload=result_payload,
                tenant_id=str(context.tenant_id),
            )
            persist_envelope = self._build_persist_action_envelope(
                payload=payload,
                context=context,
                persistence_result=persistence_result,
                course_count=len(result_payload.get("courses") or []),
            )
            lookup_envelope, link_envelope = self._run_context_tools(
                context=context,
                result_payload=result_payload,
                run_id=run_id,
            )
            result_envelope = self._build_success_envelope(
                payload=payload,
                context=context,
                result_payload=result_payload,
                persistence_result=persistence_result,
            )
            log_agent_execution_event(
                "agent_action_completed",
                agent_name="document_agent",
                context=context,
                status="completed",
                run_id=run_id,
                action_type=self.document_persistence_tool.complete_action_type,
                tool_name=self.document_persistence_tool.complete_tool_name,
                result_code=persist_envelope.code,
                metrics=persist_envelope.metrics,
            )
            with session_factory() as session:
                with session.begin():
                    run = self.agent_run_service.get_run(session, tenant_id=context.tenant_id, run_id=run_id)
                    if run is None:
                        raise ValueError("Agent run not found.")
                    self.agent_run_service.record_action(
                        session,
                        tenant_id=context.tenant_id,
                        run_id=run.id,
                        student_id=context.student_id,
                        transcript_id=context.transcript_id,
                        action_type=self.document_persistence_tool.complete_action_type,
                        tool_name=self.document_persistence_tool.complete_tool_name,
                        status="completed",
                        input_json={"transcript_id": payload.transcript_id},
                        output_json=asdict(persist_envelope),
                    )
                    if lookup_envelope is not None:
                        self.agent_run_service.record_action(
                            session,
                            tenant_id=context.tenant_id,
                            run_id=run.id,
                            student_id=context.student_id,
                            transcript_id=context.transcript_id,
                            action_type=self.document_context_tool.lookup_action_type,
                            tool_name=self.document_context_tool.lookup_tool_name,
                            status=lookup_envelope.status,
                            input_json={"student_id": str(context.student_id) if context.student_id else None},
                            output_json=asdict(lookup_envelope),
                            error_message=lookup_envelope.error,
                        )
                    if link_envelope is not None:
                        self.agent_run_service.record_action(
                            session,
                            tenant_id=context.tenant_id,
                            run_id=run.id,
                            student_id=context.student_id,
                            transcript_id=context.transcript_id,
                            action_type=self.document_context_tool.link_action_type,
                            tool_name=self.document_context_tool.link_tool_name,
                            status=link_envelope.status,
                            input_json={"document_id": result_payload.get("documentId")},
                            output_json=asdict(link_envelope),
                            error_message=link_envelope.error,
                        )
                    self.agent_run_service.complete_run(
                        session,
                        run=run,
                        status="completed",
                        output_json=asdict(result_envelope),
                    )
                    if context.student_id is not None:
                        self.agent_run_service.upsert_student_state(
                            session,
                            tenant_id=context.tenant_id,
                            student_id=context.student_id,
                            current_owner_agent="document_agent",
                            state_json={"last_reprocess_file": payload.filename},
                            last_document_run_id=run.id,
                        )
            log_agent_execution_event(
                "agent_run_completed",
                agent_name="document_agent",
                context=context,
                status="completed",
                run_id=run_id,
                result_code=result_envelope.code,
                metrics=result_envelope.metrics,
            )
            return AgentRunResult(
                agent_name="document_agent",
                status="completed",
                message=result_envelope.message,
                result=result_envelope,
                payload={
                    "run_id": str(run_id),
                    "context": asdict(context),
                    "input": asdict(payload),
                    "summary": asdict(result_envelope),
                    "result": result_payload,
                    "persistence": persistence_result,
                },
            )
        except Exception as exc:
            result_envelope = self._build_failure_envelope(
                payload=payload,
                context=context,
                error_message=str(exc),
            )
            if payload.transcript_id is not None:
                try:
                    failure_persistence_result = self.document_persistence_tool.fail_processing_upload(
                        transcript_id=payload.transcript_id,
                        tenant_id=str(context.tenant_id),
                        error_message=str(exc),
                    )
                except Exception:
                    failure_persistence_result = {}
            else:
                failure_persistence_result = {}
            log_agent_execution_event(
                "agent_run_failed",
                agent_name="document_agent",
                context=context,
                status="failed",
                run_id=run_id,
                result_code=result_envelope.code,
                error=str(exc),
                metrics=result_envelope.metrics,
            )
            log_agent_execution_event(
                "agent_action_failed",
                agent_name="document_agent",
                context=context,
                status="failed",
                run_id=run_id,
                action_type=self.document_persistence_tool.fail_action_type,
                tool_name=self.document_persistence_tool.fail_tool_name,
                result_code=result_envelope.code,
                error=str(exc),
            )
            with session_factory() as session:
                with session.begin():
                    run = self.agent_run_service.get_run(session, tenant_id=context.tenant_id, run_id=run_id)
                    if run is not None:
                        self.agent_run_service.record_action(
                            session,
                            tenant_id=context.tenant_id,
                            run_id=run.id,
                            student_id=context.student_id,
                            transcript_id=context.transcript_id,
                            action_type=self.document_persistence_tool.fail_action_type,
                            tool_name=self.document_persistence_tool.fail_tool_name,
                            status="failed",
                            input_json={"filename": payload.filename, "content_type": payload.content_type},
                            output_json={
                                **asdict(result_envelope),
                                "artifacts": {
                                    **asdict(result_envelope)["artifacts"],
                                    "persistence": failure_persistence_result,
                                },
                            },
                            error_message=str(exc),
                        )
                        self.agent_run_service.complete_run(
                            session,
                            run=run,
                            status="failed",
                            output_json=asdict(result_envelope),
                            error_message=str(exc),
                        )
            raise

    def _run_context_tools(
        self,
        *,
        context: AgentExecutionContext,
        result_payload: dict[str, Any],
        run_id: UUID | None = None,
    ) -> tuple[AgentResultEnvelope | None, AgentResultEnvelope | None]:
        if context.student_id is None:
            skipped = AgentResultEnvelope(
                status="skipped",
                code="student_context_unavailable",
                message="Student context unavailable for checklist linking.",
                artifacts={"reason": "missing_student_id"},
            )
            return skipped, None

        try:
            student_context = self.document_context_tool.lookup_student_context(
                tenant_id=str(context.tenant_id),
                student_id=str(context.student_id),
            )
            lookup_envelope = AgentResultEnvelope(
                status="completed",
                code="student_context_loaded",
                message="Student context loaded.",
                metrics={
                    "checklistItemCount": len(student_context.get("items") or []),
                    "completionPercent": student_context.get("completionPercent"),
                    "blockingItemCount": student_context.get("blockingItemCount"),
                },
                artifacts=student_context,
            )
            log_agent_execution_event(
                "agent_action_completed",
                agent_name="document_agent",
                context=context,
                status="completed",
                run_id=run_id,
                action_type=self.document_context_tool.lookup_action_type,
                tool_name=self.document_context_tool.lookup_tool_name,
                result_code=lookup_envelope.code,
                metrics=lookup_envelope.metrics,
            )
        except Exception as exc:
            lookup_envelope = AgentResultEnvelope(
                status="failed",
                code="student_context_lookup_failed",
                message="Student context lookup failed.",
                error=str(exc),
            )
            log_agent_execution_event(
                "agent_action_failed",
                agent_name="document_agent",
                context=context,
                status="failed",
                run_id=run_id,
                action_type=self.document_context_tool.lookup_action_type,
                tool_name=self.document_context_tool.lookup_tool_name,
                result_code=lookup_envelope.code,
                error=str(exc),
            )
            return lookup_envelope, None

        document_id = result_payload.get("documentId")
        if not document_id:
            link_envelope = AgentResultEnvelope(
                status="skipped",
                code="document_context_unavailable",
                message="Document id unavailable for checklist linking.",
                artifacts={"reason": "missing_document_id"},
            )
            return lookup_envelope, link_envelope

        try:
            link_result = self.document_context_tool.link_transcript_checklist_item(
                tenant_id=str(context.tenant_id),
                student_id=str(context.student_id),
                document_id=str(document_id),
                match_confidence=self._confidence_from_result(result_payload),
                actor_user_id=str(context.actor_user_id) if context.actor_user_id else None,
            )
            link_status = str(link_result.get("status") or "completed")
            link_envelope = AgentResultEnvelope(
                status=link_status,
                code=str(link_result.get("code") or "checklist_item_linked"),
                message="Checklist item linked." if link_status == "completed" else "Checklist linking skipped.",
                metrics={
                    "completionPercent": link_result.get("completionPercent"),
                    "matchConfidence": link_result.get("matchConfidence"),
                },
                artifacts=link_result,
            )
            log_agent_execution_event(
                "agent_action_completed",
                agent_name="document_agent",
                context=context,
                status=link_status,
                run_id=run_id,
                action_type=self.document_context_tool.link_action_type,
                tool_name=self.document_context_tool.link_tool_name,
                result_code=link_envelope.code,
                metrics=link_envelope.metrics,
            )
            return lookup_envelope, link_envelope
        except Exception as exc:
            link_envelope = AgentResultEnvelope(
                status="failed",
                code="checklist_link_failed",
                message="Checklist linking failed.",
                error=str(exc),
            )
            log_agent_execution_event(
                "agent_action_failed",
                agent_name="document_agent",
                context=context,
                status="failed",
                run_id=run_id,
                action_type=self.document_context_tool.link_action_type,
                tool_name=self.document_context_tool.link_tool_name,
                result_code=link_envelope.code,
                error=str(exc),
            )
            return lookup_envelope, link_envelope

    def _confidence_from_result(self, result_payload: dict[str, Any]) -> float | None:
        for key in ("parserConfidence", "confidence", "overallConfidence"):
            value = result_payload.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None
