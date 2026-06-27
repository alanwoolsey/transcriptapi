from __future__ import annotations

from pydantic import BaseModel, Field


class ProspectInquiryRequest(BaseModel):
    firstName: str
    lastName: str
    email: str
    phone: str | None = None
    population: str
    programInterest: str | None = None
    termInterest: str | None = None
    priorInstitution: str | None = None
    source: str = "manual_entry"
    sourceCategory: str = "direct"
    campaign: str | None = None
    consent: bool
    question: str | None = None
    transcriptUploadId: str | None = None
    transcriptFilename: str | None = None
    externalReferenceId: str | None = None


class ProspectProgramFit(BaseModel):
    program: str
    fitScore: int
    confidence: float
    transferCredits: int | None = None
    estimatedCompletion: str | None = None
    scholarshipPotential: str | None = None


class ProspectNextStep(BaseModel):
    code: str
    label: str
    url: str | None = None


class ProspectCounselor(BaseModel):
    id: str | None = None
    name: str
    email: str | None = None


class ProspectSignal(BaseModel):
    label: str
    value: str


class ProspectRecordResponse(BaseModel):
    prospectId: str
    studentId: str | None = None
    studentName: str
    status: str
    population: str
    programInterest: str | None = None
    termInterest: str | None = None
    source: str
    programFit: ProspectProgramFit | None = None
    nextStep: ProspectNextStep | None = None
    counselor: ProspectCounselor | None = None
    transcriptStatus: str | None = None
    missingItems: list[str] = Field(default_factory=list)
    signals: list[ProspectSignal] = Field(default_factory=list)


class ProspectInquiryResponse(BaseModel):
    prospect: ProspectRecordResponse


class ProspectUploadResponse(BaseModel):
    uploadId: str
    status: str
    filename: str


class ProspectUploadStatusResponse(BaseModel):
    uploadId: str
    status: str
    processingRunId: str | None = None
    message: str


class ProspectFitResponse(BaseModel):
    programFit: ProspectProgramFit | None = None
    missingItems: list[str] = Field(default_factory=list)
    signals: list[ProspectSignal] = Field(default_factory=list)
    nextStep: ProspectNextStep | None = None


class ProspectConvertResponse(BaseModel):
    studentId: str
    prospectId: str
    status: str


class ProspectImportSourceCreateRequest(BaseModel):
    name: str
    sourceType: str
    sourceCategory: str = "recruitment"
    defaultLifecycleStage: str | None = None
    defaultPopulation: str | None = None
    defaultStudentType: str | None = None
    defaultEntryTerm: str | None = None
    defaultMapping: dict[str, str] = Field(default_factory=dict)


class ProspectImportSourceResponse(BaseModel):
    id: str
    name: str
    sourceType: str
    sourceCategory: str
    defaultLifecycleStage: str | None = None
    defaultPopulation: str | None = None
    defaultStudentType: str | None = None
    defaultEntryTerm: str | None = None
    defaultMapping: dict[str, str] = Field(default_factory=dict)
    isActive: bool
    createdAt: str | None = None


class ProspectImportSourceListResponse(BaseModel):
    sources: list[ProspectImportSourceResponse] = Field(default_factory=list)


class ProspectImportRowsRequest(BaseModel):
    sourceId: str | None = None
    filename: str = "prospects.csv"
    sourceName: str | None = None
    sourceType: str | None = None
    sourceCategory: str | None = None
    sourceDetail: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict)
    rows: list[dict[str, str | int | float | None]] = Field(default_factory=list)
    importMode: str = "create_or_update"


class ProspectImportIssue(BaseModel):
    rowNumber: int
    severity: str
    code: str
    message: str
    field: str | None = None


class ProspectImportCounts(BaseModel):
    total: int = 0
    new: int = 0
    matched: int = 0
    duplicates: int = 0
    missingContact: int = 0
    invalidEmail: int = 0
    invalidPhone: int = 0
    missingAcademicInterest: int = 0
    errors: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class ProspectImportPreviewRow(BaseModel):
    rowNumber: int
    action: str
    firstName: str | None = None
    lastName: str | None = None
    email: str | None = None
    phone: str | None = None
    academicInterest: str | None = None
    entryTerm: str | None = None
    lifecycleStage: str | None = None
    matchedStudentId: str | None = None
    matchedProspectId: str | None = None
    issues: list[ProspectImportIssue] = Field(default_factory=list)


class ProspectImportPreviewResponse(BaseModel):
    counts: ProspectImportCounts
    rows: list[ProspectImportPreviewRow] = Field(default_factory=list)
    issues: list[ProspectImportIssue] = Field(default_factory=list)


