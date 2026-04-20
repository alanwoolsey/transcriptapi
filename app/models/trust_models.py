from pydantic import BaseModel


class TrustCaseItem(BaseModel):
    id: str
    studentId: str | None = None
    student: str
    documentId: str | None = None
    document: str | None = None
    severity: str
    signal: str
    evidence: str
    status: str
    owner: dict[str, str] | None = None
    openedAt: str | None = None
