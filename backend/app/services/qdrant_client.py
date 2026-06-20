"""
Qdrant client — supports both in-memory mode (no server) and remote server.

Priority:
  1. If QDRANT_URL is set and reachable → use remote Qdrant server
  2. Otherwise → use QdrantClient(":memory:") — runs in-process, no Docker needed

In-memory mode is perfect for local dev and demos.
Data is lost on restart, but the knowledge base is re-seeded on each startup.
"""
import os
from typing import List, Dict, Any, Optional

COLLECTION_NAME = "knowledge_base"

try:
    from qdrant_client import QdrantClient, AsyncQdrantClient
    from qdrant_client.http.models import PointStruct, VectorParams, Distance
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False
    print("[Qdrant] qdrant-client not installed.")

# Lazy singletons
_sync_client: Optional[Any] = None   # used for write/init ops (sync methods are simpler)
_async_client: Optional[Any] = None  # used for async search ops
_use_memory = False


def _init_clients():
    global _sync_client, _async_client, _use_memory
    if not HAS_QDRANT:
        return

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

    # Try remote server first
    try:
        test = QdrantClient(url=qdrant_url, timeout=3)
        test.get_collections()   # will raise if unreachable
        _sync_client  = test
        _async_client = AsyncQdrantClient(url=qdrant_url)
        _use_memory   = False
        print(f"[Qdrant] Connected to remote server at {qdrant_url}")
    except Exception:
        # Fall back to in-memory mode
        print("[Qdrant] Server unreachable — switching to in-memory mode (data resets on restart).")
        _sync_client  = QdrantClient(":memory:")
        _async_client = AsyncQdrantClient(":memory:")
        _use_memory   = True


def _get_sync() -> Optional[Any]:
    global _sync_client
    if _sync_client is None:
        _init_clients()
    return _sync_client


def _get_async() -> Optional[Any]:
    global _async_client
    if _async_client is None:
        _init_clients()
    return _async_client


async def init_qdrant() -> bool:
    """
    Create the collection if it doesn't exist yet.
    Returns True on success.
    """
    client = _get_sync()
    if not client:
        return False
    try:
        from app.services.embeddings import VECTOR_SIZE
        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in existing:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            mode = "in-memory" if _use_memory else "remote"
            print(f"[Qdrant] Collection '{COLLECTION_NAME}' created ({mode}, dim={VECTOR_SIZE})")
        return True
    except Exception as e:
        print(f"[Qdrant] init_qdrant error: {e}")
        return False


async def upsert_documents(documents: List[Dict[str, Any]], embeddings: List[List[float]]) -> bool:
    """Insert or update documents. Returns True on success."""
    client = _get_sync()
    if not client:
        return False
    try:
        import hashlib, struct
        points = [
            PointStruct(
                # Deterministic 63-bit ID from document text — avoids overwriting
                # previous batches that also started at i=0
                id=struct.unpack(">Q", hashlib.sha256(doc["text"].encode()).digest()[:8])[0] >> 1,
                vector=embeddings[i],
                payload={"text": doc["text"], "source": doc.get("source", "unknown")},
            )
            for i, doc in enumerate(documents)
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        return True
    except Exception as e:
        print(f"[Qdrant] Upsert error: {e}")
        return False


async def search_documents(query_vector: List[float], limit: int = 20) -> List[Dict[str, Any]]:
    """
    Semantic search. Returns an empty list (not an exception) if unavailable.
    """
    client = _get_sync()
    if not client:
        return []
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=limit,
        )
        return [
            {
                "id":     hit.id,
                "text":   hit.payload.get("text", ""),
                "source": hit.payload.get("source", ""),
                "score":  hit.score,
            }
            for hit in results
        ]
    except Exception as e:
        print(f"[Qdrant] Search error: {e}")
        return []
