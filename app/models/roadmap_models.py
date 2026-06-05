from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ItemsResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: int | None = None
    offset: int | None = None


class ItemResponse(BaseModel):
    item: dict[str, Any]


class RoadmapActionRequest(BaseModel):
    status: str | None = None
    note: str | None = None
    reason: str | None = None
    ownerUserId: str | None = None
    office: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RoadmapActionResponse(BaseModel):
    success: bool = True
    status: str
    detail: str
    item: dict[str, Any] | None = None


class ChecklistTemplateItemPayload(BaseModel):
    code: str
    label: str
    required: bool = True
    optional: bool = False
    conditional: bool = False
    waivable: bool = False
    blocking: bool = True
    sortOrder: int = 0
    documentType: str | None = None
    reviewRequiredDefault: bool = False
    rules: dict[str, Any] = Field(default_factory=dict)


class ChecklistTemplatePayload(BaseModel):
    name: str
    population: str
    programId: str | None = None
    termCode: str | None = None
    studentType: str | None = None
    active: bool = True
    items: list[ChecklistTemplateItemPayload] = Field(default_factory=list)


class InteractionPayload(BaseModel):
    type: str = "note"
    body: str | None = None
    note: str | None = None
    channel: str | None = None
    outcome: str | None = None
    nextFollowUpAt: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ConnectorConfigPayload(BaseModel):
    status: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorMappingsPayload(BaseModel):
    mappings: list[dict[str, Any]] = Field(default_factory=list)

