from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = Field(validation_alias=AliasChoices("username", "email"))
    password: str


class CompleteNewPasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = Field(validation_alias=AliasChoices("username", "email"))
    new_password: str = Field(validation_alias=AliasChoices("new_password", "newPassword"))
    session: str


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str | None = Field(default=None, validation_alias=AliasChoices("access_token", "accessToken"))
    previous_password: str = Field(validation_alias=AliasChoices("previous_password", "previousPassword", "oldPassword"))
    proposed_password: str = Field(validation_alias=AliasChoices("proposed_password", "proposedPassword", "newPassword"))


class TenantInfo(BaseModel):
    tenant_id: int | str | UUID
    tenant_name: str
    tenant_code: str
    user_id: str | None = None


class AuthChallengeResponse(TenantInfo):
    challenge_name: Literal["NEW_PASSWORD_REQUIRED"]
    challenge: Literal["NEW_PASSWORD_REQUIRED"] | None = None
    session: str


class AuthSuccessResponse(TenantInfo):
    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str | None = None


class ChangePasswordResponse(BaseModel):
    success: bool = True
