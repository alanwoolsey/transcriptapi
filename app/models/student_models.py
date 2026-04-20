from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


class StudentTimelineStep(BaseModel):
    label: str
    time: str


class StudentTranscriptCourse(BaseModel):
    courseId: str | None = None
    courseTitle: str | None = None
    term: str | None = None
    year: str | None = None
    credit: str | float | int | None = None
    grade: str | None = None
    subject: str | None = None
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
    name: str
    preferredName: str | None = None
    email: str | None = None
    phone: str | None = None
    program: str | StudentProgramSummary
    studentType: str | None = None
    institutionGoal: str
    stage: str
    risk: str
    advisor: str
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
