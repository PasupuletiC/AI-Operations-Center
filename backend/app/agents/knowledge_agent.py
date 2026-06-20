"""
Knowledge Agent — RAG pipeline with full graceful degradation.

Pipeline:
  1. Embed query (sentence-transformers / Ollama / hash fallback)
  2. Search Qdrant (skipped if unavailable → uses LLM knowledge directly)
  3. Rerank with cross-encoder (skipped if unavailable)
  4. Generate answer with Groq (always runs)
"""
import json
from typing import List, Dict, Any
from app.core.llm_router import router
from app.services.embeddings import embed_text
from app.services.qdrant_client import search_documents
from app.services.reranker import rerank


async def query_knowledge_base(query: str, is_sensitive: bool = False) -> Dict[str, Any]:
    """
    RAG pipeline: Embed → Search → Rerank → Generate.
    Gracefully falls back to LLM-only answer if vector DB is unavailable.
    """
    sensitivity = "high" if is_sensitive else "low"

    # ── 1. Embed Query ─────────────────────────────────────────────────────────
    try:
        query_vector = embed_text(query)
    except Exception as e:
        print(f"[Knowledge Agent] Embedding error: {e}")
        query_vector = None

    # ── 2. Search Vector DB ────────────────────────────────────────────────────
    initial_results: List[Dict[str, Any]] = []
    if query_vector:
        try:
            initial_results = await search_documents(query_vector, limit=20)
        except Exception as e:
            print(f"[Knowledge Agent] Qdrant search error: {e}")
            initial_results = []

    # ── 3. Rerank ──────────────────────────────────────────────────────────────
    selected_docs: List[Dict[str, Any]] = []
    if initial_results:
        try:
            documents_texts = [doc["text"] for doc in initial_results]
            top_k_texts = rerank(query, documents_texts, top_k=5)
            for text in top_k_texts:
                for doc in initial_results:
                    if doc["text"] == text and doc not in selected_docs:
                        selected_docs.append(doc)
                        break
        except Exception as e:
            print(f"[Knowledge Agent] Reranker error: {e}")
            selected_docs = initial_results[:5]

    # ── 4. Build Context ───────────────────────────────────────────────────────
    if selected_docs:
        context = "\n\n---\n\n".join(
            [f"Source: {doc['source']}\n{doc['text']}" for doc in selected_docs]
        )
        context_length = len(context.split()) * 1.3
        system_prompt = (
            "You are an expert Knowledge Base Agent. Answer the query based ONLY on the provided context. "
            "Include inline citations referencing the source documents. "
            "If the answer is not in the context, say so explicitly."
        )
        user_content = f"Context:\n{context}\n\nQuery:\n{query}"
    else:
        # No documents found — LLM-only mode
        context_length = 0
        system_prompt = (
            "You are an expert IT knowledge base assistant. The internal knowledge base has no relevant documents "
            "for this query. Answer from your general IT expertise and clearly state that this is based on "
            "general knowledge, not internal documentation."
        )
        user_content = f"Query:\n{query}"

    # ── 5. Generate Answer ─────────────────────────────────────────────────────
    model = router.select_model(
        task_type="rag_generation",
        sensitivity=sensitivity,
        context_length=int(context_length),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        answer = await router.call_llm(model=model, messages=messages, max_tokens=1500)
    except Exception as e:
        answer = f"Error generating answer: {str(e)}"

    sources = list(set([doc["source"] for doc in selected_docs])) if selected_docs else []

    return {
        "answer": answer,
        "sources": sources,
        "model_used": model,
        "documents_found": len(selected_docs),
        "rag_mode": "vector_search" if selected_docs else "llm_only",
    }
