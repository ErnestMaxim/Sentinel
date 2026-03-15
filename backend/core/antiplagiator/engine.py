from __future__ import annotations

import argparse
import json
import logging
import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import faiss
import fitz
from sentence_transformers import SentenceTransformer


LOGGER = logging.getLogger("plagiarism_engine")


def resolve_device(preferred: str) -> str:
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


class AntiplagiarismEngine:
    def __init__(
        self,
        model_name: str = "all-mpnet-base-v2",
        artifacts_dir: Path = Path("backend/core/antiplagiator/artifacts"),
        data_dir: Path = Path("backend/core/antiplagiator/data/processed"),
        device: str = "auto",
    ) -> None:
        self.artifacts_dir = artifacts_dir
        self.data_dir = data_dir
        self.device = resolve_device(device)

        LOGGER.info("Initializing AntiplagiarismEngine")
        LOGGER.info("Using device: %s", self.device)

        LOGGER.info("Loading model: %s", model_name)
        self.model = SentenceTransformer(model_name, device=self.device)

        index_path = self.artifacts_dir / "faiss_document_index.bin"
        metadata_path = self.artifacts_dir / "faiss_metadata.pkl"
        dataset_path = self.data_dir / "chunked_database.jsonl"

        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {index_path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"FAISS metadata not found: {metadata_path}")

        LOGGER.info("Loading FAISS index from %s", index_path)
        self.index = faiss.read_index(str(index_path))

        LOGGER.info("Loading metadata from %s", metadata_path)
        with metadata_path.open("rb") as f:
            self.metadata: list[dict[str, Any]] = pickle.load(f)

        LOGGER.info("Loading dataset texts from %s", dataset_path)
        self.dataset_texts = self._load_dataset_texts(dataset_path)

        LOGGER.info("Engine ready")

    def _load_dataset_texts(self, jsonl_path: Path) -> list[str]:
        texts: list[str] = []
        if not jsonl_path.exists():
            LOGGER.warning("Dataset JSONL not found at %s", jsonl_path)
            return texts

        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                texts.append(str(data.get("text", "")))
        return texts

    def _read_and_chunk_file(self, file_path: Path, chunk_size: int = 300, overlap: int = 50) -> list[str]:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be >= 0 and < chunk_size")

        text = ""
        if file_path.suffix.lower() == ".pdf":
            with fitz.open(file_path) as doc:
                for page in doc:
                    text += page.get_text("text") + " "
        else:
            with file_path.open("r", encoding="utf-8") as f:
                text = f.read()

        match = re.search(r"\b(References|Bibliography)\b", text, flags=re.IGNORECASE | re.MULTILINE)
        if match and match.start() > (len(text) * 0.75):
            text = text[: match.start()]

        words = text.split()
        chunks: list[str] = []
        step = chunk_size - overlap

        for i in range(0, len(words), step):
            chunk_words = words[i : i + chunk_size]
            if len(chunk_words) >= 50:
                chunks.append(" ".join(chunk_words))

        return chunks

    def analyze_document(self, file_path: Path, threshold: float = 0.70, top_k: int = 5) -> dict[str, Any]:
        chunks = self._read_and_chunk_file(file_path)
        if not chunks:
            return {"error": "No valid text could be extracted."}

        query_vectors = self.model.encode(chunks, convert_to_numpy=True, normalize_embeddings=True)
        similarities, indices = self.index.search(query_vectors, k=top_k)

        sources: dict[str, dict[str, Any]] = defaultdict(lambda: {"title": "", "matches": []})

        for query_idx, (score_row, idx_row) in enumerate(zip(similarities, indices)):
            for i in range(top_k):
                score = float(score_row[i])
                if score < threshold:
                    continue

                match_idx = int(idx_row[i])
                if match_idx < 0 or match_idx >= len(self.metadata):
                    continue

                match_data = self.metadata[match_idx]
                arxiv_id = str(match_data.get("arxiv_id", "N/A"))

                if match_idx < len(self.dataset_texts):
                    db_text = self.dataset_texts[match_idx]
                else:
                    db_text = "Text not available."

                sources[arxiv_id]["title"] = str(match_data.get("title", "N/A"))
                sources[arxiv_id]["matches"].append(
                    {
                        "query_chunk_idx": query_idx,
                        "query_text": chunks[query_idx],
                        "db_chunk_idx": int(match_data.get("chunk_id", -1)),
                        "db_text": db_text,
                        "score": score,
                    }
                )

        unique_flagged_chunks = {
            m["query_chunk_idx"] for data in sources.values() for m in data["matches"]
        }

        report: dict[str, Any] = {
            "file_name": file_path.name,
            "total_chunks_analyzed": len(chunks),
            "threshold_used": threshold,
            "total_suspicious_sources": len(sources),
            "total_flagged_chunks": len(unique_flagged_chunks),
            "sources": [],
        }

        sorted_sources = sorted(
            sources.items(),
            key=lambda item: len(item[1]["matches"]),
            reverse=True,
        )

        for arxiv_id, data in sorted_sources:
            avg_score = sum(m["score"] for m in data["matches"]) / len(data["matches"])
            report["sources"].append(
                {
                    "arxiv_id": arxiv_id,
                    "title": data["title"],
                    "match_count": len(data["matches"]),
                    "average_similarity": avg_score,
                    "matches": data["matches"],
                }
            )

        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Antiplagiarism Engine CLI")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model-name", type=str, default="all-mpnet-base-v2")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("backend/core/antiplagiator/artifacts"))
    parser.add_argument("--data-dir", type=Path, default=Path("backend/core/antiplagiator/data/processed"))
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    engine = AntiplagiarismEngine(
        model_name=args.model_name,
        artifacts_dir=args.artifacts_dir,
        data_dir=args.data_dir,
        device=args.device,
    )

    result = engine.analyze_document(args.input, threshold=args.threshold, top_k=args.top_k)

    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()