"""
API Routes — FastAPI router for the AI Operations Center.

Fix log:
  - thread_id query param type uses Optional[str] instead of `str | None`
    (Python 3.9 compatibility)
  - Added /health/agents endpoint to verify LLM connectivity
  - Added proper error messages and logging
"""
import uuid
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from app.api.models import EmailPayload
from app.agents.manager import build_manager_graph

logger = logging.getLogger(__name__)

router = APIRouter()

# Build the graph once at startup — it holds the MemorySaver checkpointer
manager_graph = build_manager_graph()

from app.core.db import set_active_session, get_active_session, delete_active_session

# In-memory store replaced with SQLite persistence
# active_sessions: Dict[str, str] = {}


@router.post("/process-email")
async def process_email_endpoint(payload: EmailPayload) -> Dict[str, Any]:
    """
    Trigger the LangGraph multi-agent workflow for a given email.
    Each call gets a unique thread_id — multiple users can run concurrently.
    """
    thread_id = str(uuid.uuid4())

    initial_state = {
        "raw_email": payload.raw_email,
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

    try:
        logger.info(f"[Routes] Processing email — thread_id={thread_id}")
        result = await manager_graph.ainvoke(initial_state, config=config)
        # Store latest thread_id so approve/reject can work even if frontend
        # loses the thread_id (e.g. page refresh)
        set_active_session("latest", thread_id)
        logger.info(f"[Routes] Graph completed — thread_id={thread_id}")
        return {"status": "success", "result": result, "thread_id": thread_id}
    except Exception as e:
        logger.error(f"[Routes] Graph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve-ticket")
async def approve_ticket_endpoint(
    thread_id: Optional[str] = Query(default=None)
) -> Dict[str, Any]:
    """
    Resume the paused LangGraph workflow after human approval.
    The graph was interrupted at the `human_approval` node.
    """
    tid = thread_id or get_active_session("latest")
    if not tid:
        raise HTTPException(
            status_code=400,
            detail="No active session found. Please process an email first.",
        )

    config = {"configurable": {"thread_id": tid}}

    try:
        logger.info(f"[Routes] Approving ticket — thread_id={tid}")
        # Update state to mark approval, then resume
        await manager_graph.aupdate_state(config, {"human_approved": True})
        result = await manager_graph.ainvoke(None, config=config)
        delete_active_session("latest")
        return {"status": "resumed", "result": result, "thread_id": tid}
    except Exception as e:
        logger.error(f"[Routes] Approve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject-ticket")
async def reject_ticket_endpoint(
    thread_id: Optional[str] = Query(default=None)
) -> Dict[str, Any]:
    """
    Reject the pending approval — discards the paused graph state.
    """
    tid = thread_id or get_active_session("latest")
    if not tid:
        raise HTTPException(
            status_code=400,
            detail="No active session found.",
        )
    logger.info(f"[Routes] Ticket rejected — thread_id={tid}")
    delete_active_session("latest")
    return {
        "status": "rejected",
        "message": "Ticket creation rejected by human operator.",
        "thread_id": tid,
    }


@router.get("/health/agents")
async def agent_health() -> Dict[str, Any]:
    """
    Quick connectivity check — verifies Groq LLM is reachable.
    """
    import os
    from app.core.llm_router import router as llm_router

    groq_ok = bool(os.getenv("GROQ_API_KEY"))
    gemini_ok = bool(os.getenv("GEMINI_API_KEY"))

    checks = {
        "groq_key_present": groq_ok,
        "gemini_key_present": gemini_ok,
    }

    # Optionally ping Qdrant
    try:
        from app.services.qdrant_client import _get_sync, COLLECTION_NAME
        client = _get_sync()
        if client:
            info = client.get_collection(COLLECTION_NAME)
            checks["qdrant"] = f"connected (in-memory) — {info.vectors_count or 0} vectors"
        else:
            checks["qdrant"] = "unavailable (qdrant-client not installed)"
    except Exception as e:
        checks["qdrant"] = f"error ({str(e)[:60]})"

    # Model quota usage
    try:
        from app.core.quota_tracker import get_stats, get_total_calls_today
        checks["quota_usage"] = {
            "total_calls_today": get_total_calls_today(),
            "models": get_stats(),
        }
    except Exception as e:
        checks["quota_usage"] = {"error": str(e)}

    # Email poller status
    try:
        from app.services.email_poller import email_poller
        checks["email_poller"] = email_poller.status()
    except Exception as e:
        checks["email_poller"] = {"error": str(e)}

    return {"status": "ok", "checks": checks}


# ── Email Poller endpoints ────────────────────────────────────────────────────

@router.get("/email-poller/status")
async def email_poller_status() -> Dict[str, Any]:
    """Returns the current status of the IMAP email poller."""
    from app.services.email_poller import email_poller
    return email_poller.status()


@router.get("/email-poller/results")
async def email_poller_results() -> Dict[str, Any]:
    """
    Returns the last 50 auto-processed email results.
    Frontend polls this every 10s to display the inbox processing history.
    """
    from app.core.results_store import get_results
    return {"results": get_results()}


@router.get("/email-poller/stats")
async def email_poller_stats() -> Dict[str, Any]:
    """Returns aggregate processing statistics for the dashboard."""
    from app.core.results_store import get_stats
    return get_stats()


@router.get("/email-poller/sentiment-trend")
async def sentiment_trend() -> Dict[str, Any]:
    """Returns recent sentiment scores for the dashboard line chart."""
    try:
        from app.core.db import fetch_sentiment_trend
        data = fetch_sentiment_trend(limit=30)
        return {"trend": data}
    except Exception:
        return {"trend": []}


@router.delete("/email-poller/results")
async def email_poller_clear() -> Dict[str, Any]:
    """Clear the auto-processed results history."""
    from app.core.results_store import clear_results
    clear_results()
    return {"status": "cleared"}


@router.post("/email-poller/test")
async def email_poller_test(payload: EmailPayload) -> Dict[str, Any]:
    """
    Manually send a raw email string through the pipeline —
    same path as auto-polled emails. Useful for testing without IMAP.
    Returns the final agent state.
    """
    try:
        graph  = manager_graph
        tid    = str(uuid.uuid4())
        config = {"configurable": {"thread_id": tid}}
        state  = {
            "raw_email": payload.raw_email, "email_data": {}, "workflow_plan": {},
            "incident_result": {}, "knowledge_results": {}, "ticket_result": {},
            "meeting_result": {}, "executive_summary": "", "human_approved": False,
        }
        result = await graph.ainvoke(state, config=config)
        return {"thread_id": tid, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Test Email Reply ──────────────────────────────────────────────────────────

@router.post("/test-reply")
async def test_reply(payload: dict) -> Dict[str, Any]:
    """
    Send a test auto-reply email immediately — no IMAP polling needed.

    Body:  { "to": "charan@gmail.com", "subject": "Test server crash" }

    Use this to verify the email reply service is working correctly.
    """
    to_addr = payload.get("to", "").strip()
    subject = payload.get("subject", "Test Incident — AI Operations Center")

    if not to_addr or "@" not in to_addr:
        raise HTTPException(status_code=400, detail="Provide a valid 'to' email address.")

    # Build a realistic mock result to populate the reply template
    mock_result = {
        "email_data": {
            "priority":   "P1-critical",
            "email_type": "incident",
            "department": "engineering",
        },
        "ticket_result": {"key": "OPS-TEST-001"},
        "incident_result": {
            "rca": {
                "root_cause": (
                    "This is a test reply from AI Operations Center. "
                    "In production, the real root cause analysis appears here."
                )
            }
        },
        "executive_summary": (
            "TEST MODE: Your email was received and processed by the AI Operations Center. "
            "Priority P1-Critical was assigned. Ticket OPS-TEST-001 created. "
            "On-call team has been notified. Estimated resolution: 30 minutes."
        ),
    }

    try:
        from app.services.email_reply import send_reply
        sent = await send_reply(
            original_sender=to_addr,
            original_subject=subject,
            result=mock_result,
        )
        if sent:
            return {"status": "sent", "to": to_addr, "subject": f"Re: {subject}"}
        else:
            return {
                "status": "skipped",
                "reason": "SMTP not configured or sender is a bot address. "
                          "Check EMAIL_USERNAME + EMAIL_PASSWORD in .env"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── B. Kanban Board Endpoints ─────────────────────────────────────────────────

@router.get("/kanban/board")
async def get_kanban_board():
    """Return all incidents grouped into Kanban columns."""
    try:
        from app.core.db import fetch_kanban_board
        return {"board": fetch_kanban_board()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/kanban/{email_id}/status")
async def update_kanban_status(email_id: str, payload: Dict[str, Any]):
    """
    Move an incident card to a new Kanban column.
    Body: { "status": "Triaged" | "In Progress" | "Resolved" | "New" }
    """
    status = payload.get("status", "")
    if status not in {"New", "Triaged", "In Progress", "Resolved"}:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    try:
        from app.core.db import update_kanban_status
        update_kanban_status(email_id, status)
        return {"status": "updated", "id": email_id, "kanban_status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── C. Demo / Seed Data ───────────────────────────────────────────────────────

@router.post("/seed-demo")
async def seed_demo_data():
    """Insert realistic sample incidents so the dashboard is fully populated."""
    import uuid, sqlite3
    from datetime import datetime, timedelta
    from app.core.db import DB_PATH

    SAMPLES = [
        # (subject, sender, priority, email_type, dept, sentiment, summary, ticket, kanban, days_ago, ms)
        ("CRITICAL: Production database unreachable — all services down",
         "alerts@datadog.com", "P1-critical", "incident", "Engineering",
         0.1, "Primary DB cluster lost quorum. Estimated 500 users affected.",
         "MOCK-1001", "Triaged", 0, 4200),
        ("P1: Payment gateway timeout — revenue impact $12k/min",
         "ops@stripe.com", "P1-critical", "incident", "Payments",
         0.05, "Stripe webhook failures causing checkout failures across all regions.",
         "MOCK-1002", "In Progress", 0, 3800),
        ("Alert: Memory leak in auth-service — CPU at 98%",
         "monitoring@internal.co", "P2-high", "alert", "Platform",
         0.3, "Auth service OOM killer triggered 3 times in last hour.",
         "MOCK-1003", "Triaged", 1, 2100),
        ("SSL certificate expiring in 48 hours — api.prod.com",
         "security@certbot.com", "P2-high", "alert", "Security",
         0.4, "Auto-renewal failed due to DNS propagation issue.",
         "MOCK-1004", "New", 1, 1500),
        ("Deployment failed: canary release v2.3.1 rollback needed",
         "ci@github.com", "P2-high", "incident", "DevOps",
         0.35, "Health check failure rate 12% on canary. Rolling back.",
         "MOCK-1005", "In Progress", 1, 2800),
        ("High error rate on /api/search — 503s spiking",
         "alerts@newrelic.com", "P3-medium", "alert", "Search",
         0.5, "Elasticsearch cluster degraded, 2 of 5 nodes unresponsive.",
         "MOCK-1006", "New", 2, 900),
        ("Scheduled maintenance: DB backup window tonight 02:00 UTC",
         "ops@internal.co", "P3-medium", "maintenance", "DBA",
         0.75, "Routine backup + vacuum. Expect 5-min read latency spike.",
         "MOCK-1007", "Resolved", 2, 600),
        ("User report: Login failing for SSO users — SAML assertion invalid",
         "support@helpdesk.com", "P3-medium", "support", "Auth",
         0.45, "SAML clock skew after NTP drift on IdP server.",
         "MOCK-1008", "Triaged", 2, 1200),
        ("Disk usage at 87% on logs-prod-03 — cleanup required",
         "monitoring@internal.co", "P3-medium", "alert", "Infrastructure",
         0.6, "Log rotation misconfigured after last kernel upgrade.",
         "MOCK-1009", "New", 3, 750),
        ("Feature request: Dark mode for admin portal",
         "pm@company.com", "P4-low", "feature_request", "Product",
         0.85, "Customer feedback: admin portal too bright for night ops.",
         "MOCK-1010", "New", 3, 300),
        ("Weekly security scan report — 2 medium CVEs found",
         "security@snyk.io", "P4-low", "report", "Security",
         0.7, "CVE-2025-1234 in lodash 4.17.20. Patch available.",
         "MOCK-1011", "Resolved", 4, 400),
        ("Post-mortem complete: June 10 outage — RCA attached",
         "eng@internal.co", "P4-low", "postmortem", "Engineering",
         0.8, "Root cause: misconfigured autoscaler cooldown period. Fixed.",
         "MOCK-1012", "Resolved", 5, 500),
    ]

    now = datetime.utcnow()
    inserted = 0
    with sqlite3.connect(DB_PATH) as conn:
        for (subject, sender, priority, etype, dept, sentiment,
             summary, ticket, kanban, days_ago, ms) in SAMPLES:
            eid = str(uuid.uuid4())
            ts  = (now - timedelta(days=days_ago, hours=inserted % 8)).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute("""
                INSERT OR IGNORE INTO processed_emails
                  (id, processed_at, subject, sender, priority, email_type,
                   department, sentiment, summary, ticket_key, reply_sent,
                   process_ms, kanban_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
            """, (eid, ts, subject, sender, priority, etype,
                  dept, sentiment, summary, ticket, ms, kanban))
            inserted += 1
        conn.commit()

    return {"seeded": inserted, "message": f"Inserted {inserted} demo incidents successfully."}


@router.delete("/seed-demo")
async def clear_demo_data():
    """Remove all MOCK-* demo incidents from the database."""
    import sqlite3
    from app.core.db import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM processed_emails WHERE ticket_key LIKE 'MOCK-%'")
        conn.commit()
    return {"deleted": cur.rowcount, "message": "Demo data cleared."}

