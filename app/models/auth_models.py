from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class CompleteNewPasswordRequest(BaseModel):
    username: str
    new_password: str
    session: str


class ChangePasswordRequest(BaseModel):
    access_token: str
    previous_password: str
    proposed_password: str


class TenantInfo(BaseModel):
    tenant_id: int | str | UUID
    tenant_name: str
    tenant_code: str


class AuthChallengeResponse(TenantInfo):
    challenge_name: Literal["NEW_PASSWORD_REQUIRED"]
    session: str


class AuthSuccessResponse(TenantInfo):
    access_token: str
    id_token: str
    refresh_token: str | None = None
    expires_in: int
    token_type: str


class ChangePasswordResponse(BaseModel):
    success: bool = True
