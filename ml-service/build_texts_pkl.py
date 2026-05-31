from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl",    type=Path, required=True,
                        help="Path to chunked_database.jsonl")
    parser.add_argument("--metadata", type=Path, required=True,
                        help="Path to faiss_metadata.pkl")
    parser.add_argument("--output",   type=Path, default=Path("faiss_texts.pkl"))
    parser.add_argument("--hf-repo",  type=str,  default=None)
    parser.add_argument("--hf-token", type=str,  default=None)
    args = parser.parse_args()

    # Load metadata to know the correct order
    print(f"Loading metadata from {args.metadata} ...")
    with open(args.metadata, "rb") as f:
        metadata = pickle.load(f)
    print(f"Metadata: {len(metadata):,} entries")

    # Build (arxiv_id, chunk_id) -> text lookup from JSONL
    print(f"Reading texts from {args.jsonl} ...")
    lookup: dict[tuple[str, int], str] = {}
    with open(args.jsonl, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row.get("arxiv_id", "")), int(row.get("chunk_id", 0)))
            lookup[key] = row.get("text", "")
    print(f"Lookup built: {len(lookup):,} entries")

    # Build texts list parallel to metadata
    texts: list[str] = []
    missing = 0
    for meta in metadata:
        key = (str(meta.get("arxiv_id", "")), int(meta.get("chunk_id", 0)))
        text = lookup.get(key, "")
        if not text:
            missing += 1
        texts.append(text)

    print(f"Texts built: {len(texts):,} entries ({missing:,} missing)")

    # Save locally
    print(f"Saving to {args.output} ...")
    with open(args.output, "wb") as f:
        pickle.dump(texts, f)
    size_gb = args.output.stat().st_size / 1024**3
    print(f"Saved ({size_gb:.2f} GB)")

    # Upload to HuggingFace
    if args.hf_repo:
        print(f"Uploading to {args.hf_repo} ...")
        from huggingface_hub import HfApi
        api = HfApi()
        api.upload_file(
            path_or_fileobj=str(args.output),
            path_in_repo="faiss_texts.pkl",
            repo_id=args.hf_repo,
            repo_type="dataset",
            token=args.hf_token,
        )
        print("Uploaded ✓")
    else:
        print("No --hf-repo specified — skipping upload.")
        print(f"Upload manually: huggingface-cli upload {args.hf_repo} {args.output} faiss_texts.pkl")


if __name__ == "__main__":
    main()