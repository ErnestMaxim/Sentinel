import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas.users import UserResponse
from utils.security import create_access_token, decode_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ── Google OAuth config ───────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI")
FRONTEND_URL         = os.getenv("FRONTEND_URL")

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Email / password login ────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == payload.email,
        User.is_deleted == False,  # noqa: E712
    ).first()

    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token)


# ── Current user dependency ───────────────────────────────────────────────────

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if subject is None:
            raise credentials_exception
        user_id = int(subject)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(
        User.id == user_id,
        User.is_deleted == False,  # noqa: E712
    ).first()

    if user is None:
        raise credentials_exception

    return user


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/google", tags=["Google OAuth"])
def google_login():
    """Redirect the user to Google's OAuth consent screen."""
    params = (
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(url=GOOGLE_AUTH_URL + params)


@router.get("/google/callback", tags=["Google OAuth"])
async def google_callback(code: str, db: Session = Depends(get_db)):
    """
    Handle the redirect back from Google.
    Exchange the auth code for a token, fetch user info,
    upsert the user in the DB, then redirect to the frontend with our JWT.
    """

    # 1. Exchange the auth code for a Google access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        # ADD THIS LOGGING LINE:
        print(f"GOOGLE TOKEN ERROR: {token_resp.status_code} - {token_resp.text}")
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch token: {token_resp.text}", # Temporarily show the detail
        )

    google_access_token = token_resp.json().get("access_token")
    if not google_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google token response missing access_token",
        )

    # 2. Use the Google access token to fetch the user's profile
    async with httpx.AsyncClient() as client:
        userinfo_resp = await client.get(
            GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )

    if userinfo_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to fetch user info from Google",
        )

    info       = userinfo_resp.json()
    google_id  = info.get("sub")          # Google's unique user ID
    email      = info.get("email", "")
    first_name = info.get("given_name", "")
    last_name  = info.get("family_name", "")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incomplete profile returned by Google",
        )

    # 3. Find or create the user
    user = db.query(User).filter(User.google_id == google_id).first()

    if not user:
        # Check if an email-based account already exists → link it
        user = db.query(User).filter(
            User.email == email,
            User.is_deleted == False,  # noqa: E712
        ).first()

        if user:
            user.google_id = google_id
        else:
            # Brand-new user — no password needed
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

    # 4. Issue our own JWT and send the user back to the frontend
    token = create_access_token(subject=user.id)
    return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?token={token}")