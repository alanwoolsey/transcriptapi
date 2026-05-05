from pydantic import BaseModel, Field


class PaginatedResponse(BaseModel):
    page: int = 1
    pageSize: int = 25
    total: int = 0


class SimpleUserRef(BaseModel):
    id: str | None = None
    name: str


class IncompleteQueueItem(BaseModel):
    id: str
    studentId: str
    studentName: str
    population: str
    program: str
    missingItemsCount: int
    missingItems: list[str] = Field(default_factory=list)
    completedItemsCount: int = 0
    totalRequired: int = 0
    lastActivityAt: str | None = None
    daysStalled: int = 0
    closestToComplete: bool = False
    assignedOwner: SimpleUserRef | None = None
    suggestedNextAction: str
    readinessState: str
    priorityScore: int | None = None


class IncompleteQueueResponse(PaginatedResponse):
    items: list[IncompleteQueueItem] = Field(default_factory=list)


class ReviewReadyItem(BaseModel):
    id: str
    studentId: str
    studentName: str
    population: str
    program: str
    transferCredits: float | int
    assignedReviewer: SimpleUserRef | None = None
    daysWaiting: int = 0
    reviewSlaHours: int = 24
    completedItemsCount: int = 0
    totalRequired: int = 0


class ReviewReadyResponse(BaseModel):
    items: list[ReviewReadyItem] = Field(default_factory=list)


class StudentMatchRef(BaseModel):
    studentId: str | None = None
    studentName: str | None = None


class DocumentQueueItem(BaseModel):
    id: str
    documentType: str
    studentMatch: StudentMatchRef | None = None
    confidence: float | None = None
    uploadSource: str
    status: str
    trustFlag: bool = False
    receivedAt: str | None = None


class DocumentsQueueResponse(BaseModel):
    items: list[DocumentQueueItem] = Field(default_factory=list)


class ActionResponse(BaseModel):
    success: bool = True
    status: str | None = None
    detail: str | None = None


class DocumentReprocessStartResponse(ActionResponse):
    documentId: str
    documentUploadId: str
    transcriptId: str
    agentRunId: str


class AgentRunResultResponse(BaseModel):
    status: str
    code: str
    message: str
    error: str | None = None
    metrics: dict = Field(default_factory=dict)
    artifacts: dict = Field(default_factory=dict)


class AgentRunStatusResponse(BaseModel):
    runId: str
    agentName: str
    agentType: str | None = None
    status: str
    triggerEvent: str | None = None
    studentId: str | None = None
    transcriptId: str | None = None
    actorUserId: str | None = None
    correlationId: str | None = None
    error: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    result: AgentRunResultResponse | None = None


class AgentRunActionItemResponse(BaseModel):
    actionId: str
    actionType: str
    toolName: str | None = None
    status: str
    studentId: str | None = None
    transcriptId: str | None = None
    error: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    result: AgentRunResultResponse | None = None
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)


class AgentRunActionsResponse(BaseModel):
    runId: str
    items: list[AgentRunActionItemResponse] = Field(default_factory=list)


class YieldQueueItem(BaseModel):
    studentId: str
    studentName: str
    program: str
    admitDate: str | None = None
    depositStatus: str
    yieldScore: int
    lastActivityAt: str | None = None
    milestoneCompletion: float = 0.0
    assignedCounselor: SimpleUserRef | None = None
    nextStep: str | None = None


class YieldQueueResponse(BaseModel):
    items: list[YieldQueueItem] = Field(default_factory=list)


class MeltQueueItem(BaseModel):
    studentId: str
    studentName: str
    program: str
    depositDate: str | None = None
    meltRisk: int
    missingMilestones: list[str] = Field(default_factory=list)
    lastOutreachAt: str | None = None
    owner: SimpleUserRef | None = None


class MeltQueueResponse(BaseModel):
    items: list[MeltQueueItem] = Field(default_factory=list)


class HandoffSummary(BaseModel):
    healthy: int = 0
    failed: int = 0
    blocked: int = 0


class HandoffItem(BaseModel):
    studentId: str
    studentName: str
    office: str
    status: str
    lastAttemptAt: str | None = None
    error: str | None = None


class HandoffResponse(BaseModel):
    summary: HandoffSummary
    items: list[HandoffItem] = Field(default_factory=list)


class ReportingOverviewResponse(BaseModel):
    incompleteToCompleteConversion: float = 0.0
    averageDaysToComplete: float = 0.0
    averageDaysCompleteToDecision: float = 0.0
    autoIndexSuccessRate: float = 0.0
    admitToDepositConversion: float = 0.0
    meltRate: float = 0.0


class AdminUserItem(BaseModel):
    userId: str
    email: str | None = None
    displayName: str
    status: str
    baseRole: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    sensitivityTiers: list[str] = Field(default_factory=list)
    scopes: dict[str, list[str]] = Field(default_factory=dict)
    lastLoginAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    tempPassword: str | None = None


class AdminUsersResponse(PaginatedResponse):
    items: list[AdminUserItem] = Field(default_factory=list)


class AdminRoleItem(BaseModel):
    key: str
    label: str
    description: str | None = None
    active: bool = True


class AdminRolesResponse(BaseModel):
    items: list[AdminRoleItem] = Field(default_factory=list)


class AdminPermissionItem(BaseModel):
    key: str
    label: str
    description: str | None = None
    category: str


class AdminPermissionsResponse(BaseModel):
    items: list[AdminPermissionItem] = Field(default_factory=list)


class SensitivityTierItem(BaseModel):
    key: str
    label: str
    description: str | None = None


class SensitivityTiersResponse(BaseModel):
    items: list[SensitivityTierItem] = Field(default_factory=list)


class AdminScopeOptionsResponse(BaseModel):
    campuses: list[str] = Field(default_factory=list)
    territories: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    studentPopulations: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class AdminUserScopes(BaseModel):
    campuses: list[str] = Field(default_factory=list)
    territories: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    studentPopulations: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class AdminUserCreateRequest(BaseModel):
    email: str
    displayName: str
    baseRole: str | None = None
    roles: list[str] = Field(default_factory=list)
    sensitivityTiers: list[str] = Field(default_factory=list)
    scopes: AdminUserScopes = Field(default_factory=AdminUserScopes)
    sendInvite: bool = True


class AdminUserUpdateRequest(BaseModel):
    displayName: str | None = None
    baseRole: str | None = None
    roles: list[str] | None = None
    sensitivityTiers: list[str] | None = None
    scopes: AdminUserScopes | None = None
    status: str | None = None


class AdminUserReassignRequest(BaseModel):
    targetUserId: str
    objects: list[str] = Field(default_factory=list)


class AdminChecklistTemplateItem(BaseModel):
    code: str
    label: str
    required: bool = True
    sortOrder: int = 0
    documentType: str | None = None
    reviewRequiredDefault: bool = False


class AdminChecklistTemplatePayload(BaseModel):
    name: str
    population: str
    active: bool = True
    items: list[AdminChecklistTemplateItem] = Field(default_factory=list)


class AdminChecklistTemplateRecord(BaseModel):
    id: str
    name: str
    population: str
    active: bool
    version: int
    items: list[AdminChecklistTemplateItem] = Field(default_factory=list)


class AdminChecklistTemplatesResponse(BaseModel):
    items: list[AdminChecklistTemplateRecord] = Field(default_factory=list)


class AdminConfigPayload(BaseModel):
    items: list[dict] = Field(default_factory=list)
