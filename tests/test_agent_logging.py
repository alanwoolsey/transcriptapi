from __future__ import annotations

import json
import logging
from uuid import uuid4

from app.agents.base import AgentExecutionContext, log_agent_execution_event


def test_agent_execution_logging_includes_correlation_and_run_context(caplog):
    tenant_id = uuid4()
    student_id = uuid4()
    transcript_id = uuid4()
    actor_user_id = uuid4()
    run_id = uuid4()
    context = AgentExecutionContext(
        tenant_id=tenant_id,
        student_id=student_id,
        transcript_id=transcript_id,
        actor_user_id=actor_user_id,
        correlation_id="document-reprocess:test",
    )

    with caplog.at_level(logging.INFO, logger="app.agents.execution"):
        log_agent_execution_event(
            "agent_action_completed",
            agent_name="document_agent",
            context=context,
            status="completed",
            run_id=run_id,
            action_type="parse_transcript",
            tool_name="parse_transcript",
            result_code="transcript_parsed",
            metrics={"courses": 2},
        )

    payload = json.loads(caplog.records[0].message)
    assert payload == {
        "actionType": "parse_transcript",
        "actorUserId": str(actor_user_id),
        "agentName": "document_agent",
        "correlationId": "document-reprocess:test",
        "event": "agent_action_completed",
        "metrics": {"courses": 2},
        "resultCode": "transcript_parsed",
        "runId": str(run_id),
        "status": "completed",
        "studentId": str(student_id),
        "tenantId": str(tenant_id),
        "toolName": "parse_transcript",
        "transcriptId": str(transcript_id),
    }
