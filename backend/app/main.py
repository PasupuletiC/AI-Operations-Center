import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.api.streaming import stream_router
from app.api.knowledge_routes import knowledge_router
from app.api.voice_routes import router as voice_router
from app.api.webhook_routes import router as webhook_router
from app.api.chatbot_routes import router as chatbot_router
from app.api.analytics_routes import analytics_router, oncall_router
from app.middleware.auth import ApiKeyMiddleware

# Load environment variables FIRST — before any other app imports read os.getenv()
load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ai_ops_center")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown lifecycle handler.
    Runs initialization tasks (e.g., Qdrant collection setup) on startup.
    """
    logger.info("=" * 60)
    logger.info("AI Operations Center v3.0 — Starting up")
    logger.info(f"  Groq key  : {'[OK] set' if os.getenv('GROQ_API_KEY') else '[MISSING]'}")
    logger.info(f"  Gemini key: {'[OK] set' if os.getenv('GEMINI_API_KEY') else '[MISSING]'}")
    auth_key = os.getenv('DASHBOARD_API_KEY', '')
    logger.info(f"  Auth      : {'[OK] API key enabled' if auth_key and not auth_key.startswith('your_') else '[DEV MODE] no auth'}")

    # ── SQLite init ────────────────────────────────────────────────────────────
    try:
        from app.core.db import init_db
        init_db()
        logger.info("  SQLite    : [OK] ai_ops.db ready")
    except Exception as e:
        logger.warning(f"  SQLite    : ⚠  {e}")

    # ── On-Call table migration ─────────────────────────────────────────────────
    try:
        from app.services.oncall_schedule import init_oncall_table
        init_oncall_table()
        logger.info("  OnCall    : [OK] schedule table ready")
    except Exception as e:
        logger.warning(f"  OnCall    : ⚠  {e}")

    # Try to initialize Qdrant and seed knowledge base (non-fatal if unavailable)
    try:
        from app.services.qdrant_client import init_qdrant
        from app.scripts.seed_knowledge_base import seed_knowledge_base
        ok = await init_qdrant()
        logger.info(f"  Qdrant    : {'[OK] connected' if ok else '[WARN] offline (Knowledge Agent LLM-only mode)'}")
        if ok:
            n = await seed_knowledge_base()
            logger.info(f"  KB Seeder : [OK] {n} documents indexed")
    except Exception as e:
        logger.warning(f"  Qdrant    : ⚠  {e}")

    # ── Email Poller (IMAP auto-processing) ───────────────────────────────────
    from app.services.email_poller import email_poller
    from app.agents.manager import build_manager_graph
    import uuid as _uuid

    async def _auto_process(raw_email: str):
        """Process an auto-fetched email through the full agent pipeline."""
        import time as _time
        from app.core.results_store import store_result

        # Extract subject / sender / uid from raw headers (best-effort)
        subject, sender, uid = "(no subject)", "(unknown)", ""
        for line in raw_email.splitlines()[:10]:
            ll = line.lower()
            if ll.startswith("from:"):
                sender = line[5:].strip()
            elif ll.startswith("subject:"):
                subject = line[8:].strip()
            elif ll.startswith("x-uid:") or ll.startswith("uid:"):
                uid = line.split(":", 1)[1].strip()

        graph     = build_manager_graph()
        thread_id = str(_uuid.uuid4())
        initial_state = {
            "raw_email": raw_email, "email_data": {}, "workflow_plan": {},
            "incident_result": {}, "knowledge_results": {},
            "ticket_result": {}, "meeting_result": {},
            "executive_summary": "", "human_approved": False,
        }
        config = {"configurable": {"thread_id": thread_id}}

        t0     = _time.monotonic()
        result = await graph.ainvoke(initial_state, config=config)
        elapsed_ms = int((_time.monotonic() - t0) * 1000)

        # Send automated confirmation reply and capture status
        reply_sent = False
        try:
            from app.services.email_reply import send_reply
            reply_sent = await send_reply(
                original_sender=sender,
                original_subject=subject,
                result=result or {},
                uid=uid,
            )
        except Exception as reply_err:
            logger.warning(f"[EmailReply] Could not send reply: {reply_err}")

        # Store result (with reply status + timing) so frontend can display it
        store_result(subject, sender, result or {},
                     process_ms=elapsed_ms, reply_sent=reply_sent)
        logger.info(
            f"[EmailPoller] Stored: {subject[:50]} | "
            f"reply={'✅' if reply_sent else '❌'} | {elapsed_ms}ms"
        )

        # ── Post-mortem for P1 — fire in background so pipeline isn't blocked ──
        priority = (result or {}).get("email_data", {}).get("priority", "")
        if priority == "P1-critical":
            async def _send_pm():
                try:
                    from app.services.pdf_postmortem import send_postmortem
                    await send_postmortem(subject=subject, result=result or {})
                except Exception as pm_err:
                    logger.warning(f"[PostMortem] Failed (non-fatal): {pm_err}")
            import asyncio as _ao
            _ao.create_task(_send_pm())
            logger.info(f"[PostMortem] 📄 Triggered for P1: {subject[:50]}")

        # ── Self-Learning KB — auto-generate runbook for P1/P2 ──────────────────
        if priority in ("P1-critical", "P2-high"):
            async def _learn():
                try:
                    from app.services.kb_learner import generate_and_save_runbook
                    await generate_and_save_runbook(subject=subject, result=result or {})
                except Exception as kb_err:
                    logger.warning(f"[KB Learner] Failed (non-fatal): {kb_err}")
            import asyncio as _ao2
            _ao2.create_task(_learn())
            logger.info(f"[KB Learner] 🧠 Auto-runbook triggered for {priority}: {subject[:40]}")

        # ── Tier-1 Integrations: Slack • Jira • WhatsApp • Auto-Resolver ─────────
        email_data = (result or {}).get("email_data", {})
        ticket_key = (result or {}).get("ticket_result", {}).get("key", "")
        summary    = (result or {}).get("executive_summary", "")

        async def _tier1_alerts():
            import asyncio as _at

            # 0 — Duplicate detection (check before alerting)
            is_duplicate = False
            duplicate_info = None
            try:
                from app.services.duplicate_detector import find_duplicate
                body_preview = (result or {}).get("executive_summary", "")[:200]
                duplicate_info = find_duplicate(
                    subject=subject, body_preview=body_preview, priority=priority
                )
                if duplicate_info:
                    is_duplicate = True
                    logger.info(
                        f"[DuplicateDetector] 🔄 Duplicate of {duplicate_info['parent_id']}: "
                        f"sim={duplicate_info['similarity']} — {subject[:40]}"
                    )
            except Exception as e:
                logger.debug(f"[DuplicateDetector] Non-fatal: {e}")

            # 1 — Slack rich alert for P1/P2 (skip for duplicates)
            if priority in ("P1-critical", "P2-high") and not is_duplicate:
                try:
                    from app.services.slack_client import slack_service
                    dup_note = f" (dup of {duplicate_info['parent_id']})" if duplicate_info else ""
                    await slack_service.send_p1_alert(
                        subject=subject + dup_note,
                        priority=priority,
                        email_type=email_data.get("email_type", "incident"),
                        department=email_data.get("department", "unknown"),
                        ticket_key=ticket_key,
                        summary=summary,
                    )
                except Exception as e:
                    logger.debug(f"[Slack] Non-fatal: {e}")

            # 2 — Jira ticket (all priorities, skip duplicates)
            if not is_duplicate:
                try:
                    from app.services.jira_client import jira_service
                    jira_result = await jira_service.create_ticket(
                        summary=subject,
                        description=summary or subject,
                        priority=priority,
                        email_type=email_data.get("email_type", "incident"),
                    )
                    if jira_result.get("key") and not jira_result.get("mock"):
                        logger.info(f"[Jira] ✅ Real ticket: {jira_result['key']}")
                except Exception as e:
                    logger.debug(f"[Jira] Non-fatal: {e}")

            # 3 — WhatsApp alert for P1/P2 (skip duplicates)
            if priority in ("P1-critical", "P2-high") and not is_duplicate:
                try:
                    from app.services.whatsapp_client import whatsapp_service
                    await whatsapp_service.send_p1_alert(
                        subject=subject,
                        priority=priority,
                        email_type=email_data.get("email_type", "incident"),
                        department=email_data.get("department", "unknown"),
                        ticket_key=ticket_key,
                    )
                except Exception as e:
                    logger.debug(f"[WhatsApp] Non-fatal: {e}")

            # 4 — On-Call alert for P1 (skip duplicates)
            if priority == "P1-critical" and not is_duplicate:
                try:
                    from app.services.oncall_schedule import alert_oncall
                    await alert_oncall(
                        subject=subject,
                        priority=priority,
                        ticket_key=ticket_key,
                        summary=summary,
                    )
                except Exception as e:
                    logger.debug(f"[OnCall] Non-fatal: {e}")

            # 5 — Auto-Resolver (P3/P4 pattern match or P1/P2 next-steps)
            try:
                from app.services.auto_resolver import try_auto_resolve
                resolved = await try_auto_resolve(
                    subject=subject,
                    sender=sender,
                    priority=priority,
                    result=result or {},
                )
                if resolved:
                    logger.info(f"[AutoResolver] ✅ Auto-resolved: {subject[:50]}")
            except Exception as e:
                logger.debug(f"[AutoResolver] Non-fatal: {e}")

        import asyncio as _at2
        _at2.create_task(_tier1_alerts())

    if email_poller.is_configured():
        logger.info(f"  Email     : [OK] polling {os.getenv('EMAIL_USERNAME')} every {os.getenv('EMAIL_POLL_INTERVAL', '30')}s")
        await email_poller.start(_auto_process)
    else:
        logger.info("  Email     : [--] IMAP not configured (set EMAIL_IMAP_HOST + credentials in .env)")

    # ── Escalation Engine ─────────────────────────────────────────────────────
    import asyncio as _asyncio
    try:
        from app.services.escalation_engine import escalation_loop
        _asyncio.create_task(escalation_loop())
        logger.info("  Escalation: [OK] engine running (checks every 5 min)")
    except Exception as e:
        logger.warning(f"  Escalation: ⚠  {e}")

    # ── SLA Monitor Loop ───────────────────────────────────────────────────
    try:
        from app.services.sla_tracker import sla_monitor_loop
        _asyncio.create_task(sla_monitor_loop())
        logger.info("  SLA       : [OK] monitor running (checks every 2 min)")
    except Exception as e:
        logger.warning(f"  SLA       : ⚠  {e}")

    # ── Daily Digest Scheduler (runs at 08:00 every day) ──────────────────────
    async def _digest_scheduler():
        from datetime import datetime as _dt
        from app.services.digest_service import send_daily_digest
        from app.services.telegram_client import telegram_service
        from app.core.db import get_aggregate_stats
        while True:
            now = _dt.now()
            # Calculate seconds until next 8:00 AM
            target_hour = int(os.getenv("DIGEST_HOUR", "8"))
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now >= next_run:
                from datetime import timedelta as _td
                next_run += _td(days=1)
            wait_secs = (next_run - now).total_seconds()
            logger.info(f"  Digest    : next run in {wait_secs/3600:.1f}h (at {next_run.strftime('%H:%M')})")
            await _asyncio.sleep(wait_secs)
            await send_daily_digest()
            try:
                await telegram_service.send_digest_summary(get_aggregate_stats())
            except Exception:
                pass

    try:
        _asyncio.create_task(_digest_scheduler())
        logger.info("  Digest    : [OK] scheduler active")
    except Exception as e:
        logger.warning(f"  Digest    : ⚠  {e}")

    # ── Weekly Report Scheduler (every Monday 8 AM) ───────────────────────────
    async def _weekly_scheduler():
        from app.services.weekly_report import send_weekly_report
        from datetime import datetime as _dt, timedelta as _td
        while True:
            now_dt = _dt.now()
            # Days until next Monday (0=Mon … 6=Sun); always at least 1 day away
            days_until_monday = (7 - now_dt.weekday()) % 7 or 7
            next_monday = now_dt.replace(hour=8, minute=0, second=0, microsecond=0)
            next_monday += _td(days=days_until_monday)
            wait_secs = (next_monday - now_dt).total_seconds()
            logger.info(f"  Weekly    : next report in {wait_secs/3600:.1f}h ({next_monday.strftime('%a %Y-%m-%d 08:00')})")
            await _asyncio.sleep(wait_secs)
            try:
                await send_weekly_report()
            except Exception as _we:
                logger.error(f"[Weekly] Report failed: {_we}")
    try:
        _asyncio.create_task(_weekly_scheduler())
        logger.info("  Weekly    : [OK] scheduler active (Mondays 08:00)")
    except Exception as e:
        logger.warning(f"  Weekly    : ⚠  {e}")

    logger.info("=" * 60)
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    await email_poller.stop()
    logger.info("AI Operations Center — Shutting down")


app = FastAPI(
    title="AI Operations Center API",
    description="Multi-Agent Enterprise Assistant API",
    version="3.0.0",
    lifespan=lifespan,
)

# Auth middleware (runs before CORS so it can reject unauthenticated preflight properly)
app.add_middleware(ApiKeyMiddleware)

# CORS — allow Next.js frontend on :3000 (and :3001 in case of port conflict)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:3001",
        "http://10.84.83.68:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)

app.include_router(api_router,        prefix="/api")
app.include_router(stream_router,     prefix="/api")
app.include_router(knowledge_router,  prefix="/api")
app.include_router(voice_router,      prefix="/api")
app.include_router(webhook_router,    prefix="/api")
app.include_router(chatbot_router,    prefix="/api")
app.include_router(analytics_router,  prefix="/api/analytics")
app.include_router(oncall_router,     prefix="/api/oncall")


@app.get("/")
def read_root():
    return {"status": "AI Operations Center is running.", "version": "3.0.0"}


@app.get("/health")
def health_check():
    """Quick health check — verifies API keys are loaded."""
    return {
        "status": "healthy",
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
    }
