from __future__ import annotations
import os
from supabase import create_client, Client

_client: Client | None = None
BUCKET = "documents"

def get_storage() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client

def upload_file(storage_path: str, file_bytes: bytes) -> str:
    get_storage().storage.from_(BUCKET).upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    return storage_path

def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    res = get_storage().storage.from_(BUCKET).create_signed_url(storage_path, expires_in)
    return res["signedURL"]

def download_file(storage_path: str) -> bytes:
    return get_storage().storage.from_(BUCKET).download(storage_path)