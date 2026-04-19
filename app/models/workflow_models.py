from pydantic import BaseModel


class WorkflowListItem(BaseModel):
    id: str
    student: str
    studentId: str
    institution: str
    status: str
    owner: str
    age: str
    priority: str
    reason: str
