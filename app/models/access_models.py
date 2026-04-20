from pydantic import BaseModel, Field


class CurrentUserScopesResponse(BaseModel):
    tenants: list[str] = Field(default_factory=list)
    campuses: list[str] = Field(default_factory=list)
    territories: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    studentPopulations: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class CurrentUserAccessResponse(BaseModel):
    userId: str
    email: str | None = None
    displayName: str
    tenantId: str
    tenantSlug: str
    tenantName: str
    baseRole: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    sensitivityTiers: list[str] = Field(default_factory=list)
    scopes: CurrentUserScopesResponse = Field(default_factory=CurrentUserScopesResponse)
    recordExceptions: list[str] = Field(default_factory=list)
