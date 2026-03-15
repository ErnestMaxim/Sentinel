from __future__ import annotations

import argparse
import io
import json
import logging
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{arxiv_id}.pdf"
DEFAULT_INPUT = Path("backend/core/antiplagiator/data/raw/arxiv_dataset.jsonl")
DEFAULT_OUTPUT = Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl")

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "SentinelChunkBuilder/1.0 "
                "(Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
        }
    )
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def extract_pdf_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        return " ".join(page.get_text("text") for page in doc)


def chunk_text(text: str, chunk_size: int, overlap: int, min_words: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")
    if min_words <= 0:
        raise ValueError("min_words must be > 0")

    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        if len(chunk_words) >= min_words:
            chunks.append(" ".join(chunk_words))
    return chunks


def download_and_chunk_pdf(
    session: requests.Session,
    arxiv_id: str,
    chunk_size: int,
    overlap: int,
    min_words: int,
    timeout_sec: int,
) -> list[str]:
    if not arxiv_id:
        return []

    url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
    resp = session.get(url, timeout=timeout_sec)
    resp.raise_for_status()

    text = extract_pdf_text(resp.content)
    return chunk_text(text, chunk_size, overlap, min_words)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build chunked plagiarism DB from arXiv PDFs")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunk-size", type=int, default=300)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--min-words", type=int, default=50)
    parser.add_argument("--pause-sec", type=float, default=3.0, help="Polite pause between papers")
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    output_dir = args.output.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(args.input)
    
    total_chunks_saved = 0
    session = build_session()

    with args.output.open("w", encoding="utf-8") as out_f:
        for index, record in enumerate(records, start=1):
            arxiv_id = str(record.get("arxiv_id", "")).strip()
            title = str(record.get("title", "")).strip()

            try:
                chunks = download_and_chunk_pdf(
                    session=session,
                    arxiv_id=arxiv_id,
                    chunk_size=args.chunk_size,
                    overlap=args.overlap,
                    min_words=args.min_words,
                    timeout_sec=args.timeout_sec,
                )
            except Exception as exc:
                chunks = []

            for chunk_index, chunk_text_value in enumerate(chunks):
                row = {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "chunk_id": chunk_index,
                    "text": chunk_text_value,
                }
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_chunks_saved += 1

            time.sleep(args.pause_sec)

if __name__ == "__main__":
    main()