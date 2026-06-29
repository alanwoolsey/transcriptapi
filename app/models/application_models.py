from datetime import datetime

from pydantic import BaseModel, Field


class ApplicationCreateRequest(BaseModel):
    studentId: str
    prospectId: str | None = None
    applicationNumber: str | None = None
    applicationType: str = "degree"
    studentType: str | None = None
    population: str | None = None
    admitTermCode: str | None = None
    entryTermCode: str | None = None
    programId: str | None = None
    campusId: str | None = None
    modality: str | None = None
    status: str = "draft"


class ApplicationStatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None


class AdmissionsDecisionCreateRequest(BaseModel):
    decisionCode: str
    decisionReason: str | None = None
    effectiveTerm: str | None = None
    conditions: dict[str, object] = Field(default_factory=dict)
    letterTemplateId: str | None = None
    releaseToStudent: bool = False


class ApplicationRecord(BaseModel):
    id: str
    studentId: str
    prospectId: str | None = None
    applicationNumber: str
    applicationType: str
    studentType: str | None = None
    population: str | None = None
    admitTermCode: str | None = None
    entryTermCode: str | None = None
    programId: str | None = None
    campusId: str | None = None
    modality: str | None = None
    status: str
    submittedAt: datetime | None = None
    completedAt: datetime | None = None
    decisionStatus: str | None = None
    decisionAt: datetime | None = None
    createdAt: datetime
    updatedAt: datetime


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationRecord] = Field(default_factory=list)
    total: int


class ApplicationResponse(BaseModel):
    application: ApplicationRecord


class AdmissionsDecisionRecord(BaseModel):
    id: str
    applicationId: str
    studentId: str
    decisionCode: str
    decisionReason: str | None = None
    decidedAt: datetime
    effectiveTerm: str | None = None
    conditions: dict[str, object] = Field(default_factory=dict)
    releasedToStudentAt: datetime | None = None


class AdmissionsDecisionResponse(BaseModel):
    decision: AdmissionsDecisionRecord
