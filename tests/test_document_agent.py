from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.base import AgentExecutionContext
from app.agents.document_agent import DocumentAgent, DocumentAgentInput
from app.agents.tools import DocumentPersistenceTool, TranscriptExtractionTool


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self

    def flush(self):
        return None


class _FakeAgentRunService:
    def __init__(self) -> None:
        self.runs: dict = {}
        self.actions: list[dict] = []
        self.student_states: list[dict] = []
        self._session_factory = lambda: _FakeSession()

    def session_factory(self):
        return self._session_factory

    def is_enabled(self) -> bool:
        return True

    def create_run(self, session, **kwargs):
        run = SimpleNamespace(
            id=uuid4(),
            tenant_id=kwargs["tenant_id"],
            student_id=kwargs.get("student_id"),
            transcript_id=kwargs.get("transcript_id"),
            actor_user_id=kwargs.get("actor_user_id"),
            parent_run_id=kwargs.get("parent_run_id"),
            agent_name=kwargs["agent_name"],
            agent_type=kwargs.get("agent_type"),
            trigger_event=kwargs.get("trigger_event"),
            status=kwargs["status"],
            input_json=kwargs["input_json"],
            output_json={},
            correlation_id=kwargs.get("correlation_id"),
            error_message=None,
            started_at=object(),
            completed_at=None,
            updated_at=None,
        )
        self.runs[run.id] = run
        return run

    def get_run(self, session, *, tenant_id, run_id):
        run = self.runs.get(run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        return run

    def record_action(self, session, **kwargs):
        self.actions.append(kwargs)
        return kwargs

    def complete_run(self, session, *, run, status, output_json=None, error_message=None):
        run.status = status
        run.output_json = output_json or {}
        run.error_message = error_message
        run.completed_at = object()
        return run

    def upsert_student_state(self, session, **kwargs):
        self.student_states.append(kwargs)
        return kwargs


class _FakePersistence:
    def __init__(self) -> None:
        self.completed_calls: list[dict] = []
        self.failed_calls: list[dict] = []

    def complete_processing_upload(self, *, transcript_id, response_payload, tenant_id):
        payload = {
            "transcriptId": transcript_id,
            "status": "completed",
            "tenantId": tenant_id,
            "courses": len(response_payload.get("courses") or []),
        }
        self.completed_calls.append(payload)
        return payload

    def fail_processing_upload(self, *, transcript_id, tenant_id, error_message):
        self.failed_calls.append(
            {
                "transcriptId": transcript_id,
                "tenantId": tenant_id,
                "error": error_message,
            }
        )


class _FakeDocumentContextTool:
    lookup_action_type = "lookup_student_context"
    lookup_tool_name = "lookup_student_context"
    link_action_type = "link_checklist_item"
    link_tool_name = "link_transcript_checklist_item"

    def __init__(self) -> None:
        self.lookup_calls: list[dict] = []
        self.link_calls: list[dict] = []

    def as_strands_tools(self):
        return []

    def lookup_student_context(self, *, tenant_id, student_id):
        self.lookup_calls.append({"tenantId": tenant_id, "studentId": student_id})
        return {
            "studentId": student_id,
            "checklistId": "checklist-1",
            "checklistStatus": "incomplete",
            "completionPercent": 75,
            "readinessState": "blocked",
            "blockingItemCount": 1,
            "items": [
                {
                    "id": "item-1",
                    "code": "official_transcript",
                    "label": "Official transcript",
                    "status": "missing",
                    "required": True,
                }
            ],
        }

    def link_transcript_checklist_item(self, *, tenant_id, student_id, document_id, match_confidence=None, actor_user_id=None):
        self.link_calls.append(
            {
                "tenantId": tenant_id,
                "studentId": student_id,
                "documentId": document_id,
                "matchConfidence": match_confidence,
                "actorUserId": actor_user_id,
            }
        )
        return {
            "status": "completed",
            "code": "checklist_item_linked",
            "studentId": student_id,
            "documentId": document_id,
            "checklistItemId": "item-1",
            "checklistItemCode": "official_transcript",
            "matchStatus": "auto_completed",
            "matchConfidence": match_confidence,
            "completionPercent": 100,
        }


class _SuccessPipeline:
    def process(self, filename, content, content_type, *, requested_document_type, use_bedrock):
        return {
            "documentId": "doc-1",
            "parserConfidence": 0.96,
            "courses": [{"courseName": "English 9"}, {"courseName": "Algebra I"}],
            "requestedDocumentType": requested_document_type,
            "usedBedrock": use_bedrock,
            "filename": filename,
        }


class _FailingPipeline:
    def process(self, filename, content, content_type, *, requested_document_type, use_bedrock):
        raise ValueError("No courses were extracted from transcript.")


def test_transcript_extraction_tool_wraps_pipeline_contract():
    tool = TranscriptExtractionTool(pipeline=_SuccessPipeline())

    result = tool.parse_content(
        filename="sample.pdf",
        content=b"%PDF-1.4 test",
        content_type="application/pdf",
        requested_document_type="official_transcript",
        use_bedrock=True,
    )

    assert result["documentId"] == "doc-1"
    assert result["filename"] == "sample.pdf"
    assert result["requestedDocumentType"] == "official_transcript"
    assert result["usedBedrock"] is True
    assert len(result["courses"]) == 2


def test_document_persistence_tool_wraps_completion_and_failure_contracts():
    persistence = _FakePersistence()
    tool = DocumentPersistenceTool(persistence=persistence)
    response_payload = {"courses": [{"courseName": "English 9"}]}

    completed = tool.complete_processing_upload(
        transcript_id="transcript-1",
        response_payload=response_payload,
        tenant_id="tenant-1",
    )
    failed = tool.fail_processing_upload(
        transcript_id="transcript-2",
        tenant_id="tenant-1",
        error_message="No courses were extracted from transcript.",
    )

    assert completed["status"] == "completed"
    assert completed["courses"] == 1
    assert persistence.completed_calls[0]["transcriptId"] == "transcript-1"
    assert failed == {
        "transcriptId": "transcript-2",
        "tenantId": "tenant-1",
        "status": "failed",
        "error": "No courses were extracted from transcript.",
    }
    assert persistence.failed_calls[0]["transcriptId"] == "transcript-2"


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        tenant_id=uuid4(),
        student_id=uuid4(),
        transcript_id=uuid4(),
        actor_user_id=uuid4(),
        correlation_id="document-reprocess:test",
    )


