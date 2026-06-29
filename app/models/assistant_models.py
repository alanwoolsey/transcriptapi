from typing import Any

from pydantic import BaseModel, Field


class AssistantActiveEntity(BaseModel):
    type: str | None = None
    id: str | None = None


class AssistantAttachment(BaseModel):
    fileName: str
    contentType: str = "application/octet-stream"
    sizeBytes: int = 0
    dataBase64: str | None = None


class AssistantChatRequest(BaseModel):
    message: str
    route: str | None = None
    activeEntity: AssistantActiveEntity | None = None
    uiState: dict[str, Any] = Field(default_factory=dict)
    conversationSummary: str | None = None
    attachments: list[AssistantAttachment] = Field(default_factory=list)


class AssistantCitation(BaseModel):
    id: str
    label: str
    type: str
    route: str | None = None


class AssistantRetrievalInfo(BaseModel):
    intent: str
    confidence: float
    toolsUsed: list[str] = Field(default_factory=list)
    inputContextTokens: int = 0
    cacheHit: bool = False
    sources: list[str] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    response: str
    policyStatus: str = "allowed"
    guardrails: list[str] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)
    auditId: str = ""
    model: str = ""
    latencyMs: int | None = None
    inputTokens: int | None = None
    outputTokens: int | None = None
    requiredApproval: bool = False
    retrieval: AssistantRetrievalInfo


class AssistantDocumentClassificationRequest(BaseModel):
    fileName: str
    contentType: str = "application/octet-stream"
    sizeBytes: int = 0
    dataBase64: str
    classificationOptions: list[str] = Field(default_factory=list)


class AssistantDocumentClassificationResponse(BaseModel):
    documentType: str
    confidence: float = 0.0
    rationale: str = ""
    policyStatus: str = "allowed"
    guardrails: list[str] = Field(default_factory=list)
    auditId: str = ""
