"""
04_classifier.py — Top-category classifier (updated).

Changes vs original:
  1. Default model updated to BAAI/bge-m3 (unified with engine + FAISS builder)
  2. MLP scaled up: (512, 256, 128) — better for 14k+ samples, 19 classes
  3. compute_sample_weight("balanced") — handles sparse categories gracefully
  4. Filters classes below MIN_SAMPLES before training — prevents sklearn crash
     when early_stopping splits produce empty classes
  5. early_stopping=False — disabled, unstable with highly imbalanced classes
  6. Evaluates on test split in addition to val
  7. Saves per-class metrics to a JSON report alongside the artifact
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import classification_report
from sklearn.neural_network import MLPClassifier
from sklearn.utils.class_weight import compute_sample_weight


LOGGER = logging.getLogger("category_classifier")

MIN_SAMPLES = 30


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
            title    = str(data.get("title",    "")).strip()
            abstract = str(data.get("abstract", "")).strip()
            label    = str(data.get("top_category_name", "")).strip()

            if not label:
                continue
            texts.append(f"{title}. {abstract}".strip())
            labels.append(label)

    return texts, labels


def filter_sparse_classes(
    texts: list[str],
    labels: list[str],
    valid_classes: set[str],
) -> tuple[list[str], list[str]]:
    filtered = [(t, l) for t, l in zip(texts, labels) if l in valid_classes]
    if not filtered:
        return [], []
    t_out, l_out = zip(*filtered)
    return list(t_out), list(l_out)


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
        "--train", type=Path,
        default=Path("backend/core/antiplagiator/data/processed/splits/train.jsonl"),
    )
    parser.add_argument(
        "--val", type=Path,
        default=Path("backend/core/antiplagiator/data/processed/splits/val.jsonl"),
    )
    parser.add_argument(
        "--test", type=Path,
        default=Path("backend/core/antiplagiator/data/processed/splits/test.jsonl"),
    )
    parser.add_argument("--model-name", type=str, default="BAAI/bge-m3")
    parser.add_argument("--device",     type=str, default="auto",
                        choices=["auto", "cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--output", type=Path,
        default=Path("backend/core/antiplagiator/artifacts/category_classifier.pkl"),
    )
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES,
                        help="Drop classes with fewer than this many training samples")
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    np.random.seed(args.seed)

    # ── Load splits ──────────────────────────────────────────────────────────
    LOGGER.info("Loading dataset splits")
    train_texts, train_labels = load_data_from_jsonl(args.train)
    val_texts,   val_labels   = load_data_from_jsonl(args.val)
    LOGGER.info("Train=%d  Val=%d", len(train_texts), len(val_texts))

    has_test = args.test.exists()
    if has_test:
        test_texts, test_labels = load_data_from_jsonl(args.test)
        LOGGER.info("Test=%d", len(test_texts))
    else:
        LOGGER.warning("Test file not found at %s — skipping test evaluation", args.test)
        test_texts, test_labels = [], []

    # ── Log class distribution ───────────────────────────────────────────────
    dist = Counter(train_labels)
    LOGGER.info("Training class distribution:")
    for label, count in sorted(dist.items(), key=lambda x: -x[1]):
        status = "OK" if count >= args.min_samples else "DROP"
        LOGGER.info("  %-45s %4d  [%s]", label, count, status)

    # ── Filter sparse classes ────────────────────────────────────────────────
    valid_classes = {cls for cls, count in dist.items() if count >= args.min_samples}
    dropped = {cls: count for cls, count in dist.items() if cls not in valid_classes}

    if dropped:
        LOGGER.warning(
            "Dropping %d class(es) with fewer than %d training samples: %s",
            len(dropped), args.min_samples, dropped,
        )
        train_texts, train_labels = filter_sparse_classes(train_texts, train_labels, valid_classes)
        val_texts,   val_labels   = filter_sparse_classes(val_texts,   val_labels,   valid_classes)
        if has_test:
            test_texts, test_labels = filter_sparse_classes(test_texts, test_labels, valid_classes)

    LOGGER.info(
        "After filtering: Train=%d  Val=%d  Classes=%d",
        len(train_texts), len(val_texts), len(valid_classes),
    )

    # ── Embed ────────────────────────────────────────────────────────────────
    device = resolve_device(args.device)
    LOGGER.info("Loading embedding model: %s (device=%s)", args.model_name, device)
    embedding_model = SentenceTransformer(args.model_name, device=device)

    LOGGER.info("Encoding train texts ...")
    x_train = embedding_model.encode(
        train_texts, show_progress_bar=True, batch_size=args.batch_size,
        normalize_embeddings=True,
    )
    LOGGER.info("Encoding val texts ...")
    x_val = embedding_model.encode(
        val_texts, show_progress_bar=True, batch_size=args.batch_size,
        normalize_embeddings=True,
    )
    if has_test and test_texts:
        LOGGER.info("Encoding test texts ...")
        x_test = embedding_model.encode(
            test_texts, show_progress_bar=True, batch_size=args.batch_size,
            normalize_embeddings=True,
        )
    else:
        x_test = None

    # ── Class weights ─────────────────────────────────────────────────────────
    sample_weights = compute_sample_weight("balanced", train_labels)

    # ── Train MLP ────────────────────────────────────────────────────────────
    LOGGER.info("Training MLP classifier ...")
    clf = MLPClassifier(
        hidden_layer_sizes=(512, 256, 128),
        activation="relu",
        max_iter=300,
        early_stopping=False,
        random_state=args.seed,
        verbose=args.verbose,
    )
    clf.fit(x_train, train_labels, sample_weight=sample_weights)
    LOGGER.info("Training finished at iteration %d", clf.n_iter_)

    # ── Evaluate ─────────────────────────────────────────────────────────────
    LOGGER.info("=" * 60)
    LOGGER.info("Validation set results:")
    val_predictions = clf.predict(x_val)
    print(classification_report(val_labels, val_predictions))

    reports: dict[str, Any] = {
        "model":           args.model_name,
        "min_samples":     args.min_samples,
        "classes_kept":    sorted(valid_classes),
        "classes_dropped": dropped,
        "val": classification_report(val_labels, val_predictions, output_dict=True),
    }

    if x_test is not None:
        LOGGER.info("=" * 60)
        LOGGER.info("Test set results:")
        test_predictions = clf.predict(x_test)
        print(classification_report(test_labels, test_predictions))
        reports["test"] = classification_report(
            test_labels, test_predictions, output_dict=True
        )

    # ── Save artifact ─────────────────────────────────────────────────────────
    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "classifier":           clf,
        "embedding_model_name": args.model_name,
        "seed":                 args.seed,
        "labels":               sorted(valid_classes),
    }
    joblib.dump(artifact, args.output)
    LOGGER.info("Artifact saved to %s", args.output)

    # ── Save metrics report ───────────────────────────────────────────────────
    report_path = args.output.with_suffix(".metrics.json")
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)
    LOGGER.info("Metrics saved to %s", report_path)


if __name__ == "__main__":
    main()