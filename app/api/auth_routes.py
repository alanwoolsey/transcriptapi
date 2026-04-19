from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.auth_models import (
    AuthChallengeResponse,
    AuthSuccessResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CompleteNewPasswordRequest,
    LoginRequest,
)
from app.services.auth_service import (
    AuthService,
    CognitoAuthError,
    LocalUserNotFoundError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
auth_service = AuthService()


@router.post("/login", response_model=AuthChallengeResponse | AuthSuccessResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthChallengeResponse | AuthSuccessResponse:
    try:
        return auth_service.login(db, payload)
    except LocalUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.") from exc
    except CognitoAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/complete-new-password", response_model=AuthChallengeResponse | AuthSuccessResponse)
def complete_new_password(
    payload: CompleteNewPasswordRequest,
    db: Session = Depends(get_db),
) -> AuthChallengeResponse | AuthSuccessResponse:
    try:
        return auth_service.complete_new_password(db, payload)
    except LocalUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.") from exc
    except CognitoAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(payload: ChangePasswordRequest) -> ChangePasswordResponse:
    try:
        auth_service.change_password(payload)
    except CognitoAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ChangePasswordResponse()
