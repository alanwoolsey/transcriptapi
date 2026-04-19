from pydantic import BaseModel


class TrustCaseItem(BaseModel):
    id: str
    student: str
    severity: str
    signal: str
    evidence: str
    status: str
