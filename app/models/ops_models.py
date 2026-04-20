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


class StudentChecklistResponse(BaseModel):
    studentId: str
    population: str
    completionPercent: int
    oneItemAway: bool
    status: str
    items: list[ChecklistItemResponse] = Field(default_factory=list)


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
    issueType: str
    label: str
    status: str
    createdAt: str


class DocumentExceptionsResponse(BaseModel):
    items: list[DocumentExceptionItem] = Field(default_factory=list)
    total: int
