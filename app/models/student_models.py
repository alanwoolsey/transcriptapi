from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class StudentChecklistItem(BaseModel):
    id: str | None = None
    label: str
    status: str | None = None
    done: bool
    required: bool | None = None
    category: str | None = None
    updatedAt: str | None = None
    updatedBy: dict[str, str] | None = None


class StudentProgramSummary(BaseModel):
    id: str | None = None
    name: str


class StudentOwnerSummary(BaseModel):
    id: str | None = None
    name: str
    email: str | None = None


class StudentReadinessSummary(BaseModel):
    state: str
    label: str
    reason: str
    tone: str | None = None


class StudentTimelineStep(BaseModel):
    label: str
    time: str


class StudentTranscriptCourse(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    courseId: str | None = Field(default=None, validation_alias=AliasChoices("courseId", "CourseId"), serialization_alias="CourseId")
    courseTitle: str | None = Field(default=None, validation_alias=AliasChoices("courseTitle", "CourseTitle"), serialization_alias="CourseTitle")
    courseNumber: str | None = Field(default=None, validation_alias=AliasChoices("courseNumber", "Course Number"), serialization_alias="Course Number")
    term: str | None = None
    year: str | None = None
    credit: str | float | int | None = None
    grade: str | None = None
    subject: str | None = Field(default=None, validation_alias=AliasChoices("subject", "Subject"), serialization_alias="Subject")
    creditAttempted: str | float | int | None = None


class StudentTranscriptRecord(BaseModel):
    id: str
    source: str
    documentId: str | None = None
    documentUploadId: str | None = None
    crtfyDocumentId: str | None = None
    documentStorageProvider: str | None = None
    documentStorageDepartment: str | None = None
    documentContentUrl: str | None = None
    institution: str
    type: str
    uploadedAt: datetime | str
    status: str
    confidence: float
    credits: float | int
    pages: int
    owner: str
    notes: str
    steps: list[StudentTimelineStep] = Field(default_factory=list)
    courses: list[StudentTranscriptCourse] = Field(default_factory=list)
    rawDocument: dict[str, Any] | None = None


class StudentTermGpa(BaseModel):
    term: str
    gpa: float
    credits: float | int


class StudentRecommendation(BaseModel):
    summary: str
    fitNarrative: str
    nextBestAction: str


class StudentApplicationSummary(BaseModel):
    id: str | None = None
    status: str | None = None
    type: str | None = None
    entryTerm: str | None = None
    campus: str | None = None
    delivery: str | None = None
    startedAt: str | None = None
    submittedAt: str | None = None
    residency: str | None = None
    studentType: str | None = None
    nextStep: str | None = None


class StudentFafsaSummary(BaseModel):
    status: str | None = None
    receivedAt: str | None = None
    aidYear: str | None = None
    sai: str | None = None
    dependencyStatus: str | None = None
    verificationStatus: str | None = None


class StudentFinancialAidSummary(BaseModel):
    usingFinancialAid: bool | None = None
    status: str | None = None
    fafsa: StudentFafsaSummary | None = None
    packageStatus: str | None = None
    estimatedAid: float | int | None = None
    scholarshipStatus: str | None = None
    scholarshipAmount: float | int | None = None
    nextStep: str | None = None


class StudentScholarshipOption(BaseModel):
    id: str
    name: str
    amount: float | int | None = None
    owner: str | None = None
    description: str | None = None
    action: str | None = None
    matchScore: int | None = None
    status: str | None = None
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class StudentScholarshipOffer(BaseModel):
    id: str
    name: str
    sourceType: Literal["Institutional", "External"]
    provider: str | None = None
    amount: float | int | None = None
    status: str | None = None
    offeredAt: str | None = None
    renewable: bool | None = None
    requirements: str | None = None
    notes: str | None = None


class Student360ListRecord(BaseModel):
    id: str
    studentId: str | None = None
    name: str
    preferredName: str | None = None
    email: str | None = None
    phone: str | None = None
    smsOptIn: bool | None = None
    textingOk: bool | None = None
    textConsent: bool | None = None
    addressLine1: str | None = None
    addressLine2: str | None = None
    state: str | None = None
    postalCode: str | None = None
    parentName: str | None = None
    parentRelationship: str | None = None
    parentEmail: str | None = None
    parentPhone: str | None = None
    notes: str | None = None
    program: str | StudentProgramSummary
    degreeProgram: str | None = None
    population: str | None = None
    studentType: str | None = None
    source: str | None = None
    sourceCategory: str | None = None
    campaign: str | None = None
    termInterest: str | None = None
    institutionGoal: str
    stage: str
    risk: str
    owner: StudentOwnerSummary | None = None
    assignedOwner: StudentOwnerSummary | None = None
    ownerId: str | None = None
    advisor: str
    readiness: StudentReadinessSummary | None = None
    city: str | None = None
    fitScore: int
    depositLikelihood: int
    summary: str
    gpa: float
    creditsAccepted: float | int
    transcriptsCount: int
    lastActivity: str | None = None
    tags: list[str] = Field(default_factory=list)
    nextBestAction: str
    nextAction: str | None = None
    lastContactedAt: str | None = None
    nextFollowUpAt: str | None = None
    contactOutcome: str | None = None
    interactions: list[dict[str, Any]] | None = None
    handoffs: list[dict[str, Any]] | None = None
    postAdmitMilestones: list[dict[str, Any]] | None = None
    territory: str | None = None
    sourceSchool: str | None = None
    partnerSchool: str | None = None
    checklist: list[StudentChecklistItem] | None = None
    transcripts: list[StudentTranscriptRecord] | None = None
    termGpa: list[StudentTermGpa] | None = None
    recommendation: StudentRecommendation | None = None
    application: StudentApplicationSummary | None = None
    financialAid: StudentFinancialAidSummary | None = None
    scholarshipOptions: list[StudentScholarshipOption] = Field(default_factory=list)
    scholarshipOffers: list[StudentScholarshipOffer] = Field(default_factory=list)


class Student360Record(Student360ListRecord):
    preferredName: str
    city: str
    lastActivity: str
    recommendation: StudentRecommendation
    yield_data: dict[str, Any] | None = Field(default=None, alias="yield")
    handoff: dict[str, Any] | None = None
    trustSummary: dict[str, Any] | None = None
    decisionSummary: dict[str, Any] | None = None


class Student360ListResponse(BaseModel):
    students: list[Student360ListRecord] = Field(default_factory=list)
    total: int


class Student360DetailResponse(BaseModel):
    student: Student360Record


class StudentCreateRequest(BaseModel):
    id: str | None = None
    studentId: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    population: str | None = None
    studentType: str | None = None
    source: str | None = None
    sourceCategory: str | None = None
    campaign: str | None = None
    stage: str | None = None
    termInterest: str | None = None
    program: str | None = None
    degreeProgram: str | None = None
    programInterest: str | None = None
    institutionGoal: str | None = None
    owner: str | None = None
    advisor: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    territory: str | None = None
    sourceSchool: str | None = None
    partnerSchool: str | None = None


class StudentTimelineActor(BaseModel):
    id: str | None = None
    name: str
    type: str = "system"


class StudentTimelineEntity(BaseModel):
    type: str
    id: str | None = None


class StudentInteractionRecord(BaseModel):
    id: str
    studentId: str | None = None
    type: str
    outcome: str | None = None
    title: str
    note: str | None = None
    description: str | None = None
    nextAction: str | None = None
    nextFollowUpAt: str | None = None
    occurredAt: str
    actor: str | None = None
    source: str


class StudentInteractionCreateRequest(BaseModel):
    type: str
    outcome: str | None = None
    title: str | None = None
    note: str | None = None
    description: str | None = None
    nextAction: str | None = None
    nextFollowUpAt: str | None = None
    occurredAt: str | None = None
    actor: str | None = None
    source: str = "student_360"


class StudentInteractionUpdateRequest(BaseModel):
    type: str | None = None
    outcome: str | None = None
    title: str | None = None
    note: str | None = None
    description: str | None = None
    nextAction: str | None = None
    nextFollowUpAt: str | None = None
    occurredAt: str | None = None
    actor: str | None = None
    source: str | None = None


class StudentInteractionCreateResponse(BaseModel):
    interaction: StudentInteractionRecord


class StudentInteractionsListResponse(BaseModel):
    items: list[StudentInteractionRecord] = Field(default_factory=list)


class StudentTimelineEvent(BaseModel):
    id: str
    type: str
    title: str
    description: str | None = None
    occurredAt: str
    actor: StudentTimelineActor | str | None = None
    source: str
    status: str | None = None
    entity: StudentTimelineEntity | None = None
    sensitivityTier: str = "standard"


class StudentTimelineResponse(BaseModel):
    events: list[StudentTimelineEvent] = Field(default_factory=list)


class StudentProgramUpdateRequest(BaseModel):
    name: str | None = None
    preferredName: str | None = None
    email: str | None = None
    phone: str | None = None
    smsOptIn: bool | None = None
    textingOk: bool | None = None
    textConsent: bool | None = None
    addressLine1: str | None = None
    addressLine2: str | None = None
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    parentName: str | None = None
    parentRelationship: str | None = None
    parentEmail: str | None = None
    parentPhone: str | None = None
    advisor: str | None = None
    population: str | None = None
    source: str | None = None
    notes: str | None = None
    program: str | None = None
    degreeProgram: str | None = None
    programInterest: str | None = None


class StudentProgramUpdateResponse(BaseModel):
    id: str
    program: str
    degreeProgram: str
    stage: str


class StudentNextActionRequest(BaseModel):
    actionType: str
    note: str | None = None
    nextAction: str | None = None
    contactOutcome: str | None = None
    ownerId: str | None = None
    lastContactedAt: str | None = None
    nextFollowUpAt: str | None = None
    lastActivity: str | None = None


class StudentNextActionResponse(BaseModel):
    id: str
    nextAction: str | None = None
    nextFollowUpAt: str | None = None
    lastContactedAt: str | None = None
    contactOutcome: str | None = None
    lastActivity: str | None = None