def _payload(context: AgentExecutionContext) -> DocumentAgentInput:
    return DocumentAgentInput(
        filename="replacement.pdf",
        content_type="application/pdf",
        requested_document_type="official_transcript",
        use_bedrock=False,
        transcript_id=str(context.transcript_id),
    )


def test_document_agent_success_returns_structured_result_and_records_run():
    context = _context()
    payload = _payload(context)
    agent_run_service = _FakeAgentRunService()
    persistence = _FakePersistence()
    context_tool = _FakeDocumentContextTool()
    agent = DocumentAgent(
        agent_run_service=agent_run_service,
        pipeline=_SuccessPipeline(),
        persistence=persistence,
        document_context_tool=context_tool,
    )

    result = agent.reprocess_content(
        context=context,
        payload=payload,
        content=b"%PDF-1.4 test",
    )

    assert result.status == "completed"
    assert result.result is not None
    assert result.result.code == "transcript_processed"
    assert result.result.metrics["courses"] == 2
    assert result.payload["summary"]["code"] == "transcript_processed"
    assert persistence.completed_calls[0]["status"] == "completed"

    run = next(iter(agent_run_service.runs.values()))
    assert run.status == "completed"
    assert run.output_json["code"] == "transcript_processed"
    assert run.output_json["artifacts"]["documentId"] == "doc-1"
    assert [entry["action_type"] for entry in agent_run_service.actions] == [
        "parse_transcript",
        "persist_transcript",
        "lookup_student_context",
        "link_checklist_item",
    ]
    assert agent_run_service.actions[0]["output_json"]["code"] == "transcript_parsed"
    assert agent_run_service.actions[1]["output_json"]["code"] == "transcript_persisted"
    assert agent_run_service.actions[2]["output_json"]["code"] == "student_context_loaded"
    assert agent_run_service.actions[3]["output_json"]["code"] == "checklist_item_linked"
    assert context_tool.link_calls[0]["matchConfidence"] == 0.96


def test_document_agent_failure_records_structured_failure_and_marks_processing_failed():
    context = _context()
    payload = _payload(context)
    agent_run_service = _FakeAgentRunService()
    persistence = _FakePersistence()
    agent = DocumentAgent(
        agent_run_service=agent_run_service,
        pipeline=_FailingPipeline(),
        persistence=persistence,
        document_context_tool=_FakeDocumentContextTool(),
    )

    with pytest.raises(ValueError, match="No courses were extracted from transcript."):
        agent.reprocess_content(
            context=context,
            payload=payload,
            content=b"%PDF-1.4 test",
        )

    run = next(iter(agent_run_service.runs.values()))
    assert run.status == "failed"
    assert run.output_json["code"] == "document_processing_failed"
    assert run.output_json["error"] == "No courses were extracted from transcript."
    assert persistence.failed_calls[0]["error"] == "No courses were extracted from transcript."
    assert agent_run_service.actions[-1]["status"] == "failed"
    assert agent_run_service.actions[-1]["action_type"] == "fail_transcript_processing"
    assert agent_run_service.actions[-1]["tool_name"] == "fail_processing_upload"
    assert agent_run_service.actions[-1]["output_json"]["code"] == "document_processing_failed"
    assert agent_run_service.actions[-1]["output_json"]["artifacts"]["persistence"]["status"] == "failed"


def test_document_agent_recovery_reuses_existing_run_and_clears_previous_error():
    context = _context()
    payload = _payload(context)
    agent_run_service = _FakeAgentRunService()
    persistence = _FakePersistence()
    failing_agent = DocumentAgent(
        agent_run_service=agent_run_service,
        pipeline=_FailingPipeline(),
        persistence=persistence,
        document_context_tool=_FakeDocumentContextTool(),
    )

    with pytest.raises(ValueError):
        failing_agent.reprocess_content(
            context=context,
            payload=payload,
            content=b"%PDF-1.4 test",
        )

    existing_run = next(iter(agent_run_service.runs.values()))
    assert existing_run.status == "failed"

    recovering_agent = DocumentAgent(
        agent_run_service=agent_run_service,
        pipeline=_SuccessPipeline(),
        persistence=persistence,
        document_context_tool=_FakeDocumentContextTool(),
    )
    result = recovering_agent.reprocess_content(
        context=context,
        payload=payload,
        content=b"%PDF-1.4 test",
        existing_run_id=existing_run.id,
    )

    assert result.status == "completed"
    assert result.payload["run_id"] == str(existing_run.id)
    assert existing_run.status == "completed"
    assert existing_run.error_message is None
    assert existing_run.output_json["code"] == "transcript_processed"
    assert persistence.completed_calls[-1]["status"] == "completed"
