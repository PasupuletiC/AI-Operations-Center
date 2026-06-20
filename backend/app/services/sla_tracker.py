"""
SLA Tracker — monitors resolution time targets for each priority level.

SLA Targets:
  P1-critical : 30 minutes
  P2-high     : 2 hours  (120 min)
  P3-medium   : 8 hours  (480 min)
  P4-low      : 24 hours (1440 min)

Runs a background loop every 2 minutes checking for breaches.
Sends Telegram + Slack alerts when SLA is breached or about to breach.

Fix log:
  - Timestamp parser now handles both "T" and " " separators (ISO 8601 & DB format)
  - _alerted_ids now persisted in SQLite (not lost on server restart)
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# SLA targets in minutes
SLA_MINUTES: Dict[str, int] = {
    "P1-critical": 30,
    "P2-high":     120,
    "P3-medium":   480,
    "P4-low":      1440,
}

# Warning threshold — alert at X% of SLA elapsed
WARN_PCT = 0.75   # warn when 75% of SLA time has elapsed


def _parse_dt(value: str) -> Optional[datetime]:
    """
    Parse a datetime string that may use either 'T' or ' ' as separator.
    Handles: '2026-06-19T14:30:00', '2026-06-19 14:30:00', '2026-06-19T14:30:00Z'
    Returns None on failure instead of raising.
    """
    if not value:
        return None
    # Normalize: strip trailing Z, replace T with space
    normalized = value.rstrip("Z").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


# ── SQLite-persisted SLA alert set ────────────────────────────────────────────

def _load_alerted_ids() -> set:
    """Load already-alerted incident IDs from SQLite (survives restarts)."""
    try:
        import sqlite3
        from app.core.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sla_alerts (
                    email_id   TEXT PRIMARY KEY,
                    alerted_at TEXT NOT NULL
                )
            """)
            rows = conn.execute("SELECT email_id FROM sla_alerts").fetchall()
            return {r[0] for r in rows}
    except Exception as e:
        logger.warning(f"[SLA] Could not load alerted IDs: {e}")
        return set()


