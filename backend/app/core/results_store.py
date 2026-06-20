"""
Auto-Email Results Store — dual-layer: fast in-memory deque + SQLite persistence.

On startup, the in-memory deque is pre-seeded from SQLite so the dashboard
is fully populated immediately after a server restart (not empty).

Fix log:
  - get_results() now reads from SQLite on first call after restart
  - store_result() writes to both in-memory deque AND SQLite
  - get_stats() falls back to live DB aggregate when in-memory counters are 0
"""
from collections import deque
from datetime import datetime
from typing import Any, Dict, List
import time
import logging

logger = logging.getLogger(__name__)

# In-memory ring buffer — last 50 results (fast reads for dashboard)
_results: deque = deque(maxlen=50)
_results_loaded = False   # flag: have we seeded from SQLite yet?

# Aggregate stats (in-memory counters for current session)
_stats: Dict[str, Any] = {
    "total_processed": 0,
    "bot_skipped":     0,
    "by_priority":     {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "unknown": 0},
    "by_type":         {},
    "avg_process_ms":  0,
    "replies_sent":    0,
    "session_start":   datetime.now().strftime("%H:%M:%S"),
}
_timing_samples: list = []


def _seed_from_db() -> None:
    """
    Pre-populate the in-memory deque from SQLite on first access.
    This ensures the dashboard shows processed emails immediately after restart.
    """
    global _results_loaded
    if _results_loaded:
        return
    _results_loaded = True
    try:
        from app.core.db import fetch_recent_emails
        rows = fetch_recent_emails(limit=50)
        for row in reversed(rows):   # oldest first so appendleft puts newest at front
            display_rec = {
                **row,
                # Show HH:MM:SS for dashboard display
                "processed_at": (row.get("processed_at") or "")[-8:] or row.get("processed_at", ""),
            }
            _results.appendleft(display_rec)
        if rows:
            logger.info(f"[ResultsStore] Seeded {len(rows)} results from SQLite on startup.")
    except Exception as e:
        logger.debug(f"[ResultsStore] Could not seed from SQLite: {e}")


def _persist(record: Dict[str, Any]) -> None:
    """Write to SQLite — non-fatal if it fails."""
    try:
        from app.core.db import insert_email
        insert_email(record)
    except Exception as e:
        logger.debug(f"[ResultsStore] SQLite write skipped: {e}")


def store_result(
    subject:    str,
    sender:     str,
    result:     Dict[str, Any],
    process_ms: float = 0,
    reply_sent: bool  = False,
) -> None:
    """Called by the email poller after each email is processed."""
    priority   = result.get("email_data", {}).get("priority",   "unknown")
    email_type = result.get("email_data", {}).get("email_type", "unknown")
    department = result.get("email_data", {}).get("department", "unknown")
    sentiment  = result.get("email_data", {}).get("sentiment",  0.5)

    rec = {
        "id":           f"{time.time():.0f}",
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subject":      subject[:80],
        "sender":       sender[:60],
        "priority":     priority,
        "email_type":   email_type,
        "department":   department,
        "sentiment":    float(sentiment) if sentiment else 0.5,
        "summary":      result.get("executive_summary", "")[:300],
        "ticket_key":   result.get("ticket_result",  {}).get("key"),
        "ticket_url":   result.get("ticket_result",  {}).get("url"),
        "root_cause":   result.get("incident_result", {}).get("rca", {}).get("root_cause", ""),
        "remediation":  result.get("incident_result", {}).get("rca", {}).get("remediation_plan", []),
        "reply_sent":   reply_sent,
        "process_ms":   int(process_ms),
        "resolved":     False,
    }

    # Fast in-memory store (dashboard display uses HH:MM:SS)
    display_rec = {**rec, "processed_at": datetime.now().strftime("%H:%M:%S")}
    _results.appendleft(display_rec)

    # Durable SQLite store (persists across restarts)
    _persist(rec)

    # Update aggregate stats
    _stats["total_processed"] += 1
    p_key = priority if priority in _stats["by_priority"] else "unknown"
    _stats["by_priority"][p_key] += 1
    _stats["by_type"][email_type] = _stats["by_type"].get(email_type, 0) + 1
    if reply_sent:
        _stats["replies_sent"] += 1

    if process_ms > 0:
        _timing_samples.append(process_ms)
        if len(_timing_samples) > 100:
            _timing_samples.pop(0)
        _stats["avg_process_ms"] = int(sum(_timing_samples) / len(_timing_samples))


def record_bot_skip() -> None:
    """Call when a bot email is filtered out."""
    _stats["bot_skipped"] += 1


def get_results() -> List[Dict[str, Any]]:
    """
    Return all stored results newest-first.
    On first call after a restart, seeds from SQLite so the list is never empty.
    """
    _seed_from_db()
    return list(_results)


def get_stats() -> Dict[str, Any]:
    """
    Return aggregate processing statistics.
    If this is a fresh session (total=0), pull live numbers from SQLite
    so the counters don't reset to zero after a server restart.
    """
    if _stats["total_processed"] == 0:
        try:
            from app.core.db import get_aggregate_stats
            db_stats = get_aggregate_stats()
            return {
                **_stats,
                "total_processed": db_stats.get("total_processed", 0),
                "by_priority":     db_stats.get("by_priority", _stats["by_priority"]),
                "avg_process_ms":  db_stats.get("avg_process_ms", 0),
                "replies_sent":    db_stats.get("replies_sent", 0),
            }
        except Exception:
            pass
    return {**_stats}


def clear_results() -> None:
    global _results_loaded
    _results.clear()
    _results_loaded = False   # allow re-seed next time
    _stats["total_processed"] = 0
    _stats["bot_skipped"]     = 0
    _stats["replies_sent"]    = 0
    _stats["by_priority"]     = {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "unknown": 0}
    _stats["by_type"]         = {}
    _stats["avg_process_ms"]  = 0
    _timing_samples.clear()
    try:
        from app.core.db import clear_all
        clear_all()
    except Exception:
        pass
