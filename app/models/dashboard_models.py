from pydantic import BaseModel


class DashboardStat(BaseModel):
    label: str
    value: str
    delta: str
    tone: str


class DashboardFunnelItem(BaseModel):
    step: str
    count: int


class DashboardRoutingMixItem(BaseModel):
    name: str
    value: int


class DashboardAgentItem(BaseModel):
    name: str
    objective: str
    metric: str
    summary: str


class DashboardActivityItem(BaseModel):
    title: str
    detail: str
    when: str
    category: str


class DashboardResponse(BaseModel):
    stats: list[DashboardStat]
    funnel: list[DashboardFunnelItem]
    routing_mix: list[DashboardRoutingMixItem]
    agents: list[DashboardAgentItem]
    activity: list[DashboardActivityItem]
