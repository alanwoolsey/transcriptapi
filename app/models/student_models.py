from datetime import datetime
from typing import Any

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


class Student360ListRecord(BaseModel):
    id: str
    studentId: str | None = None
    name: str
    preferredName: str | None = None
    email: str | None = None
    phone: str | None = None
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
    program: str | None = None
    degreeProgram: str | None = None


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
