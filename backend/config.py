from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────────
    database_url: Optional[str] = None  # preferred — full URL
    user:     str = ""
    password: str = ""
    host:     str = ""
    port:     str = "5432"
    dbname:   str = ""

    # ── Auth ──────────────────────────────────────────────────────────────────
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ── Google OAuth ──────────────────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    frontend_url: str = "http://localhost:5173"

    # ── Email ─────────────────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "Sentinel"

    # ── ML Service ────────────────────────────────────────────────────────────
    ml_service_url: str = "http://localhost:8001"
    ml_shared_upload_dir: str = "uploads"

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173", "https://sentinel-ivory-three.vercel.app"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg2://{self.user}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.dbname}?sslmode=require"
        )