"""
SSE Streaming — Real-time agent event stream via Server-Sent Events.

The frontend connects with EventSource('/api/stream-email') and receives
one JSON event per agent node as it completes, enabling a true live feed.
"""
import uuid
import json
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.api.models import EmailPayload
from app.agents.manager import build_manager_graph

logger = logging.getLogger(__name__)
stream_router = APIRouter()

# Reuse the same compiled graph as the main router (import it lazily to avoid circular deps)
_stream_graph = None

def _get_graph():
    global _stream_graph
    if _stream_graph is None:
        _stream_graph = build_manager_graph()
    return _stream_graph


def _sse(event: str, data: Dict[str, Any]) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _run_stream(raw_email: str, thread_id: str) -> AsyncGenerator[str, None]:
    """
    Run the LangGraph pipeline and yield SSE events as each node finishes.
    Uses astream_events (LangGraph ≥ 0.2) to get per-node callbacks.
    """
    graph = _get_graph()
    initial_state = {
        "raw_email": raw_email,
        "email_data": {},
        "workflow_plan": {},
        "incident_result": {},
        "knowledge_results": {},
        "ticket_result": {},
        "meeting_result": {},
        "executive_summary": "",
        "human_approved": False,
    }
    config = {"configurable": {"thread_id": thread_id}}

    # Map internal node names → user-friendly display labels
    NODE_LABELS = {
        "classify_email":   ("Email Agent",     "📧 Classifying incident type and priority..."),
        "plan_workflow":    ("Manager Agent",   "🧠 Planning agent workflow..."),
        "parallel_agents":  ("Parallel Agents", "⚡ Running Incident + Knowledge agents in parallel..."),
        "incident_only":    ("Incident Agent",  "🔍 Running two-stage incident analysis (Triage + RCA)..."),
        "knowledge_only":   ("Knowledge Agent", "📚 Searching knowledge base (RAG)..."),
        "human_approval":   ("Human Gate",      "⏸️ P1/P2 detected — awaiting human approval..."),
        "ticket_agent":     ("Ticket Agent",    "🎫 Creating Jira ticket..."),
        "meeting_agent":    ("Meeting Agent",   "📅 Scheduling follow-up meeting..."),
        "executive_summary":("Summary Agent",   "✍️ Generating executive summary..."),
    }

    yield _sse("start", {"thread_id": thread_id, "message": "Pipeline started"})

    try:
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            kind = event.get("event", "")
            name = event.get("name", "")

            # Node started
            if kind == "on_chain_start" and name in NODE_LABELS:
                agent_name, message = NODE_LABELS[name]
                yield _sse("agent_start", {
                    "node": name,
                    "agent": agent_name,
                    "message": message,
                })
                await asyncio.sleep(0)  # yield control to event loop

            # Node finished — emit its output
            elif kind == "on_chain_end" and name in NODE_LABELS:
                agent_name, _ = NODE_LABELS[name]
                output = event.get("data", {}).get("output", {})

                # Build a human-readable completion message from the output
                done_msg = _build_done_message(name, output)

                yield _sse("agent_done", {
                    "node": name,
                    "agent": agent_name,
                    "message": done_msg,
                    "data": output,
                })
                await asyncio.sleep(0)

        # Stream complete — fetch final state
        final_state = await graph.aget_state(config)
        values = final_state.values if hasattr(final_state, "values") else {}

        # Check if paused at human_approval
        next_nodes = final_state.next if hasattr(final_state, "next") else []
        if "human_approval" in (next_nodes or []) or "ticket_agent" in (next_nodes or []):
            yield _sse("paused", {
                "message": "Paused for human approval",
                "thread_id": thread_id,
                "result": values,
            })
        else:
            yield _sse("complete", {
                "message": "All agents finished",
                "thread_id": thread_id,
                "result": values,
            })

    except Exception as e:
        logger.error(f"[SSE Stream] Error: {e}")
        yield _sse("error", {"message": str(e)})


def _build_done_message(node: str, output: Dict[str, Any]) -> str:
    """Turn node output into a concise human-readable completion message."""
    if node == "classify_email":
        ed = output.get("email_data", {})
        # Detect failed LLM call — email_data will have "error" key instead of classification fields
        if "error" in ed or not ed.get("email_type"):
            err = ed.get("error", "LLM call failed — check API key")
            return f"❌ Classification failed: {str(err)[:120]}"
        return f"✅ Classified as {ed.get('email_type')} — Priority: {ed.get('priority')} ({ed.get('department')} dept)"
    elif node == "plan_workflow":
        plan = output.get("workflow_plan", {})
        if "error" in plan:
            return f"❌ Planning failed: {plan.get('error', 'unknown')}"
        parts = []
        if plan.get("needs_incident_analysis"): parts.append("incident analysis")
        if plan.get("needs_ticket"):            parts.append("Jira ticket")
        if plan.get("needs_meeting"):           parts.append("meeting")
        if plan.get("needs_knowledge_search"):  parts.append("knowledge search")
        return f"✅ Workflow planned: {', '.join(parts) or 'executive summary only'}"
    elif node == "incident_agent" or node == "incident_only":
        res = output.get("incident_result", {})
        if "error" in res:
            return f"❌ Incident analysis failed: {res.get('error', '')[:80]}"
        rca = res.get("rca", {})
        return f"✅ RCA complete: {str(rca.get('root_cause', 'see summary'))[:100]}"
    elif node == "knowledge_agent" or node == "knowledge_only":
        n = output.get("knowledge_results", {}).get("documents_found", 0)
        mode = output.get("knowledge_results", {}).get("rag_mode", "llm_only")
        return f"✅ Knowledge search done — {n} docs found ({mode})"
    elif node == "parallel_agents":
        # Both incident + knowledge ran together
        inc = output.get("incident_result", {})
        kb = output.get("knowledge_results", {})
        rca_summary = inc.get("rca", {}).get("root_cause", "") if inc else ""
        kb_docs = kb.get("documents_found", 0) if kb else 0
        parts = []
        if rca_summary: parts.append(f"RCA: {str(rca_summary)[:60]}")
        if kb_docs:     parts.append(f"{kb_docs} KB docs found")
        return f"✅ Parallel agents done — {' | '.join(parts) or 'analysis complete'}"
    elif node == "ticket_agent":
        res = output.get("ticket_result", {})
        if "error" in res:
            return f"❌ Ticket creation failed: {res.get('error', '')[:80]}"
        return f"✅ Ticket created: {res.get('key', 'N/A')}"
    elif node == "meeting_agent":
        res = output.get("meeting_result", {})
        return f"✅ Meeting scheduled (event: {res.get('event_id', 'N/A')})"
    elif node == "executive_summary":
        summ = output.get("executive_summary", "")
        if not summ:
            return "❌ Executive summary failed — check API key / LLM quota"
        return f"✅ Executive summary ready ({len(summ)} chars)"
    elif node == "human_approval":
        return "⏸️ Workflow paused — awaiting human decision in dashboard"
    return f"✅ {node} complete"


@stream_router.post("/stream-email")
async def stream_email_endpoint(payload: EmailPayload, request: Request):
    """
    SSE endpoint: POST the email, receive real-time agent events.
    Frontend uses EventSource with a fetch+ReadableStream since EventSource
    doesn't support POST — we return text/event-stream from a POST body.
    """
    thread_id = str(uuid.uuid4())
    logger.info(f"[SSE] Starting stream — thread_id={thread_id}")

    async def event_generator():
        async for chunk in _run_stream(payload.raw_email, thread_id):
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info(f"[SSE] Client disconnected — thread_id={thread_id}")
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",      # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