class ProspectImportConfirmResponse(BaseModel):
    batchId: str
    counts: ProspectImportCounts
    status: str
    issues: list[ProspectImportIssue] = Field(default_factory=list)


class ProspectImportBatchResponse(BaseModel):
    batchId: str
    filename: str
    sourceId: str | None = None
    sourceName: str | None = None
    uploadedBy: str | None = None
    createdAt: str
    completedAt: str | None = None
    status: str
    importMode: str
    mapping: dict[str, str] = Field(default_factory=dict)
    counts: ProspectImportCounts


class ProspectImportBatchListResponse(BaseModel):
    imports: list[ProspectImportBatchResponse] = Field(default_factory=list)


class ProspectImportTemplateRequest(BaseModel):
    name: str
    sourceType: str = "manual_import"
    sourceDetail: str | None = None
    defaultLifecycleStage: str | None = None
    fieldMappings: dict[str, str] = Field(default_factory=dict)
    normalizationRules: dict[str, object] = Field(default_factory=dict)
    dedupeRules: dict[str, object] = Field(default_factory=dict)
    assignmentRules: dict[str, object] = Field(default_factory=dict)
    campaignRules: dict[str, object] = Field(default_factory=dict)
    validationRules: dict[str, object] = Field(default_factory=dict)


class ProspectImportTemplateResponse(ProspectImportTemplateRequest):
    id: str
    createdAt: str | None = None
    updatedAt: str | None = None


class ProspectImportTemplateListResponse(BaseModel):
    templates: list[ProspectImportTemplateResponse] = Field(default_factory=list)


class ProspectAssignmentRuleRequest(BaseModel):
    sourceId: str | None = None
    name: str
    field: str
    operator: str = "equals"
    value: str
    ownerUserId: str | None = None
    ownerTeamId: str | None = None
    territory: str | None = None
    priority: int = 100
    active: bool = True


class ProspectAssignmentRuleResponse(ProspectAssignmentRuleRequest):
    id: str
    createdAt: str | None = None


class ProspectAssignmentRuleListResponse(BaseModel):
    rules: list[ProspectAssignmentRuleResponse] = Field(default_factory=list)


class ProspectScheduledImportRequest(BaseModel):
    sourceId: str | None = None
    mappingTemplateId: str | None = None
    deliveryMethod: str = "sftp"
    inboundFolder: str | None = None
    schedule: str | None = None
    importMode: str = "create_or_update"
    failureNotificationEmail: str | None = None
    status: str = "active"


class ProspectScheduledImportResponse(ProspectScheduledImportRequest):
    id: str
    lastRunAt: str | None = None
    nextRunAt: str | None = None
    createdAt: str | None = None


class ProspectScheduledImportListResponse(BaseModel):
    schedules: list[ProspectScheduledImportResponse] = Field(default_factory=list)


class ProspectApiCredentialRequest(BaseModel):
    sourceId: str | None = None
    name: str


class ProspectApiCredentialResponse(BaseModel):
    id: str
    sourceId: str | None = None
    name: str
    keyPrefix: str
    apiKey: str | None = None
    active: bool
    createdAt: str | None = None


class ProspectApiCredentialListResponse(BaseModel):
    credentials: list[ProspectApiCredentialResponse] = Field(default_factory=list)


class ProspectImportExceptionResponse(BaseModel):
    id: str
    batchId: str | None = None
    rowId: str | None = None
    exceptionType: str
    severity: str
    status: str
    message: str
    assignedToUserId: str | None = None
    resolution: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    createdAt: str | None = None
    resolvedAt: str | None = None


class ProspectImportExceptionListResponse(BaseModel):
    exceptions: list[ProspectImportExceptionResponse] = Field(default_factory=list)


class ProspectImportExceptionResolveRequest(BaseModel):
    resolution: str


class ProspectApiImportRequest(BaseModel):
    sourceId: str | None = None
    sourceName: str | None = None
    sourceType: str = "api_import"
    sourceDetail: str | None = None
    lifecycleStage: str | None = None
    person: dict[str, object] = Field(default_factory=dict)
    interest: dict[str, object] = Field(default_factory=dict)
    tracking: dict[str, object] = Field(default_factory=dict)


class ProspectApiImportResponse(BaseModel):
    batchId: str
    status: str
    counts: ProspectImportCounts
    issues: list[ProspectImportIssue] = Field(default_factory=list)


class ProspectSourceReportingResponse(BaseModel):
    sources: list[dict[str, object]] = Field(default_factory=list)
    importPerformance: list[dict[str, object]] = Field(default_factory=list)
    duplicateAndErrorTrend: list[dict[str, object]] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


class ProspectImportErrorFileResponse(BaseModel):
    filename: str
    content: str
