import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from dependencies import get_current_user
from models import User
from schemas.auth import ForgotPasswordRequest, LoginRequest, ResetPasswordRequest, TokenResponse
from schemas.users import UserResponse, UserUpdate
from utils.email import send_password_reset_email
from utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])

settings = get_settings()

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"

_RESET_TOKEN_EXPIRE_MINUTES = 15


# ── Email / password ──────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == payload.email,
        User.is_deleted == False,
    ).first()

    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=create_access_token(subject=user.id))


# ── Password reset ────────────────────────────────────────────────────────────

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Always returns 200 — never reveal whether an email is registered."""
    user = db.query(User).filter(
        User.email == payload.email,
        User.is_deleted == False,
    ).first()

    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes==_RESET_TOKEN_EXPIRE_MINUTES)
        db.commit()
        background_tasks.add_task(send_password_reset_email, user.email, token)

    return {"detail": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Validate the reset token and set the new password. Token is single-use."""
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    user = db.query(User).filter(
        User.reset_token == payload.token,
        User.is_deleted == False,
    ).first()

    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link")

    expires_at = user.reset_token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is None or datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link")

    user.hashed_password        = hash_password(payload.new_password)
    user.reset_token            = None
    user.reset_token_expires_at = None
    db.commit()

    return {"detail": "Password updated successfully."}


# ── Current user ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.first_name is not None:
        current_user.first_name = payload.first_name
    if payload.last_name is not None:
        current_user.last_name = payload.last_name

    if payload.new_password:
        if not payload.current_password or not verify_password(payload.current_password, current_user.hashed_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
        current_user.hashed_password = hash_password(payload.new_password)

    db.commit()
    db.refresh(current_user)
    return current_user


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/google/login", tags=["Google OAuth"])
def google_login():
    params = (
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(url=_GOOGLE_AUTH_URL + params)


@router.get("/google/callback", tags=["Google OAuth"])
async def google_callback(code: str, db: Session = Depends(get_db)):
    """Exchange the auth code for a token, upsert the user, redirect with our JWT."""
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to fetch token: {token_resp.text}")

    google_access_token = token_resp.json().get("access_token")
    if not google_access_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google token response missing access_token")

    async with httpx.AsyncClient() as client:
        userinfo_resp = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )

    if userinfo_resp.status_code != 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to fetch user info from Google")

    info = userinfo_resp.json()
    google_id  = info.get("sub")
    email      = info.get("email", "")
    first_name = info.get("given_name", "")
    last_name  = info.get("family_name", "")

    if not google_id or not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incomplete profile returned by Google")

    user = db.query(User).filter(User.google_id == google_id).first()

    if not user:
        user = db.query(User).filter(
            User.email == email,
            User.is_deleted == False,
        ).first()

        if user:
            user.google_id = google_id
        else:
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                hashed_password=None,
                google_id=google_id,
            )
            db.add(user)

        db.commit()
        db.refresh(user)

    jwt_token = create_access_token(subject=user.id)
    return RedirectResponse(url=f"{settings.frontend_url}/oauth-callback?token={jwt_token}")