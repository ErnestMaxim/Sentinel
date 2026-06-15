import httpx
from fastapi import HTTPException

from config import get_settings

settings = get_settings()

_ANALYZE_DEFAULTS = {
    "threshold": 0.60,
    "top_k": 50,
    "paraphrase_mode": False,
}


def analyze_document(file_path: str, arxiv_id: str | None = None) -> dict:
    """Call the ML microservice to run plagiarism analysis on a file."""
    payload = {
        "file_path": file_path,
        "arxiv_id": arxiv_id,
        **_ANALYZE_DEFAULTS,
    }

    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(f"{settings.ml_service_url}/analyze", json=payload)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach ML service at {settings.ml_service_url}. Is it running?",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="ML service timed out. The document may be too large.",
        )

    match response.status_code:
        case 200:
            return response.json()
        case 503:
            raise HTTPException(503, "ML service not ready yet. Try again shortly.")
        case 404:
            raise HTTPException(500, "ML service could not find the uploaded file. Check shared volume.")
        case _:
            raise HTTPException(500, f"ML service error {response.status_code}: {response.text}")