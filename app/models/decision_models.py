from pydantic import BaseModel


class DecisionWorkbenchItem(BaseModel):
    id: str
    student: str
    program: str
    fit: int
    creditEstimate: int
    readiness: str
    reason: str
