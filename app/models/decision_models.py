from pydantic import BaseModel


class DecisionWorkbenchItem(BaseModel):
    id: str
    student: str
    program: str
    fit: int
    creditEstimate: int
    readiness: str
    reason: str


class CreateDecisionRequest(BaseModel):
    student: str
    program: str
    fit: int
    creditEstimate: int
    readiness: str
    reason: str


class DecisionAssignedUser(BaseModel):
    id: str
    name: str


class DecisionStudentSummary(BaseModel):
    id: str | None = None
    name: str
    email: str | None = None
    externalId: str | None = None


class DecisionProgramSummary(BaseModel):
    name: str


class DecisionRecommendation(BaseModel):
    fit: int
    creditEstimate: int
    reason: str


class DecisionEvidence(BaseModel):
    institution: str | None = None
    gpa: float | None = None
    creditsEarned: float | None = None
    parserConfidence: float | None = None
    documentCount: int


class DecisionTrustSignal(BaseModel):
    id: str
    severity: str
    signal: str
    evidence: str
    status: str


class DecisionTrustSummary(BaseModel):
    status: str
    signals: list[DecisionTrustSignal]


class DecisionNoteItem(BaseModel):
    id: str
    body: str
    authorName: str
    createdAt: str


class DecisionTimelineEvent(BaseModel):
    id: str
    type: str
    label: str
    detail: str | None = None
    actorName: str | None = None
    at: str


class DecisionDetailResponse(BaseModel):
    id: str
    status: str
    readiness: str
    assignedTo: DecisionAssignedUser | None = None
    queue: str | None = None
    createdAt: str
    updatedAt: str
    student: DecisionStudentSummary
    program: DecisionProgramSummary
    recommendation: DecisionRecommendation
    evidence: DecisionEvidence
    trust: DecisionTrustSummary
    notes: list[DecisionNoteItem]
    timelinePreview: list[DecisionTimelineEvent]


class DecisionStatusUpdateRequest(BaseModel):
    status: str


class DecisionStatusUpdateResponse(BaseModel):
    id: str
    status: str
    updatedAt: str


class DecisionAssignRequest(BaseModel):
    assignee_user_id: str
    queue: str | None = None


class DecisionAssignResponse(BaseModel):
    id: str
    assignedTo: DecisionAssignedUser | None = None
    updatedAt: str


class DecisionNoteCreateRequest(BaseModel):
    body: str
