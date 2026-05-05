from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.base import AgentExecutionContext, AgentRunResult, StrandsAgentFactory
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
        persistence: TranscriptPersistenceService | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.agent_run_service = agent_run_service or AgentRunService()
        self.pipeline = pipeline or TranscriptPipeline()
        self.persistence = persistence or TranscriptPersistenceService()

    def build(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def parse_transcript(filename: str, content_type: str, requested_document_type: str, use_bedrock: bool, file_path: str) -> dict[str, Any]:
            """Parse a transcript file and return the API-shaped response payload."""
            content = Path(file_path).read_bytes()
            return self.pipeline.process(
                filename,
                content,
                content_type,
                requested_document_type=requested_document_type,
                use_bedrock=use_bedrock,
            )

        return self.factory.create(
            system_prompt=(
                "You are the Document Agent for an admissions system. "
                "Your job is to turn uploaded documents into structured student evidence, "
                "escalate exceptions clearly, and never invent transcript facts."
            ),
            tools=[parse_transcript],
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

        if not self.agent_run_service.is_enabled():
            result_payload = self.pipeline.process(
                payload.filename,
                content,
                payload.content_type,
                requested_document_type=payload.requested_document_type,
                use_bedrock=payload.use_bedrock,
            )
            return AgentRunResult(
                agent_name="document_agent",
                status="completed",
                message="Transcript parsed successfully.",
                payload={
                    "context": asdict(context),
                    "input": asdict(payload),
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

        try:
            result_payload = self.pipeline.process(
                payload.filename,
                content,
                payload.content_type,
                requested_document_type=payload.requested_document_type,
                use_bedrock=payload.use_bedrock,
            )
            with session_factory() as session:
                with session.begin():
                    self.agent_run_service.record_action(
                        session,
                        tenant_id=context.tenant_id,
                        run_id=run_id,
                        student_id=context.student_id,
                        transcript_id=context.transcript_id,
                        action_type="parse_transcript",
                        tool_name="parse_transcript",
                        status="completed",
                        input_json={"filename": payload.filename, "content_type": payload.content_type},
                        output_json={"document_id": result_payload.get("documentId"), "courses": len(result_payload.get("courses") or [])},
                    )
            if payload.transcript_id is None:
                raise ValueError("A transcript_id is required for document reprocessing.")
            persistence_result = self.persistence.complete_processing_upload(
                transcript_id=payload.transcript_id,
                response_payload=result_payload,
                tenant_id=str(context.tenant_id),
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
                        action_type="persist_transcript",
                        tool_name="complete_processing_upload",
                        status="completed",
                        input_json={"transcript_id": payload.transcript_id},
                        output_json=persistence_result,
                    )
                    self.agent_run_service.complete_run(
                        session,
                        run=run,
                        status="completed",
                        output_json={
                            "document_id": result_payload.get("documentId"),
                            "courses": len(result_payload.get("courses") or []),
                            "persistence": persistence_result,
                        },
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
            return AgentRunResult(
                agent_name="document_agent",
                status="completed",
                message="Transcript parsed successfully.",
                payload={
                    "run_id": str(run_id),
                    "context": asdict(context),
                    "input": asdict(payload),
                    "result": result_payload,
                    "persistence": persistence_result,
                },
            )
        except Exception as exc:
            if payload.transcript_id is not None:
                try:
                    self.persistence.fail_processing_upload(
                        transcript_id=payload.transcript_id,
                        tenant_id=str(context.tenant_id),
                        error_message=str(exc),
                    )
                except Exception:
                    pass
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
                            action_type="document_reprocess",
                            tool_name="document_agent",
                            status="failed",
                            input_json={"filename": payload.filename, "content_type": payload.content_type},
                            output_json={},
                            error_message=str(exc),
                        )
                        self.agent_run_service.complete_run(
                            session,
                            run=run,
                            status="failed",
                            output_json={},
                            error_message=str(exc),
                        )
            raise
