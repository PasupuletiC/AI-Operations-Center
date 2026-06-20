"""
Cross-encoder reranker with lazy loading and graceful degradation.

The model is loaded lazily on first call (not at import time),
so the server starts instantly even if sentence-transformers isn't installed.
"""
from typing import List, Optional

_reranker_model = None
_model_load_attempted = False


def _get_reranker():
    global _reranker_model, _model_load_attempted
    if _model_load_attempted:
        return _reranker_model
    _model_load_attempted = True
    try:
        from sentence_transformers import CrossEncoder
        _reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        print("[Reranker] Loaded cross-encoder/ms-marco-MiniLM-L-6-v2")
    except ImportError:
        print("[Reranker] sentence-transformers not installed. Reranking disabled (top-k by index).")
        _reranker_model = None
    except Exception as e:
        print(f"[Reranker] Model load failed: {e}. Reranking disabled.")
        _reranker_model = None
    return _reranker_model


def rerank(query: str, documents: List[str], top_k: int = 5) -> List[str]:
    """
    Re-rank documents using a local cross-encoder.
    Falls back to returning the first top_k documents if model unavailable.
    """
    if not documents:
        return []

    model = _get_reranker()
    if not model:
        return documents[:top_k]

    try:
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs)
        ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked[:top_k]]
    except Exception as e:
        print(f"[Reranker] Prediction error: {e}. Falling back to top-k by index.")
        return documents[:top_k]
