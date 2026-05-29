from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER = logging.getLogger("artifacts_manager")

REQUIRED_FILES = [
    "faiss_document_index.bin",
    "faiss_metadata.pkl",
    "category_classifier.pkl",
]


def _all_required_present(artifacts_dir: Path) -> bool:
    """Return True only if every required file exists and is non-empty."""
    for filename in REQUIRED_FILES:
        path = artifacts_dir / filename
        if not path.exists():
            LOGGER.info("[artifacts] Missing: %s", filename)
            return False
        if path.stat().st_size == 0:
            LOGGER.warning("[artifacts] Empty file (corrupted?): %s", filename)
            return False
    return True


def ensure_artifacts(
    artifacts_dir: Path,
    hf_repo_id: str,
    hf_token: str | None,
    repo_type: str = "dataset",
) -> None:
    """
    Ensure all artifacts are present in artifacts_dir.

    - If all required files exist → skips download (fast path).
    - If any are missing → downloads entire repo from HuggingFace Hub.

    This is safe to call every time the service starts.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if _all_required_present(artifacts_dir):
        LOGGER.info("[artifacts] All artifacts present at %s — skipping download.", artifacts_dir)
        return

    LOGGER.info("[artifacts] First boot detected — downloading from HuggingFace Hub...")
    LOGGER.info("[artifacts] Repo: %s", hf_repo_id)
    LOGGER.info("[artifacts] Destination: %s", artifacts_dir)
    LOGGER.info("[artifacts] This will take several minutes (~10GB)...")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise RuntimeError(
            "huggingface_hub is not installed. "
            "Add 'huggingface_hub' to ml-service/requirements.txt"
        )

    if not hf_token:
        LOGGER.warning(
            "[artifacts] HF_TOKEN is not set. "
            "This will fail for private repos. "
            "Set HF_TOKEN in your environment."
        )

    snapshot_download(
        repo_id=hf_repo_id,
        repo_type=repo_type,
        local_dir=str(artifacts_dir),
        token=hf_token,
        ignore_patterns=[".gitattributes", "*.git*"],
        local_dir_use_symlinks=False,   # ← add this
    )

    # Verify after download
    if not _all_required_present(artifacts_dir):
        missing = [
            f for f in REQUIRED_FILES
            if not (artifacts_dir / f).exists()
        ]
        raise RuntimeError(
            f"Download completed but required files are still missing: {missing}\n"
            f"Check that your HF repo contains these files."
        )

    LOGGER.info("[artifacts] Download complete. All required files verified.")


def get_artifacts_info(artifacts_dir: Path) -> dict:
    """Return size info for all artifact files — useful for the /health endpoint."""
    info = {}
    if not artifacts_dir.exists():
        return info
    for f in sorted(artifacts_dir.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(artifacts_dir))
            info[rel] = {
                "size_mb": round(f.stat().st_size / 1024**2, 1),
                "exists": True,
            }
    return info