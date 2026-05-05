from pydantic import BaseModel, Field

from app.models.operations_models import AgentRunActionItemResponse, AgentRunStatusResponse


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


class WorkTodayAgentSummary(BaseModel):
    runId: str | None = None
    status: str | None = None
    resultCode: str | None = None
    updatedAt: str | None = None


class WorkTodayItemResponse(BaseModel):
    id: str
    studentId: str
    studentName: str
    section: str
    priority: str
    priorityScore: int | None = None
    owner: WorkItemOwner
    reasonToAct: WorkItemReason
    suggestedAction: WorkItemReason
    currentOwnerAgent: str | None = None
    currentStage: str | None = None
    recommendedAgent: str | None = None
    queueGroup: str | None = None
    documentAgent: WorkTodayAgentSummary | None = None
    trustAgent: WorkTodayAgentSummary | None = None
    decisionAgent: WorkTodayAgentSummary | None = None
    updatedAt: str | None = None


class WorkTodayResponse(BaseModel):
    items: list[WorkTodayItemResponse] = Field(default_factory=list)
    total: int


class WorkTodayGroupRouteHint(BaseModel):
    nextAgent: str
    reason: str
    actionLabel: str


class WorkTodayGroupResponse(BaseModel):
    key: str
    label: str
    total: int
    routeHint: WorkTodayGroupRouteHint | None = None
    items: list[WorkTodayItemResponse] = Field(default_factory=list)


class WorkTodayBoardResponse(BaseModel):
    groups: list[WorkTodayGroupResponse] = Field(default_factory=list)
    total: int


class WorkTodayOrchestrationResponse(BaseModel):
    agentRunId: str
    board: WorkTodayBoardResponse
    run: AgentRunStatusResponse
    actions: list[AgentRunActionItemResponse] = Field(default_factory=list)


class WorkTodayRouteRequest(BaseModel):
    nextAgent: str
    note: str | None = None


class WorkTodayRouteResponse(BaseModel):
    studentId: str
    nextAgent: str
    currentStage: str
    detail: str


class WorkTodayRecommendationResponse(BaseModel):
    studentId: str
    recommendedAgent: str
    currentOwnerAgent: str | None = None
    currentStage: str | None = None
    reason: str


class WorkProjectionStatusResponse(BaseModel):
    projectedStudents: int
    totalStudents: int
    ready: bool
    lastProjectedAt: str | None = None
    remainingStudents: int = 0
    nextCursor: str | None = None
    currentJob: dict | None = None


class WorkProjectionJobResponse(BaseModel):
    jobId: str
    status: str
    resetRequested: bool
    chunkSize: int
    processedStudents: int
    remainingStudents: int
    nextCursor: str | None = None
    error: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class WorkProjectionJobsResponse(BaseModel):
    items: list[WorkProjectionJobResponse] = Field(default_factory=list)


class WorkProjectionRebuildResponse(BaseModel):
    status: str
    detail: str
    jobId: str | None = None
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


class DocumentAgentRunFailureResponse(BaseModel):
    code: str | None = None
    message: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DocumentAgentRunDetailsResponse(BaseModel):
    documentId: str
    transcriptId: str | None = None
    studentId: str | None = None
    studentName: str | None = None
    documentStatus: str | None = None
    transcriptStatus: str | None = None
    parserConfidence: float | None = None
    latestFailure: DocumentAgentRunFailureResponse | None = None
    run: AgentRunStatusResponse | None = None
    actions: list[AgentRunActionItemResponse] = Field(default_factory=list)
