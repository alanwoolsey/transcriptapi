from pydantic import BaseModel, Field


class ChecklistItemResponse(BaseModel):
    id: str
    code: str
    label: str
    required: bool
    status: str
    done: bool | None = None
    category: str | None = None
    receivedAt: str | None = None
    completedAt: str | None = None
    sourceDocumentId: str | None = None
    sourceConfidence: float | None = None
    updatedAt: str | None = None
    updatedBy: dict[str, str] | None = None


class ChecklistStatusUpdateRequest(BaseModel):
    status: str


class StudentReadinessResponse(BaseModel):
    studentId: str
    state: str | None = None
    label: str | None = None
    reason: str | None = None
    updatedAt: str | None = None
    readinessState: str
    reasonCode: str
    reasonLabel: str
    blockingItemCount: int
    trustBlocked: bool
    computedAt: str


class WorkSummaryCounts(BaseModel):
    needsAttention: int
    closeToCompletion: int
    readyForDecision: int
    exceptions: int


class WorkSummaryResponse(BaseModel):
    summary: WorkSummaryCounts


class WorkItemOwner(BaseModel):
    id: str | None = None
    name: str


class WorkItemReason(BaseModel):
    code: str
    label: str


class WorkBlockingItem(BaseModel):
    id: str
    code: str
    label: str
    status: str


class WorkChecklistSummary(BaseModel):
    totalRequired: int
    completedCount: int
    missingCount: int
    needsReviewCount: int
    oneItemAway: bool


class WorkItemResponse(BaseModel):
    id: str
    studentId: str
    studentName: str
    population: str
    stage: str
    completionPercent: int
    priority: str
    priorityScore: int | None = None
    section: str
    owner: WorkItemOwner
    reasonToAct: WorkItemReason
    suggestedAction: WorkItemReason
    readiness: dict | None = None
    blockingItems: list[WorkBlockingItem] = Field(default_factory=list)
    checklistSummary: WorkChecklistSummary
    fitScore: int
    depositLikelihood: int
    program: str
    institutionGoal: str
    risk: str
    lastActivity: str
    updatedAt: str | None = None


class WorkItemsResponse(BaseModel):
    items: list[WorkItemResponse] = Field(default_factory=list)
    page: int | None = None
    pageSize: int | None = None
    total: int


class WorkProjectionStatusResponse(BaseModel):
    projectedStudents: int
    totalStudents: int
    ready: bool
    lastProjectedAt: str | None = None
    remainingStudents: int = 0
    nextCursor: str | None = None


class WorkProjectionRebuildResponse(BaseModel):
    status: str
    detail: str
    processedStudents: int = 0
    nextCursor: str | None = None
    remainingStudents: int = 0


class LinkChecklistItemRequest(BaseModel):
    studentId: str
    checklistItemId: str
    matchConfidence: float | None = None
    matchStatus: str


class DocumentExceptionItem(BaseModel):
    id: str
    studentId: str | None = None
    studentName: str
    documentId: str | None = None
    transcriptId: str | None = None
    issueType: str
    label: str
    status: str
    createdAt: str
    transcriptStatus: str | None = None
    documentStatus: str | None = None
    parserConfidence: float | None = None
    reason: str | None = None
    suggestedAction: str | None = None
    latestRunStatus: str | None = None


class DocumentExceptionsResponse(BaseModel):
    items: list[DocumentExceptionItem] = Field(default_factory=list)
    total: int


class DocumentExceptionSummaryRun(BaseModel):
    runId: str
    agentName: str
    status: str
    triggerEvent: str | None = None
    error: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None


class DocumentExceptionSummaryAction(BaseModel):
    actionId: str
    actionType: str
    toolName: str | None = None
    status: str
    error: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)


class DocumentExceptionSummaryResponse(BaseModel):
    documentId: str
    transcriptId: str | None = None
    studentId: str | None = None
    studentName: str | None = None
    documentStatus: str | None = None
    transcriptStatus: str | None = None
    parserConfidence: float | None = None
    issueType: str
    issueLabel: str
    issueStatus: str
    suggestedAction: str
    failureCode: str | None = None
    failureMessage: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    latestRun: DocumentExceptionSummaryRun | None = None
    recentActions: list[DocumentExceptionSummaryAction] = Field(default_factory=list)
