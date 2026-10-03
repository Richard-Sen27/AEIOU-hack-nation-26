"""Local text embeddings (fastembed, ONNX). No network calls besides the one-time model download."""

import os
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL") or "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-small-en": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
}

_lock = threading.Lock()
_model = None


def cache_dir() -> Path:
    raw = os.environ.get("FASTEMBED_CACHE_DIR") or "~/.cache/amber/fastembed"
    return Path(raw).expanduser()


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                path = cache_dir()
                path.mkdir(parents=True, exist_ok=True)
                _model = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=str(path))
    return _model


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


def embed_texts(texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
    """Embed documents. Returns float32 array of shape (n, EMBEDDING_DIM), L2-normalized."""
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    model = get_model()
    vectors = np.asarray(list(model.embed(list(texts), batch_size=batch_size)), dtype=np.float32)
    return _normalize(vectors)


def embed_query(text: str) -> list[float]:
    """Embed a search query (with the model's query instruction prefix, if it has one)."""
    prefix = _QUERY_PREFIXES.get(EMBEDDING_MODEL, "")
    return embed_texts([prefix + text])[0].tolist()
