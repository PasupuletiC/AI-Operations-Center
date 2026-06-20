"""
SQLite Persistence Layer — replaces volatile in-memory deque.

Uses Python's built-in sqlite3 (zero new dependencies).
Stores full history of processed emails, sentiment scores,
and aggregate stats that survive server restarts.
"""
import sqlite3
import os
import json
import logging
from contextlib import contextmanager
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ai_ops.db")
))


def init_db() -> None:
    """Create all tables if they don't exist. Call once on startup."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                id             TEXT PRIMARY KEY,
                processed_at   TEXT NOT NULL,
                subject        TEXT,
                sender         TEXT,
                priority       TEXT,
                email_type     TEXT,
                department     TEXT,
                sentiment      REAL DEFAULT 0.5,
                summary        TEXT,
                ticket_key     TEXT,
                ticket_url     TEXT,
                root_cause     TEXT,
                remediation    TEXT,
                reply_sent     INTEGER DEFAULT 0,
                process_ms     INTEGER DEFAULT 0,
                resolved       INTEGER DEFAULT 0,
                kanban_status  TEXT DEFAULT 'New'
            );

            CREATE TABLE IF NOT EXISTS bot_skips (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                skipped_at   TEXT NOT NULL,
                sender       TEXT
            );

            CREATE TABLE IF NOT EXISTS active_sessions (
                key          TEXT PRIMARY KEY,
                thread_id    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_priority
                ON processed_emails (priority);
            CREATE INDEX IF NOT EXISTS idx_processed_at
                ON processed_emails (processed_at);
        """)
        # Safe migration: add kanban_status if upgrading existing DB
        try:
            conn.execute("ALTER TABLE processed_emails ADD COLUMN kanban_status TEXT DEFAULT 'New'")
            conn.commit()
        except Exception:
            pass  # Column already exists — that's fine
    logger.info(f"[DB] SQLite initialized at {DB_PATH}")


@contextmanager
def get_db():
    """Context manager returning a sqlite3 connection with Row factory."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_email(record: Dict[str, Any]) -> None:
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO processed_emails
            (id, processed_at, subject, sender, priority, email_type,
             department, sentiment, summary, ticket_key, ticket_url,
             root_cause, remediation, reply_sent, process_ms, resolved)
            VALUES
            (:id, :processed_at, :subject, :sender, :priority, :email_type,
             :department, :sentiment, :summary, :ticket_key, :ticket_url,
             :root_cause, :remediation, :reply_sent, :process_ms, :resolved)
        """, {
            **record,
            "remediation": json.dumps(record.get("remediation", [])),
            "reply_sent":  int(record.get("reply_sent", False)),
            "resolved":    int(record.get("resolved", False)),
        })


def fetch_recent_emails(limit: int = 50) -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM processed_emails
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        try:
            d["remediation"] = json.loads(d.get("remediation") or "[]")
        except Exception:
            d["remediation"] = []
        d["reply_sent"] = bool(d.get("reply_sent"))
        results.append(d)
    return results


def fetch_emails_since(hours: int = 24) -> List[Dict]:
    """Fetch emails processed in the last N hours (for digest / escalation)."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM processed_emails
            WHERE processed_at >= ?
            ORDER BY id DESC
        """, (cutoff,)).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        try:
            d["remediation"] = json.loads(d.get("remediation") or "[]")
        except Exception:
            d["remediation"] = []
        d["reply_sent"] = bool(d.get("reply_sent"))
        results.append(d)
    return results


def fetch_unresolved_p1(older_than_minutes: int = 30) -> List[Dict]:
    """Return P1 emails older than N minutes that are still unresolved."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=older_than_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM processed_emails
            WHERE priority = 'P1-critical'
              AND resolved = 0
              AND processed_at <= ?
        """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def mark_resolved(email_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE processed_emails SET resolved = 1 WHERE id = ?",
            (email_id,)
        )


def fetch_sentiment_trend(limit: int = 30) -> List[Dict]:
    """Return recent sentiment scores for the trend chart."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, processed_at, subject, sentiment, priority
            FROM processed_emails
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def update_kanban_status(email_id: str, status: str) -> None:
    """Move a card to a new Kanban column. Status: New|Triaged|In Progress|Resolved"""
    valid = {"New", "Triaged", "In Progress", "Resolved"}
    if status not in valid:
        raise ValueError(f"Invalid kanban status: {status}")
    resolved = 1 if status == "Resolved" else 0
    with get_db() as conn:
        conn.execute(
            "UPDATE processed_emails SET kanban_status=?, resolved=? WHERE id=?",
            (status, resolved, email_id)
        )


def fetch_kanban_board() -> Dict[str, List[Dict]]:
    """Return all incidents grouped by kanban_status for the board."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, processed_at, subject, sender, priority,
                   email_type, department, ticket_key, ticket_url,
                   reply_sent, kanban_status, summary, root_cause
            FROM processed_emails
            ORDER BY id DESC LIMIT 100
        """).fetchall()
    board: Dict[str, List[Dict]] = {
        "New": [], "Triaged": [], "In Progress": [], "Resolved": []
    }
    for row in rows:
        d = dict(row)
        d["reply_sent"] = bool(d.get("reply_sent"))
        col = d.get("kanban_status", "New")
        if col not in board:
            col = "New"
        board[col].append(d)
    return board


def clear_all() -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM processed_emails")
        conn.execute("DELETE FROM bot_skips")


def get_aggregate_stats() -> Dict[str, Any]:
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM processed_emails"
        ).fetchone()[0]

        by_priority = {}
        for row in conn.execute(
            "SELECT priority, COUNT(*) as cnt FROM processed_emails GROUP BY priority"
        ).fetchall():
            key = (row["priority"] or "unknown").split("-")[0].upper()
            by_priority[key] = row["cnt"]

        avg_ms = conn.execute(
            "SELECT AVG(process_ms) FROM processed_emails WHERE process_ms > 0"
        ).fetchone()[0] or 0

        replies = conn.execute(
            "SELECT COUNT(*) FROM processed_emails WHERE reply_sent = 1"
        ).fetchone()[0]

    return {
        "total_processed": total,
        "by_priority":     by_priority,
        "avg_process_ms":  round(avg_ms),
        "replies_sent":    replies,
        "bot_skipped":     0,
    }


def set_active_session(key: str, thread_id: str) -> None:
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO active_sessions (key, thread_id)
            VALUES (?, ?)
        """, (key, thread_id))

def get_active_session(key: str) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT thread_id FROM active_sessions WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

def delete_active_session(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM active_sessions WHERE key = ?", (key,))
