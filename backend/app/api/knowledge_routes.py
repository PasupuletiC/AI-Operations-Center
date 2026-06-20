"""
Knowledge Base document upload API.

Endpoints:
  POST /api/knowledge/upload   — upload text/markdown/PDF content into the KB
  GET  /api/knowledge/stats    — see how many docs are indexed
  POST /api/knowledge/search   — direct semantic search (for testing)
"""
import io
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class TextUploadRequest(BaseModel):
    title: str
    content: str
    source: Optional[str] = None   # e.g. "confluence/runbooks", "pdf/sop-2024"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


# ── Shared chunk state (in-memory counter, survives per server session) ────
_doc_count = {"total": 0}


def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """
    Semantic-aware chunking:
    Split on paragraph boundaries first, then enforce max chunk_size words.
    Adds overlap between chunks for better retrieval continuity.
    """
    # Split on double newlines (paragraph boundaries)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_words: List[str] = []

    for para in paragraphs:
        words = para.split()
        if len(current_words) + len(words) <= chunk_size:
            current_words.extend(words)
        else:
            if current_words:
                chunks.append(" ".join(current_words))
                # Add overlap: take last `overlap` words into next chunk
                current_words = current_words[-overlap:] + words
            else:
                current_words = words

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


async def _ingest_document(title: str, content: str, source: str) -> Dict[str, Any]:
    """Core ingestion logic shared by text and file upload."""
    from app.services.qdrant_client import upsert_documents, init_qdrant
    from app.services.embeddings import embed_documents

    await init_qdrant()

    # Semantic chunking
    chunks = _chunk_text(content)
    if not chunks:
        raise ValueError("Document has no content after chunking")

    # Prefix each chunk with title for better semantic matching
    documents = [
        {"text": f"{title}\n\n{chunk}", "source": source}
        for chunk in chunks
    ]

    embeddings = embed_documents([doc["text"] for doc in documents])
    success = await upsert_documents(documents, embeddings)

    if not success:
        raise RuntimeError("Failed to upsert into Qdrant")

    _doc_count["total"] += len(chunks)
    return {
        "status": "indexed",
        "title": title,
        "source": source,
        "chunks_created": len(chunks),
        "total_docs_in_kb": _doc_count["total"],
    }


@knowledge_router.post("/upload")
async def upload_text(request: TextUploadRequest):
    """
    Upload plain text / markdown content into the knowledge base.

    Example:
        POST /api/knowledge/upload
        {"title": "VPN Troubleshooting", "content": "Step 1: ...", "source": "runbook/vpn"}
    """
    try:
        source = request.source or f"upload/{request.title.lower().replace(' ', '-')}"
        result = await _ingest_document(request.title, request.content, source)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@knowledge_router.post("/upload-file")
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(...),
    source: str = Form(default=""),
):
    """
    Upload a .txt or .md file into the knowledge base.
    PDF support requires: pip install pypdf2

    Example:
        POST /api/knowledge/upload-file
        multipart: file=<file.txt>, title="Runbook", source="runbook/vpn"
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    raw = await file.read()

    try:
        if ext in ("txt", "md"):
            content = raw.decode("utf-8", errors="replace")
        elif ext == "pdf":
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(raw))
                content = "\n\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            except ImportError:
                raise HTTPException(
                    status_code=422,
                    detail="PDF support requires: pip install PyPDF2"
                )
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported file type: .{ext}. Use .txt, .md, or .pdf")

        if not content.strip():
            raise HTTPException(status_code=422, detail="File appears to be empty or unreadable")

        src = source or f"file/{filename}"
        result = await _ingest_document(title, content, src)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@knowledge_router.get("/stats")
async def kb_stats():
    """Return knowledge base statistics."""
    try:
        from app.services.qdrant_client import _get_sync, COLLECTION_NAME
        client = _get_sync()
        if not client:
            return {"status": "unavailable", "total_vectors": 0}
        info = client.get_collection(COLLECTION_NAME)
        return {
            "status": "ok",
            "total_vectors": info.vectors_count or 0,
            "indexed_segments": info.segments_count or 0,
            "collection": COLLECTION_NAME,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@knowledge_router.post("/search")
async def direct_search(request: SearchRequest):
    """
    Direct semantic search — for testing the knowledge base.
    """
    try:
        from app.services.embeddings import embed_text
        from app.services.qdrant_client import search_documents
        from app.services.reranker import rerank

        vec = embed_text(request.query)
        results = await search_documents(vec, limit=request.top_k * 4)
        if results:
            texts = [r["text"] for r in results]
            top_texts = rerank(request.query, texts, top_k=request.top_k)
            results = [r for t in top_texts for r in results if r["text"] == t][:request.top_k]

        return {
            "query": request.query,
            "results": [
                {"source": r["source"], "score": round(r.get("score", 0), 4),
                 "text": r["text"][:300] + "..." if len(r["text"]) > 300 else r["text"]}
                for r in results
            ],
            "total_found": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
