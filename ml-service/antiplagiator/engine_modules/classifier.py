"""
classifier.py — SentinelMLP PyTorch architecture + sklearn-compatible wrapper.

These classes must be importable at the time joblib loads category_classifier_v2.pkl,
because the pickle stores class references as "__main__.SentinelMLP" etc.
(they were defined in a Colab notebook whose __main__ is not uvicorn's __main__).

engine.py calls `register_classifier_classes()` BEFORE joblib.load() so that
`sys.modules["__main__"]` exposes the right classes.
"""

from __future__ import annotations

import sys
import types
import logging

import numpy as np
import torch
import torch.nn as nn

LOGGER = logging.getLogger("antiplagiator.classifier")


# ── Architecture ──────────────────────────────────────────────────────────────

class ResidualBlock(nn.Module):
    def __init__(self, dim: int, dropout: float) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim),
        )
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(x + self.net(x))


class SentinelMLP(nn.Module):
    """
    PyTorch MLP with optional residual connections.
    Architecture: [1024, 512, 256], GELU, BatchNorm, dropout=0.35
    """
    def __init__(
        self,
        in_dim: int,
        hidden_dims: list[int],
        num_classes: int,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden_dims:
            layers += [
                nn.Linear(prev, h),
                nn.BatchNorm1d(h),
                nn.GELU(),
                nn.Dropout(dropout),
            ]
            if prev == h:
                layers.append(ResidualBlock(h, dropout))
            prev = h
        self.trunk = nn.Sequential(*layers)
        self.head  = nn.Linear(prev, num_classes)
        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.trunk(x))


# ── sklearn-compatible wrapper ────────────────────────────────────────────────

class SentinelMLPWrapper:
    """
    Drop-in replacement for the sklearn MLPClassifier artifact.
    Exposes .predict() and .predict_proba() with the same interface.
    Lazy-loads the SentenceTransformer encoder on first call.
    """

    def __init__(
        self,
        mlp_state: dict,
        hidden_dims: list[int],
        embed_model_name: str,
        label_encoder,          # sklearn LabelEncoder
        embed_dim: int = 768,
        dropout: float = 0.0,
    ) -> None:
        self.mlp_state        = mlp_state
        self.hidden_dims      = hidden_dims
        self.embed_model_name = embed_model_name
        self.le               = label_encoder
        self.embed_dim        = embed_dim
        self.thresholds: np.ndarray | None = None
        self._mlp:      SentinelMLP | None = None
        self._embedder  = None
        self._device:   torch.device | None = None

    # ── sklearn compatibility (category_router uses these) ────────────────

    @property
    def classes_(self) -> np.ndarray:
        return self.le.classes_

    def _ensure_loaded(self, device: str = "cpu") -> None:
        if self._mlp is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._device   = torch.device(device)
        self._embedder = SentenceTransformer(
            self.embed_model_name, device=device
        )
        self._embedder.eval()
        num_classes = len(self.le.classes_)
        self._mlp   = SentinelMLP(
            self.embed_dim, self.hidden_dims, num_classes, dropout=0.0
        ).to(self._device)
        self._mlp.load_state_dict(self.mlp_state)
        self._mlp.eval()
        LOGGER.info(
            "SentinelMLPWrapper: loaded MLP (%d classes, device=%s)",
            num_classes, device,
        )

    def _embed(self, texts: list[str]) -> np.ndarray:
        return self._embedder.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    # predict_proba accepts:
    #   - np.ndarray of shape (n, dim)           — pre-computed embeddings
    #   - list/tuple of np.ndarray               — e.g. [embedding] from category_router
    #   - list of str                             — raw texts to encode
    def predict_proba(self, inputs, device: str = "cpu") -> np.ndarray:
        self._ensure_loaded(device)
        if isinstance(inputs, np.ndarray):
            # Already a 2D (or 1D) array of floats
            embs = (inputs if inputs.ndim == 2 else inputs[np.newaxis, :]).astype("float32")
        elif (
            isinstance(inputs, (list, tuple))
            and len(inputs) > 0
            and not isinstance(inputs[0], str)
        ):
            # List of numpy arrays (or numbers) — pre-computed embeddings
            embs = np.array(inputs, dtype="float32")
            if embs.ndim == 1:
                embs = embs[np.newaxis, :]
        else:
            embs = self._embed(list(inputs))
        with torch.no_grad():
            logits = self._mlp(
                torch.tensor(embs, dtype=torch.float32).to(self._device)
            )
        return torch.softmax(logits, dim=-1).cpu().numpy()

    def predict(self, inputs, device: str = "cpu") -> np.ndarray:
        probs = self.predict_proba(inputs, device=device)
        if self.thresholds is not None:
            margins = probs - self.thresholds[np.newaxis, :]
            indices = np.argmax(margins, axis=1)
        else:
            indices = np.argmax(probs, axis=1)
        return self.le.inverse_transform(indices)


# ── Pickle compatibility fix ──────────────────────────────────────────────────

def register_classifier_classes() -> None:
    """
    Register SentinelMLP, SentinelMLPWrapper, and ResidualBlock on the
    __main__ module so that joblib/pickle can find them when loading a .pkl
    that was saved from a Colab notebook (where __main__ was the notebook).

    Call this ONCE before joblib.load() in engine._setup_classifier().
    It is idempotent — safe to call multiple times.
    """
    main = sys.modules.get("__main__")
    if main is None:
        main = types.ModuleType("__main__")
        sys.modules["__main__"] = main

    for cls in (ResidualBlock, SentinelMLP, SentinelMLPWrapper):
        if not hasattr(main, cls.__name__):
            setattr(main, cls.__name__, cls)
            LOGGER.debug("Registered %s on __main__", cls.__name__)
