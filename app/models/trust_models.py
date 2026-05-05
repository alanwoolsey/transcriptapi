from pydantic import BaseModel, Field

from app.models.operations_models import AgentRunActionItemResponse, AgentRunStatusResponse


class TrustCaseSummary(BaseModel):
    riskLevel: str
    summary: str
    rationale: str
    recommendedAction: str
    signals: list[str] = Field(default_factory=list)


class TrustCaseItem(BaseModel):
    id: str
    transcriptId: str | None = None
    studentId: str | None = None
    student: str
    documentId: str | None = None
    document: str | None = None
    severity: str
    signal: str
    evidence: str
    status: str
    trustBlocked: bool = False
    latestRunStatus: str | None = None
    latestResultCode: str | None = None
    owner: dict[str, str] | None = None
    openedAt: str | None = None
    summary: TrustCaseSummary | None = None


class TrustCaseDetailsResponse(BaseModel):
    transcriptId: str
    studentId: str | None = None
    student: str
    document: str | None = None
    severity: str
    signal: str
    evidence: str
    status: str
    trustBlocked: bool = False
    owner: dict[str, str] | None = None
    openedAt: str | None = None
    summary: TrustCaseSummary | None = None
    latestRun: AgentRunStatusResponse | None = None
    actions: list[AgentRunActionItemResponse] = Field(default_factory=list)


class TrustCaseActionRequest(BaseModel):
    note: str | None = None


class TrustCaseAssignRequest(BaseModel):
    userId: str
    note: str | None = None
