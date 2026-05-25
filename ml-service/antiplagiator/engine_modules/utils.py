from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("antiplagiator.utils")


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def build_session(user_agent: str = "SentinelEngine/4.0") -> requests.Session:
    """Return a requests.Session with automatic retry on transient errors."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


# ---------------------------------------------------------------------------
# Device resolution
# ---------------------------------------------------------------------------

def resolve_device(preferred: str) -> str:
    """
    Return 'cuda' or 'cpu'.

    - If preferred is 'cpu' or 'cuda', honour it directly.
    - If preferred is 'auto', probe torch availability.
    """
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, records: list[Any]) -> None:
    """
    Write a list of dataclass instances (or plain dicts) to a JSONL file.
    Parent directories are created automatically.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            row = asdict(r) if hasattr(r, "__dataclass_fields__") else r
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    LOGGER.info("Wrote %d records to %s", len(records), path)


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file and return a list of dicts. Skips blank lines."""
    if not path.exists():
        LOGGER.warning("JSONL not found: %s", path)
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]