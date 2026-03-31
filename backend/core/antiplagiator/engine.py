from __future__ import annotations

import argparse
import difflib
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

    def _read_and_chunk_file(self, file_path: Path, chunk_size: int = 100, overlap: int = 30) -> list[str]:
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

        text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        match = re.search(r"\b(References|Bibliography)\b", text, flags=re.IGNORECASE | re.MULTILINE)
        if match and match.start() > (len(text) * 0.75):
            text = text[: match.start()]

        words = text.split()
        chunks: list[str] = []
        step = chunk_size - overlap

        for i in range(0, len(words), step):
            chunk_words = words[i : i + chunk_size]
            if len(chunk_words) >= 20:
                chunks.append(" ".join(chunk_words))

        return chunks

    def _extract_exact_matches(self, query_text: str, db_text: str, min_words: int = 6) -> list[str]:
       
        clean_query = re.sub(r'\s+', ' ', query_text).strip()
        clean_db = re.sub(r'\s+', ' ', db_text).strip()

        matcher = difflib.SequenceMatcher(None, clean_query.lower(), clean_db.lower())
        exact_phrases = set()
        
        for match in matcher.get_matching_blocks():
            matched_string = clean_query[match.a : match.a + match.size].strip()
            
            if len(matched_string.split()) >= min_words:
                exact_phrases.add(matched_string)
                
        return list(exact_phrases)

    def analyze_document(self, file_path: Path, threshold: float = 0.70, top_k: int = 5) -> dict[str, Any]:
        chunks = self._read_and_chunk_file(file_path)
        if not chunks:
            return {"error": "No valid text could be extracted."}

        total_words_in_doc = sum(len(chunk.split()) for chunk in chunks)
        if total_words_in_doc == 0:
            return {"error": "Document is empty."}

        query_vectors = self.model.encode(chunks, convert_to_numpy=True, normalize_embeddings=True)
        similarities, indices = self.index.search(query_vectors, k=top_k)

        sources: dict[str, dict[str, Any]] = defaultdict(lambda: {"title": "", "matches": []})

        plagiarized_words_weighted_sum = 0.0
        unique_flagged_chunks = set()

        for query_idx, (score_row, idx_row) in enumerate(zip(similarities, indices)):
            chunk_word_count = len(chunks[query_idx].split())
            chunk_already_flagged = False

            for i in range(top_k):
                raw_cosine_score = float(score_row[i])
                cosine_sim = max(0.0, min(1.0, raw_cosine_score))

                if cosine_sim < threshold:
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

                exact_copied_phrases = self._extract_exact_matches(chunks[query_idx], db_text)

                sources[arxiv_id]["title"] = str(match_data.get("title", "N/A"))
                sources[arxiv_id]["matches"].append(
                    {
                        "query_chunk_idx": query_idx,
                        "query_text": chunks[query_idx],
                        "db_chunk_idx": int(match_data.get("chunk_id", -1)),
                        "db_text": db_text,
                        "cosine_similarity": round(cosine_sim, 4),
                        "match_percentage": round(cosine_sim * 100, 2),
                        "exact_copied_phrases": exact_copied_phrases
                    }
                )

                if not chunk_already_flagged:
                    plagiarized_words_weighted_sum += (cosine_sim * chunk_word_count)
                    unique_flagged_chunks.add(query_idx)
                    chunk_already_flagged = True

        global_plagiarism_score = (plagiarized_words_weighted_sum / total_words_in_doc) * 100

        report: dict[str, Any] = {
            "file_name": file_path.name,
            "document_stats": {
                "total_words": total_words_in_doc,
                "total_chunks_analyzed": len(chunks)
            },
            "analysis_config": {
                "threshold_used": threshold,
                "metric": "Cosine Similarity"
            },
            "global_plagiarism_score_percent": round(global_plagiarism_score, 2),
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
            avg_score = sum(m["match_percentage"] for m in data["matches"]) / len(data["matches"])
            report["sources"].append(
                {
                    "arxiv_id": arxiv_id,
                    "title": data["title"],
                    "match_count": len(data["matches"]),
                    "average_similarity_percent": round(avg_score, 2),
                    "matches": data["matches"],
                }
            )

        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Antiplagiarism Engine CLI")
    parser.add_argument("--input", type=Path, required=True, help="Path to the PDF or text file to analyze")
    parser.add_argument("--output", type=Path, default=None, help="Path to save the JSON report (e.g., report.json)")
    parser.add_argument("--model-name", type=str, default="all-mpnet-base-v2")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("backend/core/antiplagiator/artifacts"))
    parser.add_argument("--data-dir", type=Path, default=Path("backend/core/antiplagiator/data/processed"))
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--pretty", action="store_true", help="Print or save JSON with indentation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    engine = AntiplagiarismEngine(
        model_name=args.model_name,
        artifacts_dir=args.artifacts_dir,
        data_dir=args.data_dir,
        device=args.device,
    )

    LOGGER.info(f"Analyzing {args.input.name}...")
    result = engine.analyze_document(args.input, threshold=args.threshold, top_k=args.top_k)

    indent = 2 if args.pretty else None

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        LOGGER.info(f"Report successfully saved to {args.output.absolute()}")
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()