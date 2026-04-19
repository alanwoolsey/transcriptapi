from dataclasses import dataclass

from botocore.exceptions import ClientError
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AppUser, Tenant, TenantUserMembership
from app.models.auth_models import (
    AuthChallengeResponse,
    AuthSuccessResponse,
    ChangePasswordRequest,
    CompleteNewPasswordRequest,
    LoginRequest,
)
from app.services.aws_client_factory import create_boto3_client


class LocalUserNotFoundError(Exception):
    pass


class CognitoAuthError(Exception):
    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass
class ResolvedAppUser:
    user: AppUser
    tenant: Tenant


class AuthService:
    def __init__(self) -> None:
        self._client = None

    def login(self, db: Session, payload: LoginRequest) -> AuthChallengeResponse | AuthSuccessResponse:
        resolved = self._resolve_user(db, payload.username)
        response = self._initiate_auth(payload.username, payload.password)
        return self._build_auth_response(resolved, response)

    def complete_new_password(
        self,
        db: Session,
        payload: CompleteNewPasswordRequest,
    ) -> AuthChallengeResponse | AuthSuccessResponse:
        resolved = self._resolve_user(db, payload.username)
        response = self._respond_to_new_password_challenge(
            username=payload.username,
            new_password=payload.new_password,
            session=payload.session,
        )
        return self._build_auth_response(resolved, response)

    def change_password(self, payload: ChangePasswordRequest) -> None:
        try:
            self._cognito_client.change_password(
                AccessToken=payload.access_token,
                PreviousPassword=payload.previous_password,
                ProposedPassword=payload.proposed_password,
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    @property
    def _cognito_client(self):
        if self._client is None:
            if not settings.cognito_app_client_id:
                raise RuntimeError("COGNITO_APP_CLIENT_ID is not configured.")
            self._client = create_boto3_client("cognito-idp")
        return self._client

    def _resolve_user(self, db: Session, email: str) -> ResolvedAppUser:
        stmt = (
            select(AppUser, Tenant)
            .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
            .join(Tenant, Tenant.id == TenantUserMembership.tenant_id)
            .where(
                AppUser.email == email,
                AppUser.is_active.is_(True),
                Tenant.status == "active",
                TenantUserMembership.status == "active",
            )
            .order_by(
                case((TenantUserMembership.is_default.is_(True), 0), else_=1),
                TenantUserMembership.created_at.asc(),
            )
            .limit(1)
        )
        row = db.execute(stmt).first()
        if row is None:
            raise LocalUserNotFoundError(email)
        user, tenant = row
        return ResolvedAppUser(user=user, tenant=tenant)

    def _initiate_auth(self, username: str, password: str) -> dict:
        try:
            return self._cognito_client.initiate_auth(
                ClientId=settings.cognito_app_client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": username, "PASSWORD": password},
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def _respond_to_new_password_challenge(self, username: str, new_password: str, session: str) -> dict:
        try:
            return self._cognito_client.respond_to_auth_challenge(
                ClientId=settings.cognito_app_client_id,
                ChallengeName="NEW_PASSWORD_REQUIRED",
                Session=session,
                ChallengeResponses={"USERNAME": username, "NEW_PASSWORD": new_password},
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def _build_auth_response(
        self,
        resolved: ResolvedAppUser,
        cognito_response: dict,
    ) -> AuthChallengeResponse | AuthSuccessResponse:
        challenge_name = cognito_response.get("ChallengeName")
        if challenge_name:
            if challenge_name != "NEW_PASSWORD_REQUIRED":
                raise CognitoAuthError(f"Unsupported Cognito challenge: {challenge_name}", 502)
            return AuthChallengeResponse(
                tenant_id=resolved.tenant.id,
                tenant_name=resolved.tenant.name,
                tenant_code=resolved.tenant.slug,
                challenge_name="NEW_PASSWORD_REQUIRED",
                session=cognito_response["Session"],
            )

        auth_result = cognito_response["AuthenticationResult"]
        return AuthSuccessResponse(
            tenant_id=resolved.tenant.id,
            tenant_name=resolved.tenant.name,
            tenant_code=resolved.tenant.slug,
            access_token=auth_result["AccessToken"],
            id_token=auth_result["IdToken"],
            refresh_token=auth_result.get("RefreshToken"),
            expires_in=auth_result["ExpiresIn"],
            token_type=auth_result["TokenType"],
        )

    def _map_cognito_error(self, exc: ClientError) -> CognitoAuthError:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        error_message = exc.response.get("Error", {}).get("Message", "Cognito request failed.")

        if error_code in {"NotAuthorizedException", "UserNotConfirmedException"}:
            return CognitoAuthError(error_message, 401)
        if error_code in {"PasswordResetRequiredException", "InvalidPasswordException"}:
            return CognitoAuthError(error_message, 400)
        if error_code in {"InvalidParameterException", "CodeMismatchException", "ExpiredCodeException"}:
            return CognitoAuthError(error_message, 400)
        if error_code == "TooManyRequestsException":
            return CognitoAuthError(error_message, 429)
        return CognitoAuthError(error_message, 502)
