from __future__ import annotations

import argparse
import io
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{arxiv_id}.pdf"
DEFAULT_INPUT = Path("backend/core/antiplagiator/data/raw/arxiv_dataset.jsonl")
DEFAULT_OUTPUT = Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl")

# Lock to prevent file corruption when multiple threads write to the JSONL file simultaneously
file_write_lock = threading.Lock()
LOGGER = logging.getLogger("fast_builder")

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "SentinelFastBuilder/3.0"})
    retry = Retry(
        total=3, 
        backoff_factor=1.0, 
        status_forcelist=[429, 500, 502, 503, 504], 
        allowed_methods={"GET"}
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    return session

def extract_and_clean_pdf_text(pdf_bytes: bytes) -> str:
    """Extracts text from PDF, removes corrupted characters, and cuts the bibliography."""
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        raw_text = " ".join(page.get_text("text") for page in doc)
        
    # 1. Clean invisible ASCII control characters (e.g., \u0001, \b)
    clean_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw_text)
    
    # 2. Replace multiple spaces or newlines with a single space
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # 3. Exclude Bibliography (if it appears in the last 25% of the document)
    match = re.search(r"\b(References|Bibliography)\b", clean_text, flags=re.IGNORECASE | re.MULTILINE)
    if match and match.start() > (len(clean_text) * 0.75):
        clean_text = clean_text[: match.start()]
        
    return clean_text

def chunk_text(text: str, chunk_size: int, overlap: int, min_words: int) -> list[str]:
    words = text.split()
    step = chunk_size - overlap
    chunks = []
    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        if len(chunk_words) >= min_words:
            chunks.append(" ".join(chunk_words))
    return chunks

def process_single_paper(record: dict, session: requests.Session, args) -> list[dict]:
    """The function executed by each individual thread."""
    arxiv_id = str(record.get("arxiv_id", "")).strip()
    title = str(record.get("title", "")).strip()
    if not arxiv_id: 
        return []

    try:
        url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
        resp = session.get(url, timeout=args.timeout_sec)
        resp.raise_for_status()
        
        text = extract_and_clean_pdf_text(resp.content)
        chunks = chunk_text(text, args.chunk_size, args.overlap, args.min_words)
        
        return [
            {"arxiv_id": arxiv_id, "title": title, "chunk_id": i, "text": chunk} 
            for i, chunk in enumerate(chunks)
        ]
    except Exception as e:
        # Silently skip failed downloads to keep the pipeline moving
        return []

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    parser = argparse.ArgumentParser(description="Fast Multithreaded ArXiv PDF Downloader and Chunker")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--overlap", type=int, default=30)
    parser.add_argument("--min-words", type=int, default=20)
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel downloads")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    with args.input.open("r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    session = build_session()
    total_saved = 0

    LOGGER.info(f"Starting to process {len(records)} documents using {args.workers} parallel workers...")

    with args.output.open("w", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            # Submit all tasks to the thread pool
            futures = {executor.submit(process_single_paper, rec, session, args): rec for rec in records}
            
            # As each PDF finishes downloading and chunking...
            for future in as_completed(futures):
                result_rows = future.result()
                
                if result_rows:
                    # Use the thread lock to write safely to the output file
                    with file_write_lock:
                        for row in result_rows:
                            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        total_saved += len(result_rows)
                        
                if total_saved % 1000 == 0 and total_saved > 0:
                    LOGGER.info(f"-> Successfully saved {total_saved} text chunks so far...")

    LOGGER.info(f"Finished! Saved a total of {total_saved} clean text chunks.")

if __name__ == "__main__":
    main()