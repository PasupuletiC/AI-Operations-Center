"""
AI Ops Chatbot — natural language Q&A over your live ops data.

Users can ask questions like:
  "How many P1 incidents this week?"
  "What was the last incident about?"
  "Show me all unresolved tickets"
  "What is the most common issue type?"
  "What's the average resolution time?"

The chatbot fetches live data from SQLite, formats it as context,
then uses the LLM router to generate a natural language answer.

Endpoint: POST /api/chatbot/message
          GET  /api/chatbot/history
"""
import logging
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory chat history (last 50 messages)
_history: List[Dict[str, Any]] = []


def _get_ops_context() -> str:
    """Pull live data from SQLite and format it as LLM context."""
    try:
        from app.core.db import fetch_emails_since, get_aggregate_stats

        stats  = get_aggregate_stats()
        recent = fetch_emails_since(hours=168)  # last 7 days

        total    = stats.get("total_processed", 0)
        by_pri   = stats.get("by_priority", {})
        avg_ms   = stats.get("avg_process_ms", 0)
        replies  = stats.get("replies_sent", 0)

        inc_lines = []
        for e in recent[:20]:
            resolved = "✅ Resolved" if e.get("resolved") else "⏳ Open"
            reply    = "📧 Replied" if e.get("reply_sent") else "—"
            ticket   = e.get("ticket_key") or "—"
            inc_lines.append(
                f"  • [{e.get('priority','?')}] {e.get('subject','')[:60]} "
                f"| Type: {e.get('email_type','?')} "
                f"| Ticket: {ticket} | Status: {resolved} | {reply}"
            )

        by_type_raw: dict = {}
        for e in recent:
            t = e.get("email_type", "unknown")
            by_type_raw[t] = by_type_raw.get(t, 0) + 1
        type_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(
            by_type_raw.items(), key=lambda x: -x[1]))

        from datetime import datetime
        context = f"""
=== AI OPERATIONS CENTER — LIVE DATA CONTEXT ===
Report generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}

AGGREGATE STATS (all time):
  Total incidents processed : {total}
  P1 Critical               : {by_pri.get('P1', 0)}
  P2 High                   : {by_pri.get('P2', 0)}
  P3 Medium                 : {by_pri.get('P3', 0)}
  P4 Low                    : {by_pri.get('P4', 0)}
  Auto-replies sent         : {replies}
  Avg processing time       : {avg_ms}ms

INCIDENT TYPES (last 7 days):
{type_lines or "  No data yet"}

RECENT INCIDENTS (last 7 days — newest first):
{chr(10).join(inc_lines) or "  No incidents in last 7 days"}
=================================================
"""
        return context
    except Exception as e:
        logger.warning(f"[Chatbot] Could not load context: {e}")
        return "No live data available yet. Process some incidents first."



async def _ask_llm(question: str, context: str, history: List[Dict]) -> str:
    """Send question + context to LLM and return answer."""
    try:
        from app.core.llm_router import router as llm_router

        # Build conversation history (last 6 messages)
        conv = []
        for msg in history[-6:]:
            role = "user" if msg["role"] == "user" else "assistant"
            conv.append({"role": role, "content": msg["content"]})

        system_prompt = f"""You are an AI Operations Center assistant.
You have access to live incident data from the system.
Answer questions concisely and helpfully based on the data provided.
Format numbers clearly. If asked for a list, use bullet points.
If data is not available, say so honestly.

{context}"""

        messages = [
            {"role": "system", "content": system_prompt},
            *conv,
            {"role": "user", "content": question},
        ]

        model    = llm_router.select_model(task_type="executive_summary", sensitivity="low")
        response = await llm_router.call_llm(model=model, messages=messages, max_tokens=600)
        return response.strip()

    except Exception as e:
        logger.error(f"[Chatbot] LLM call failed: {e}")
        return (
            "I couldn't process your question right now. "
            "Please make sure the backend is running and try again."
        )


@router.post("/chatbot/message")
async def chatbot_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a message to the AI ops chatbot.

    Body: { "message": "How many P1 incidents this week?" }
    Returns: { "reply": "...", "timestamp": "..." }
    """
    question = (payload.get("message") or "").strip()
    if not question:
        return {"reply": "Please ask me something!", "timestamp": datetime.now().strftime("%H:%M")}

    # Add user message to history
    ts = datetime.now().strftime("%H:%M")
    _history.append({"role": "user", "content": question, "time": ts})

    # Get live context and ask LLM
    context = _get_ops_context()
    reply   = await _ask_llm(question, context, _history[:-1])

    # Add assistant reply to history
    _history.append({"role": "assistant", "content": reply, "time": ts})

    # Keep last 50 messages
    if len(_history) > 50:
        del _history[:2]

    logger.info(f"[Chatbot] Q: {question[:60]} → {reply[:60]}")
    return {"reply": reply, "timestamp": ts}


@router.get("/chatbot/history")
async def chatbot_history() -> Dict[str, Any]:
    """Return chat history for the frontend."""
    return {"history": _history}


@router.delete("/chatbot/history")
async def chatbot_clear() -> Dict[str, Any]:
    """Clear chat history."""
    _history.clear()
    return {"status": "cleared"}


@router.get("/chatbot/suggestions")
async def chatbot_suggestions() -> Dict[str, Any]:
    """Return suggested questions based on current data."""
    return {
        "suggestions": [
            "How many P1 incidents happened this week?",
            "What is the most common incident type?",
            "Show me all unresolved tickets",
            "What was the last critical incident?",
            "What is the average processing time?",
            "How many auto-replies were sent today?",
            "Which department has the most incidents?",
            "Are there any open P1 incidents right now?",
        ]
    }
