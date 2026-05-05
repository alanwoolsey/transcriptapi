from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from app.core.config import settings


@dataclass(slots=True)
class AgentExecutionContext:
    tenant_id: UUID
    student_id: UUID | None = None
    transcript_id: UUID | None = None
    actor_user_id: UUID | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunResult:
    agent_name: str
    status: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


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
