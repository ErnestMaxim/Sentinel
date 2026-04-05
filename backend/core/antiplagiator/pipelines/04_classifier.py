from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import classification_report
from sklearn.neural_network import MLPClassifier


LOGGER = logging.getLogger("category_classifier")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(message)s")


def load_data_from_jsonl(file_path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data: dict[str, Any] = json.loads(line)
            title = str(data.get("title", "")).strip()
            abstract = str(data.get("abstract", "")).strip()
            label = str(data.get("top_category_name", "")).strip()

            if not label:
                continue
            texts.append(f"{title}. {abstract}".strip())
            labels.append(label)
    return texts, labels


def resolve_device(preferred: str) -> str:
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train top-category classifier")

    parser.add_argument(
        "--train",
        type=Path,
        default=Path("backend/core/antiplagiator/data/processed/splits/train.jsonl"),
    )
    parser.add_argument(
        "--val",
        type=Path,
        default=Path("backend/core/antiplagiator/data/processed/splits/val.jsonl"),
    )

    parser.add_argument("--model-name", type=str, default="malteos/scincl")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/core/antiplagiator/artifacts/category_classifier.pkl"),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    np.random.seed(args.seed)

    LOGGER.info("Loading dataset")
    train_texts, train_labels = load_data_from_jsonl(args.train)
    val_texts, val_labels = load_data_from_jsonl(args.val)
    LOGGER.info("Train=%d  Val=%d", len(train_texts), len(val_texts))

    device = resolve_device(args.device)
    LOGGER.info("Loading embedding model: %s (device=%s)", args.model_name, device)
    embedding_model = SentenceTransformer(args.model_name, device=device)

    LOGGER.info("Encoding train / validation texts")
    x_train = embedding_model.encode(
        train_texts, show_progress_bar=True, batch_size=args.batch_size
    )
    x_val = embedding_model.encode(
        val_texts, show_progress_bar=True, batch_size=args.batch_size
    )

    LOGGER.info("Training MLP classifier")
    clf = MLPClassifier(
        hidden_layer_sizes=(256, 128),
        max_iter=500,
        random_state=args.seed,
    )
    clf.fit(x_train, train_labels)

    LOGGER.info("Evaluating on validation set")
    predictions = clf.predict(x_val)
    print(classification_report(val_labels, predictions))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "classifier": clf,
        "embedding_model_name": args.model_name,
        "seed": args.seed,
        "labels": sorted(set(train_labels)),
    }
    joblib.dump(artifact, args.output)
    LOGGER.info("Artifact saved to %s", args.output)


if __name__ == "__main__":
    main()