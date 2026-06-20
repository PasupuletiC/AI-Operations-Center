"""
Embeddings service — uses sentence-transformers (local, no Ollama needed).

Model: all-MiniLM-L6-v2 (384-dim, fast, great quality for IT docs)
Falls back to a deterministic hash vector if model can't load.
"""
from typing import List

VECTOR_SIZE = 384       # all-MiniLM-L6-v2 output dimension
_model = None
_load_attempted = False


def _get_model():
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("[Embeddings] Loaded sentence-transformers/all-MiniLM-L6-v2 (384-dim)")
    except Exception as e:
        print(f"[Embeddings] WARNING: Could not load model: {e}")
        print("[Embeddings] Falling back to hash-based vectors (no semantic search).")
        _model = None
    return _model


def embed_text(text: str) -> List[float]:
    """Embed a single string. Returns a 384-dim float list."""
    model = _get_model()
    if model is None:
        return _hash_embed(text)
    try:
        return model.encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"[Embeddings] Encode error: {e}")
        return _hash_embed(text)


def embed_documents(texts: List[str]) -> List[List[float]]:
    """Batch embed a list of strings. Faster than calling embed_text in a loop."""
    model = _get_model()
    if model is None:
        return [_hash_embed(t) for t in texts]
    try:
        return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()
    except Exception as e:
        print(f"[Embeddings] Batch encode error: {e}")
        return [_hash_embed(t) for t in texts]


def _hash_embed(text: str) -> List[float]:
    """
    Deterministic fallback: spreads a string's hash across VECTOR_SIZE floats.
    Not semantic — only used when the model fails to load.
    """
    import hashlib, struct
    h = hashlib.sha256(text.encode()).digest()
    # Repeat hash bytes to fill VECTOR_SIZE floats
    extended = (h * ((VECTOR_SIZE * 4 // len(h)) + 1))[:VECTOR_SIZE * 4]
    raw = struct.unpack(f"{VECTOR_SIZE}f", extended)
    # Normalize to unit vector
    mag = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / mag for x in raw]
