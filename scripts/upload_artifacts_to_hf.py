from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger("upload_artifacts")


def upload(artifacts_dir: Path, repo_id: str, token: str) -> None:
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        raise SystemExit("Run: pip install huggingface_hub")

    if not artifacts_dir.exists():
        raise SystemExit(f"Artifacts dir not found: {artifacts_dir}")

    api = HfApi(token=token)

    # Create repo if it doesn't exist (private by default)
    LOGGER.info("Creating/verifying repo: %s", repo_id)
    create_repo(
        repo_id=repo_id,
        repo_type="dataset",
        private=True,
        exist_ok=True,
        token=token,
    )

    # List what we're uploading
    all_files = list(artifacts_dir.rglob("*"))
    files_to_upload = [f for f in all_files if f.is_file()]
    total_size_gb = sum(f.stat().st_size for f in files_to_upload) / 1024**3

    LOGGER.info("Found %d files to upload (%.2f GB total)", len(files_to_upload), total_size_gb)
    for f in files_to_upload:
        size_mb = f.stat().st_size / 1024**2
        LOGGER.info("  %s (%.1f MB)", f.relative_to(artifacts_dir), size_mb)

    LOGGER.info("Starting upload — this may take 20-60 minutes depending on your connection...")

    api.upload_folder(
        folder_path=str(artifacts_dir),
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        commit_message="Upload FAISS artifacts and classifiers",
        # ignore common junk
        ignore_patterns=["*.pyc", "__pycache__", ".DS_Store", "*.npy"],
    )

    LOGGER.info("=" * 60)
    LOGGER.info("Upload complete!")
    LOGGER.info("Repo URL: https://huggingface.co/datasets/%s", repo_id)
    LOGGER.info("")
    LOGGER.info("IMPORTANT: Go to the URL above → Settings → Make Private")
    LOGGER.info("Then set HF_REPO_ID=%s in your ml-service/.env", repo_id)
    LOGGER.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload FAISS artifacts to HuggingFace Hub")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("backend/core/antiplagiator/artifacts"),
        help="Path to your artifacts folder",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        required=True,
        help="HuggingFace repo id, e.g. myusername/antiplagiator-artifacts",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.getenv("HF_TOKEN"),
        help="HuggingFace write token (or set HF_TOKEN env var)",
    )
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "No HF token provided. Pass --token hf_xxx or set HF_TOKEN env var.\n"
            "Get a token at: https://huggingface.co/settings/tokens"
        )

    upload(args.artifacts_dir, args.repo_id, args.token)


if __name__ == "__main__":
    main()