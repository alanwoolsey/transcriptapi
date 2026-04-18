from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class BoundingBoxModel(BaseModel):
    left: float = 0.0
    top: float = 0.0
    width: float = 0.0
    height: float = 0.0


class DemographicModel(BaseModel):
    firstName: str = ""
    lastName: str = ""
    middleName: str = ""
    studentId: str = ""
    institutionId: str = ""
    dateOfBirth: str = ""
    ssn: str = ""
    institutionName: str = ""
    institutionAddress: str = ""
    institutionCity: str = ""
    institutionState: str = ""
    institutionPostalCode: str = ""
    institutionCountry: str = ""
    ceebCode: str = ""
    official: str = ""
    accredited: str = ""
    accreditationAgency: str = ""
    cumulativeGpa: str = ""
    weightedGpa: str = ""
    unweightedGpa: str = ""
    totalCreditsAttempted: str = ""
    totalCreditsEarned: str = ""
    totalGradePoints: str = ""
    classRank: str = ""
    weightedClassRank: str = ""
    classSize: str = ""
    weightedClassSize: str = ""
    degreeAwarded: str = ""
    degreeAwardedDate: str = ""
    degreeAwarded2: str = ""
    degreeAwardedDate2: str = ""
    graduationDate: str = ""
    studentAddress: str = ""
    studentCity: str = ""
    studentState: str = ""
    studentPostalCode: str = ""
    studentCountry: str = ""
    actEnglishScore: str = ""
    actEnglishDate: str = ""
    actMathScore: str = ""
    actMathDate: str = ""
    actReadingScore: str = ""
    actReadingDate: str = ""
    actSciencesScore: str = ""
    actSciencesDate: str = ""
    actStemScore: str = ""
    actStemDate: str = ""
    actCompositeScore: str = ""
    actCompositeDate: str = ""
    satMathScore: str = ""
    satMathDate: str = ""
    satReadingScore: str = ""
    satReadingDate: str = ""
    satTotalScore: str = ""
    satTotalDate: str = ""


class CourseTranscriptModel(BaseModel):
    subject: str = ""
    courseId: str = ""
    courseTitle: str = ""
    credit: str = ""
    grade: str = ""
    gradePoints: str = ""
    term: str = ""
    year: str = ""
    startDate: str = ""
    endDate: str = ""
    transfer: str = ""
    repeat: str = ""
    courseType: str = ""
    rigor: str = ""
    confidenceScore: float = 0.0
    notes: str = ""
    tenantCourseCodes: Optional[List[str]] = None
    equivalencyId: Optional[str] = None
    mappingStatus: str = ""
    transferGrade: str = ""
    transferStatus: str = ""
    ruleApplied: str = ""
    boundingBox: BoundingBoxModel = Field(default_factory=BoundingBoxModel)
    pageNumber: int = 1
    courseGpa: Optional[float] = None
    institution: str = ""
    equlCourseCode: Optional[str] = None
    equlCoreCode: Optional[str] = None
    creditAttempted: str = ""
    courseLevel: str = ""
    equlSubject: Optional[str] = None
    equlDescription: Optional[str] = None
    equlCredit: Optional[str] = None
    equlTerm: Optional[str] = None
    equlYear: Optional[str] = None


class GradePointsNumericRangeModel(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class GradePointMapModel(BaseModel):
    gradeAlpha: str = ""
    gradePoints: float = 0.0
    gradePointsNumericRange: GradePointsNumericRangeModel = Field(default_factory=GradePointsNumericRangeModel)


class GrandGPAModel(BaseModel):
    unitsEarned: float = 0.0
    simpleGPA: float = 0.0
    cumulativeGPA: float = 0.0
    weightedGPA: float = 0.0


class TermGPAModel(BaseModel):
    uniqueRowId: int = 0
    year: str = ""
    term: str = ""
    simpleUnitsEarned: float = 0.0
    simplePoints: float = 0.0
    simpleGPA: float = 0.0


class AuditModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    occurredOnUtc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    category: str = "Document"
    action: str = "Ready Completed"
    entityType: str = "Document"
    entityId: str
    payloadJson: str = ""
    userId: Optional[str] = None
    tenantId: Optional[str] = None
    success: bool = True
    errorMessage: Optional[str] = None
    correlationId: Optional[str] = None
    source: str = "Documents"


class ParseTranscriptResponse(BaseModel):
    documentId: str
    demographic: DemographicModel = Field(default_factory=DemographicModel)
    courses: List[CourseTranscriptModel] = Field(default_factory=list)
    gradePointMap: List[GradePointMapModel] = Field(default_factory=list)
    grandGPA: GrandGPAModel = Field(default_factory=GrandGPAModel)
    termGPAs: List[TermGPAModel] = Field(default_factory=list)
    audit: List[AuditModel] = Field(default_factory=list)
    isOfficial: bool = False
    isFinalized: bool = False
    finalizedAt: Optional[str] = None
    finalizedBy: Optional[str] = None
    isFraudulent: bool = False
    fraudFlaggedAt: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchParseTranscriptItem(BaseModel):
    filename: str
    success: bool = False
    result: Optional[ParseTranscriptResponse] = None
    error: Optional[str] = None


class BatchParseTranscriptResponse(BaseModel):
    totalFiles: int = 0
    processedFiles: int = 0
    failedFiles: int = 0
    items: List[BatchParseTranscriptItem] = Field(default_factory=list)
