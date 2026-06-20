"""
On-Call Schedule — manages who is responsible for P1 incidents at any given time.

Features:
  - Weekly rotation stored in SQLite
  - Automatically alerts the on-call person via Telegram + WhatsApp for P1
  - REST API to view/set schedule
  - Falls back gracefully if no schedule is configured
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ── DB helpers ─────────────────────────────────────────────────────────────

def init_oncall_table() -> None:
    """Create oncall_schedule table if it doesn't exist."""
    try:
        from app.core.db import get_db
        with get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS oncall_schedule (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    email       TEXT,
                    phone       TEXT,
                    telegram_id TEXT,
                    whatsapp    TEXT,
                    start_date  TEXT NOT NULL,
                    end_date    TEXT NOT NULL,
                    notes       TEXT
                );
            """)
        logger.info("[OnCall] Table initialized")
    except Exception as e:
        logger.error(f"[OnCall] Table init failed: {e}")


def get_current_oncall() -> Optional[Dict[str, Any]]:
    """Return the person currently on call (date range covers today)."""
    try:
        from app.core.db import get_db
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db() as conn:
            row = conn.execute("""
                SELECT * FROM oncall_schedule
                WHERE start_date <= ? AND end_date >= ?
                ORDER BY id DESC LIMIT 1
            """, (today, today)).fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"[OnCall] get_current failed: {e}")
        return None


def get_oncall_schedule(days: int = 30) -> List[Dict[str, Any]]:
    """Return upcoming on-call schedule."""
    try:
        from app.core.db import get_db
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db() as conn:
            rows = conn.execute("""
                SELECT * FROM oncall_schedule
                WHERE end_date >= ?
                ORDER BY start_date ASC
                LIMIT 20
            """, (today,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[OnCall] get_schedule failed: {e}")
        return []


def add_oncall_person(data: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new on-call rotation entry."""
    try:
        from app.core.db import get_db
        with get_db() as conn:
            cur = conn.execute("""
                INSERT INTO oncall_schedule
                (name, email, phone, telegram_id, whatsapp, start_date, end_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("name", ""),
                data.get("email", ""),
                data.get("phone", ""),
                data.get("telegram_id", ""),
                data.get("whatsapp", ""),
                data.get("start_date", ""),
                data.get("end_date", ""),
                data.get("notes", ""),
            ))
            return {"id": cur.lastrowid, "status": "created"}
    except Exception as e:
        logger.error(f"[OnCall] add failed: {e}")
        return {"error": str(e)}


def delete_oncall_entry(entry_id: int) -> bool:
    """Remove an on-call entry."""
    try:
        from app.core.db import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM oncall_schedule WHERE id = ?", (entry_id,))
        return True
    except Exception as e:
        logger.error(f"[OnCall] delete failed: {e}")
        return False


# ── Alert on-call person ────────────────────────────────────────────────────

async def alert_oncall(
    subject:    str,
    priority:   str,
    ticket_key: str = "",
    summary:    str = "",
) -> bool:
    """
    Alert the current on-call person about a P1/P2 incident.
    Tries Telegram personal chat first, then WhatsApp.
    """
    person = get_current_oncall()
    if not person:
        logger.debug("[OnCall] No one on call right now — skipping alert")
        return False

    name   = person.get("name", "On-Call")
    emoji  = "🔴" if "P1" in priority else "🟠"
    msg    = (
        f"{emoji} *{priority.upper()} — YOU ARE ON CALL*\n\n"
        f"👤 Hi {name}, this needs your attention!\n"
        f"📧 {subject[:80]}\n"
        f"{'🎫 Ticket: ' + ticket_key if ticket_key else ''}\n\n"
        f"🕐 {datetime.now().strftime('%H:%M')} — Check the dashboard: http://localhost:3000"
    ).strip()

    sent = False

    # Try Telegram personal message
    tg_id = person.get("telegram_id")
    if tg_id:
        try:
            import httpx, os
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if token:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": tg_id, "text": msg, "parse_mode": "Markdown"}
                    )
                if r.json().get("ok"):
                    logger.info(f"[OnCall] ✅ Telegram alert sent to {name}")
                    sent = True
        except Exception as e:
            logger.debug(f"[OnCall] Telegram failed: {e}")

    # Try WhatsApp
    wa_num = person.get("whatsapp")
    if wa_num and not sent:
        try:
            import os
            from app.services.whatsapp_client import WhatsAppClient
            client = WhatsAppClient()
            # Temporarily override TO for this person
            import os as _os
            orig_to = _os.environ.get("TWILIO_WHATSAPP_TO", "")
            _os.environ["TWILIO_WHATSAPP_TO"] = f"whatsapp:{wa_num}" if not wa_num.startswith("whatsapp:") else wa_num
            sent = await client.send_message(msg)
            _os.environ["TWILIO_WHATSAPP_TO"] = orig_to
            if sent:
                logger.info(f"[OnCall] ✅ WhatsApp alert sent to {name}")
        except Exception as e:
            logger.debug(f"[OnCall] WhatsApp failed: {e}")

    if not sent:
        logger.info(f"[OnCall] ⚠️ Could not reach {name} — no Telegram/WhatsApp configured for this person")

    return sent


oncall_service = type("OnCallService", (), {
    "get_current":  staticmethod(get_current_oncall),
    "get_schedule": staticmethod(get_oncall_schedule),
    "add":          staticmethod(add_oncall_person),
    "delete":       staticmethod(delete_oncall_entry),
    "alert":        staticmethod(alert_oncall),
})()
