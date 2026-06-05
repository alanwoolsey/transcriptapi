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
