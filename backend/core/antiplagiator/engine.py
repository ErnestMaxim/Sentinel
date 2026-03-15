from __future__ import annotations

import argparse
import json
import pickle
import re
import textwrap
from collections import defaultdict
from pathlib import Path

import faiss
import fitz
from sentence_transformers import SentenceTransformer


def resolve_device(preferred: str) -> str:
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def read_and_chunk_file(file_path: Path, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

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
        text = text[:match.start()]

    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        if len(chunk_words) >= 50:
            chunks.append(" ".join(chunk_words))

    return chunks


def load_dataset_texts(jsonl_path: Path) -> list[str]:
    texts = []
    if not jsonl_path.exists():
        return texts

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            texts.append(data.get("text", ""))
    return texts


def analyze_document(
    model: SentenceTransformer,
    index: faiss.Index,
    metadata: list[dict],
    dataset_texts: list[str],
    chunks: list[str],
    threshold: float,
    top_k: int = 5,
) -> dict:
    query_vectors = model.encode(chunks, convert_to_numpy=True, normalize_embeddings=True)

    similarities, indices = index.search(query_vectors, k=top_k)

    sources = defaultdict(lambda: {"title": "", "matches": []})

    for query_idx, (score_row, idx_row) in enumerate(zip(similarities, indices)):
        for i in range(top_k):
            score = float(score_row[i])
            if score >= threshold:
                match_idx = idx_row[i]
                match_data = metadata[match_idx]
                arxiv_id = match_data.get("arxiv_id", "N/A")

                db_text = "Text not available."
                if match_idx < len(dataset_texts):
                    db_text = dataset_texts[match_idx]

                sources[arxiv_id]["title"] = match_data.get("title", "N/A")
                sources[arxiv_id]["matches"].append(
                    {
                        "query_chunk_idx": query_idx,
                        "query_text": chunks[query_idx],
                        "db_chunk_idx": match_data.get("chunk_id", -1),
                        "db_text": db_text,
                        "score": score,
                    }
                )

    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description="Document Plagiarism Search Engine")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model-name", type=str, default="all-mpnet-base-v2")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--index-path", type=Path, default=Path("backend/core/antiplagiator/artifacts/faiss_document_index.bin"))
    parser.add_argument("--metadata-path", type=Path, default=Path("backend/core/antiplagiator/artifacts/faiss_metadata.pkl"))
    parser.add_argument("--dataset-path", type=Path, default=Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl"))
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    device = resolve_device(args.device)

    model = SentenceTransformer(args.model_name, device=device)
    index = faiss.read_index(str(args.index_path))

    with args.metadata_path.open("rb") as f:
        metadata = pickle.load(f)

    dataset_texts = load_dataset_texts(args.dataset_path)
    chunks = read_and_chunk_file(args.input)

    if not chunks:
        print("No valid text could be extracted or chunked from the input file.")
        return

    sources = analyze_document(model, index, metadata, dataset_texts, chunks, args.threshold, args.top_k)

    print("\n" + "=" * 80)
    print("PLAGIARISM DETECTION REPORT")
    print("=" * 80)
    print(f"File: {args.input.name}")
    print(f"Total Chunks Analyzed: {len(chunks)}")
    print(f"Similarity Threshold: {args.threshold * 100:.1f}%")
    print(f"Search Depth (Top-K): {args.top_k} matches per chunk\n")

    if not sources:
        print("Result: No significant plagiarism detected.")
        return

    unique_flagged_chunks = set()
    for data in sources.values():
        for m in data["matches"]:
            unique_flagged_chunks.add(m["query_chunk_idx"])

    print(f"Total Suspicious Sources Found: {len(sources)}")
    print(f"Total Input Chunks Flagged: {len(unique_flagged_chunks)} out of {len(chunks)}\n")

    sorted_sources = sorted(sources.items(), key=lambda item: len(item[1]["matches"]), reverse=True)

    wrapper = textwrap.TextWrapper(width=100, initial_indent="      ", subsequent_indent="      ")

    for arxiv_id, data in sorted_sources:
        matches = data["matches"]
        avg_score = sum(m["score"] for m in matches) / len(matches)

        print(f"SOURCE: {data['title']} (ArXiv ID: {arxiv_id})")
        print(f"Matched {len(matches)} chunk(s) with {avg_score * 100:.1f}% average similarity.")

        for m in matches:
            print(
                f"\n  [!] Input Chunk {m['query_chunk_idx'] + 1} -> {m['score'] * 100:.1f}% Match (Matched with DB Chunk {m['db_chunk_idx']})"
            )

            print("\n    --- Text from Input Document ---")
            print(wrapper.fill(m["query_text"]))

            print("\n    --- Text from Dataset Source ---")
            print(wrapper.fill(m["db_text"]))
            print("-" * 80)
        print("\n")


if __name__ == "__main__":
    main()