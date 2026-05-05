from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Callable
from uuid import UUID

from app.core.config import settings

agent_execution_logger = logging.getLogger("app.agents.execution")


@dataclass(slots=True)
class AgentExecutionContext:
    tenant_id: UUID
    student_id: UUID | None = None
    transcript_id: UUID | None = None
    actor_user_id: UUID | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResultEnvelope:
    status: str
    code: str
    message: str
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunResult:
    agent_name: str
    status: str
    message: str
    result: AgentResultEnvelope | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


def log_agent_execution_event(
    event: str,
    *,
    agent_name: str,
    context: AgentExecutionContext,
    status: str | None = None,
    run_id: UUID | str | None = None,
    action_type: str | None = None,
    tool_name: str | None = None,
    result_code: str | None = None,
    error: str | None = None,
    **metadata: Any,
) -> None:
    record = {
        "event": event,
        "agentName": agent_name,
        "tenantId": str(context.tenant_id),
        "studentId": str(context.student_id) if context.student_id is not None else None,
        "transcriptId": str(context.transcript_id) if context.transcript_id is not None else None,
        "actorUserId": str(context.actor_user_id) if context.actor_user_id is not None else None,
        "correlationId": context.correlation_id,
        "runId": str(run_id) if run_id is not None else None,
        "status": status,
        "actionType": action_type,
        "toolName": tool_name,
        "resultCode": result_code,
        "error": error,
    }
    record.update({key: _json_safe(value) for key, value in metadata.items() if value is not None})
    payload = {key: value for key, value in record.items() if value is not None}
    log_method = agent_execution_logger.error if status == "failed" or error else agent_execution_logger.info
    log_method(json.dumps(payload, sort_keys=True))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


class StrandsAgentFactory:
    def __init__(self) -> None:
        self._agent_cls = None
        self._bedrock_model_cls = None

    def create(self, *, system_prompt: str, tools: list[Callable[..., Any]], temperature: float | None = None):
        agent_cls, bedrock_model_cls = self._load_strands_types()
        model = bedrock_model_cls(
            model_id=settings.strands_model_id,
            temperature=settings.strands_temperature if temperature is None else temperature,
            max_tokens=settings.strands_max_tokens,
            region_name=settings.aws_region,
        )
        return agent_cls(model=model, system_prompt=system_prompt, tools=tools)

    def _load_strands_types(self):
        if self._agent_cls is None or self._bedrock_model_cls is None:
            try:
                from strands import Agent
                from strands.models import BedrockModel
            except ImportError as exc:
                raise RuntimeError(
                    "Strands Agents is not installed. Install requirements before using app.agents."
                ) from exc
            self._agent_cls = Agent
            self._bedrock_model_cls = BedrockModel
        return self._agent_cls, self._bedrock_model_cls
