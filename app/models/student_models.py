from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StudentChecklistItem(BaseModel):
    label: str
    done: bool


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


class Student360Record(BaseModel):
    id: str
    name: str
    preferredName: str
    email: str | None = None
    phone: str | None = None
    program: str
    institutionGoal: str
    stage: str
    risk: str
    advisor: str
    city: str
    gpa: float
    creditsAccepted: float | int
    transcriptsCount: int
    fitScore: int
    depositLikelihood: int
    lastActivity: str
    tags: list[str] = Field(default_factory=list)
    summary: str
    checklist: list[StudentChecklistItem] = Field(default_factory=list)
    transcripts: list[StudentTranscriptRecord] = Field(default_factory=list)
    termGpa: list[StudentTermGpa] = Field(default_factory=list)
    recommendation: StudentRecommendation
