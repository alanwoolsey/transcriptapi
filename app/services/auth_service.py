from dataclasses import dataclass

from botocore.exceptions import ClientError
from sqlalchemy import case, or_, select
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
        auth_response = self._build_auth_response(resolved, response)
        if isinstance(auth_response, AuthSuccessResponse):
            self._activate_local_user(db, resolved.user.email, resolved.tenant.id)
        return auth_response

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
        auth_response = self._build_auth_response(resolved, response)
        if isinstance(auth_response, AuthSuccessResponse):
            self._activate_local_user(db, resolved.user.email, resolved.tenant.id)
        return auth_response

    def change_password(self, payload: ChangePasswordRequest) -> None:
        try:
            self._cognito_client.change_password(
                AccessToken=payload.access_token,
                PreviousPassword=payload.previous_password,
                ProposedPassword=payload.proposed_password,
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def admin_create_user(
        self,
        *,
        email: str,
        display_name: str,
        temporary_password: str | None = None,
        send_invite: bool = True,
    ) -> dict:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        try:
            params = {
                "UserPoolId": settings.cognito_user_pool_id,
                "Username": email,
                "DesiredDeliveryMediums": ["EMAIL"],
                "UserAttributes": [
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": display_name},
                ],
            }
            if temporary_password:
                params["TemporaryPassword"] = temporary_password
            if not send_invite:
                params["MessageAction"] = "SUPPRESS"
            return self._cognito_client.admin_create_user(**params)
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def admin_resend_invite(self, *, email: str) -> dict:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        try:
            return self._cognito_client.admin_create_user(
                UserPoolId=settings.cognito_user_pool_id,
                Username=email,
                DesiredDeliveryMediums=["EMAIL"],
                MessageAction="RESEND",
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def admin_reset_user_password(self, *, email: str) -> dict:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        try:
            return self._cognito_client.admin_reset_user_password(
                UserPoolId=settings.cognito_user_pool_id,
                Username=email,
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def admin_get_user(self, *, email: str) -> dict:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        try:
            return self._cognito_client.admin_get_user(
                UserPoolId=settings.cognito_user_pool_id,
                Username=email,
            )
        except ClientError as exc:
            raise self._map_cognito_error(exc) from exc

    def admin_update_user(
        self,
        *,
        current_email: str,
        email: str,
        display_name: str,
    ) -> None:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        try:
            self._cognito_client.admin_update_user_attributes(
                UserPoolId=settings.cognito_user_pool_id,
                Username=current_email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": display_name},
                ],
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
                AppUser.tenant_id == Tenant.id,
                Tenant.status == "active",
                or_(
                    AppUser.is_active.is_(True),
                    TenantUserMembership.status == "invited",
                ),
                TenantUserMembership.status.in_(["active", "invited"]),
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

    def _activate_local_user(self, db: Session, email: str | None, tenant_id) -> None:
        if db is None or not email:
            return
        user = db.execute(
            select(AppUser).where(AppUser.email == email, AppUser.tenant_id == tenant_id).limit(1)
        ).scalar_one_or_none()
        membership = db.execute(
            select(TenantUserMembership)
            .where(TenantUserMembership.tenant_id == tenant_id, TenantUserMembership.user_id == user.id)
            .limit(1)
        ).scalar_one_or_none() if user is not None else None
        changed = False
        if user is not None and not user.is_active:
            user.is_active = True
            changed = True
        if membership is not None and membership.status != "active":
            membership.status = "active"
            changed = True
        if changed:
            db.commit()

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
                user_id=(str(resolved.user.id) if getattr(resolved.user, "id", None) else None),
                challenge_name="NEW_PASSWORD_REQUIRED",
                challenge="NEW_PASSWORD_REQUIRED",
                session=cognito_response["Session"],
            )

        auth_result = cognito_response["AuthenticationResult"]
        return AuthSuccessResponse(
            tenant_id=resolved.tenant.id,
            tenant_name=resolved.tenant.name,
            tenant_code=resolved.tenant.slug,
            user_id=(str(resolved.user.id) if getattr(resolved.user, "id", None) else None),
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
        if error_code in {"UsernameExistsException"}:
            return CognitoAuthError(error_message, 409)
        if error_code in {"UserNotFoundException"}:
            return CognitoAuthError(error_message, 404)
        if error_code in {"PasswordResetRequiredException", "InvalidPasswordException"}:
            return CognitoAuthError(error_message, 400)
        if error_code in {"InvalidParameterException", "CodeMismatchException", "ExpiredCodeException"}:
            return CognitoAuthError(error_message, 400)
        if error_code == "TooManyRequestsException":
            return CognitoAuthError(error_message, 429)
        return CognitoAuthError(error_message, 502)