def _mark_alerted(email_id: str) -> None:
    """Persist that we've alerted for this incident."""
    try:
        import sqlite3
        from app.core.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sla_alerts (
                    email_id   TEXT PRIMARY KEY,
                    alerted_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO sla_alerts (email_id, alerted_at) VALUES (?, ?)",
                (email_id, datetime.utcnow().isoformat())
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[SLA] Could not mark alerted: {e}")


# Loaded once at module import — refreshed from DB on each check
_alerted_ids: set = set()


def get_sla_deadline(priority: str, processed_at: str) -> Optional[str]:
    """Calculate SLA deadline from processed_at timestamp."""
    minutes = SLA_MINUTES.get(priority)
    if not minutes:
        return None
    dt = _parse_dt(processed_at)
    if not dt:
        return None
    deadline = dt + timedelta(minutes=minutes)
    return deadline.strftime("%Y-%m-%d %H:%M:%S")


def get_sla_status(email: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return SLA status for a single incident.
    Returns:
      {
        "target_minutes": int,
        "deadline": str,
        "minutes_remaining": float,
        "pct_elapsed": float,   # 0-100
        "status": "ok"|"warning"|"breached"|"resolved"
      }
    """
    priority     = email.get("priority", "")
    processed_at = email.get("processed_at", "")
    resolved     = bool(email.get("resolved"))
    resolved_at  = email.get("resolved_at")

    target = SLA_MINUTES.get(priority)
    if not target:
        return {"status": "n/a", "target_minutes": 0, "pct_elapsed": 0}

    start = _parse_dt(processed_at)
    if not start:
        return {"status": "unknown", "target_minutes": target, "pct_elapsed": 0}

    deadline = start + timedelta(minutes=target)

    if resolved:
        if resolved_at:
            res_dt = _parse_dt(resolved_at)
            if res_dt:
                elapsed = (res_dt - start).total_seconds() / 60
                met = elapsed <= target
                return {
                    "status":          "resolved_ok" if met else "resolved_breached",
                    "target_minutes":  target,
                    "elapsed_minutes": round(elapsed, 1),
                    "deadline":        deadline.strftime("%Y-%m-%d %H:%M:%S"),
                    "pct_elapsed":     min(100, round(elapsed / target * 100, 1)),
                }
        return {"status": "resolved", "target_minutes": target, "pct_elapsed": 100}

    now       = datetime.now()
    elapsed   = (now - start).total_seconds() / 60
    remaining = (deadline - now).total_seconds() / 60
    pct       = min(100, round(elapsed / target * 100, 1))

    if now >= deadline:
        status = "breached"
    elif pct >= WARN_PCT * 100:
        status = "warning"
    else:
        status = "ok"

    return {
        "status":            status,
        "target_minutes":    target,
        "elapsed_minutes":   round(elapsed, 1),
        "minutes_remaining": round(remaining, 1),
        "deadline":          deadline.strftime("%Y-%m-%d %H:%M:%S"),
        "pct_elapsed":       pct,
    }


def get_all_sla_statuses() -> List[Dict[str, Any]]:
    """Return SLA status for all active (unresolved) incidents."""
    try:
        from app.core.db import fetch_emails_since
        recent = fetch_emails_since(hours=48)  # look at last 48h
        results = []
        for email in recent:
            if email.get("resolved"):
                continue
            sla = get_sla_status(email)
            results.append({
                "id":       email.get("id"),
                "subject":  email.get("subject", "")[:60],
                "priority": email.get("priority"),
                "sla":      sla,
            })
        return results
    except Exception as e:
        logger.error(f"[SLA] get_all_sla_statuses failed: {e}")
        return []


def get_sla_compliance_stats() -> Dict[str, Any]:
    """
    Compute SLA compliance % for the last 7 days.
    Returns per-priority compliance and overall.
    """
    try:
        from app.core.db import fetch_emails_since
        emails = fetch_emails_since(hours=168)  # 7 days

        per_priority: Dict[str, Dict] = {}
        total_resolved = 0
        total_met = 0

        for email in emails:
            priority = email.get("priority", "unknown")
            target   = SLA_MINUTES.get(priority)
            if not target:
                continue

            if priority not in per_priority:
                per_priority[priority] = {"total": 0, "met": 0, "breached": 0}

            per_priority[priority]["total"] += 1

            if email.get("resolved"):
                total_resolved += 1
                processed_at = email.get("processed_at", "")
                resolved_at  = email.get("resolved_at")
                if resolved_at and processed_at:
                    start  = _parse_dt(processed_at)
                    end    = _parse_dt(resolved_at)
                    if start and end:
                        elapsed = (end - start).total_seconds() / 60
                        if elapsed <= target:
                            per_priority[priority]["met"] += 1
                            total_met += 1
                        else:
                            per_priority[priority]["breached"] += 1

        compliance = {}
        for p, d in per_priority.items():
            met = d.get("met", 0)
            tot = d.get("total", 0)
            compliance[p] = {
                "total":      tot,
                "met":        met,
                "compliance": round(met / tot * 100, 1) if tot else 0,
            }

        overall = round(total_met / total_resolved * 100, 1) if total_resolved else 0

        return {
            "overall_compliance": overall,
            "total_resolved":     total_resolved,
            "total_met_sla":      total_met,
            "per_priority":       compliance,
        }
    except Exception as e:
        logger.error(f"[SLA] compliance stats failed: {e}")
        return {"overall_compliance": 0, "per_priority": {}}


# ── Background SLA monitor loop ────────────────────────────────────────────────

async def sla_monitor_loop() -> None:
    """Check SLA breaches every 2 minutes. Fire Telegram + Slack alerts."""
    global _alerted_ids
    # Load persisted alert history on startup
    _alerted_ids = _load_alerted_ids()
    logger.info("[SLA] Monitor started — checking every 2 min")
    while True:
        try:
            await asyncio.sleep(120)  # 2 minutes
            await _check_sla_breaches()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[SLA] Monitor loop error: {e}")
            await asyncio.sleep(60)


async def _check_sla_breaches() -> None:
    """Alert on breached or warning-level incidents."""
    global _alerted_ids
    try:
        from app.core.db import fetch_emails_since
        emails = fetch_emails_since(hours=48)

        for email in emails:
            if email.get("resolved"):
                continue
            eid = email.get("id")
            sla = get_sla_status(email)
            status = sla.get("status")

            if status in ("breached", "warning") and eid not in _alerted_ids:
                _alerted_ids.add(eid)
                _mark_alerted(eid)          # persist to DB
                await _send_sla_alert(email, sla)

    except Exception as e:
        logger.error(f"[SLA] Breach check failed: {e}")


async def _send_sla_alert(email: Dict, sla: Dict) -> None:
    """Fire Telegram + Slack SLA alert."""
    subject   = email.get("subject", "Unknown")[:60]
    priority  = email.get("priority", "")
    status    = sla.get("status")
    remaining = sla.get("minutes_remaining", 0)
    elapsed   = sla.get("elapsed_minutes", 0)

    if status == "breached":
        emoji = "🚨"
        msg   = f"*SLA BREACHED* — {priority.upper()}\n⏱ {elapsed:.0f} min elapsed (limit: {sla['target_minutes']} min)"
    else:
        emoji = "⚠️"
        msg   = f"*SLA WARNING* — {priority.upper()}\n⏱ Only {remaining:.0f} min remaining!"

    text = f"{emoji} {msg}\n📧 {subject}"

    try:
        from app.services.telegram_client import telegram_service
        await telegram_service.send_message(text)
    except Exception:
        pass

    try:
        from app.services.slack_client import slack_service
        await slack_service.send_notification(text)
    except Exception:
        pass

    logger.warning(f"[SLA] {status.upper()} — {priority} | {subject}")
