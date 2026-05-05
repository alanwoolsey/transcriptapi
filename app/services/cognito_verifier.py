from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import settings


class TokenVerificationError(Exception):
    pass


class CognitoAccessTokenVerifier:
    def __init__(self) -> None:
        if not settings.cognito_user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured.")
        if not settings.cognito_app_client_id:
            raise RuntimeError("COGNITO_APP_CLIENT_ID is not configured.")
        self.issuer = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.cognito_user_pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"

    @property
    def jwk_client(self) -> PyJWKClient:
        return get_jwk_client(self.jwks_url)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=settings.cognito_clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "token_use"]},
            )
        except Exception as exc:
            raise TokenVerificationError("Invalid access token.") from exc

        if claims.get("token_use") != "access":
            raise TokenVerificationError("Invalid access token.")
        if claims.get("client_id") != settings.cognito_app_client_id:
            raise TokenVerificationError("Invalid access token.")
        return claims


@lru_cache(maxsize=8)
def get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)
