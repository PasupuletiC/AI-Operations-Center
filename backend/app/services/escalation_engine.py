"""
Escalation Engine — monitors unresolved P1/P2 incidents and re-alerts.

Fix: _escalated_ids now persisted in SQLite so backend restarts
don't re-send duplicate Telegram/email alerts.
"""
import os
import asyncio
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

# Max escalations per incident before silencing (prevents eternal spam)
MAX_ESCALATIONS_PER_INCIDENT = 2


def _get_escalation_count(email_id: str) -> int:
    """Return how many times this incident has been escalated (from DB)."""
    try:
        import sqlite3
        from app.core.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            # Create escalation tracking table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS escalation_log (
                    email_id    TEXT NOT NULL,
                    escalated_at TEXT NOT NULL,
                    PRIMARY KEY (email_id, escalated_at)
                )
            """)
            cur = conn.execute(
                "SELECT COUNT(*) FROM escalation_log WHERE email_id = ?", (email_id,)
            )
            return cur.fetchone()[0]
    except Exception as e:
        logger.warning(f"[Escalation] Could not check escalation count: {e}")
        return 0


def _mark_escalated(email_id: str) -> None:
    """Record that this incident was escalated."""
    try:
        import sqlite3
        from app.core.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS escalation_log (
                    email_id    TEXT NOT NULL,
                    escalated_at TEXT NOT NULL,
                    PRIMARY KEY (email_id, escalated_at)
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO escalation_log (email_id, escalated_at) VALUES (?, ?)",
                (email_id, datetime.utcnow().isoformat())
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Escalation] Could not mark escalated: {e}")


def _build_escalation_html(subject: str, processed_at: str,
                            ticket_key: str, minutes: int) -> str:
    ticket_line = f"<b>Ticket:</b> {ticket_key}<br>" if ticket_key else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;
             font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#0f172a;padding:40px 20px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#1e293b;border-radius:12px;overflow:hidden;
                    border:1px solid #ef4444;">
        <tr>
          <td style="background:linear-gradient(135deg,#ef4444,#b91c1c);
                     padding:24px 32px;">
            <p style="margin:0;font-size:11px;color:#fecaca;
                      letter-spacing:.1em;text-transform:uppercase;">
              ⚠️ ESCALATION ALERT
            </p>
            <h1 style="margin:6px 0 0;font-size:20px;color:#fff;font-weight:700;">
              P1 Incident Unresolved
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px;">
            <p style="color:#fca5a5;font-size:15px;font-weight:600;margin:0 0 16px;">
              🚨 This P1-Critical incident has been open for <b>{minutes}+ minutes</b>
              with no resolution recorded.
            </p>
            <div style="background:#0f172a;border:1px solid #334155;
                        border-radius:8px;padding:16px 20px;margin-bottom:16px;">
              <p style="margin:0 0 8px;color:#f1f5f9;font-size:14px;font-weight:600;">
                {subject}
              </p>
              <p style="margin:0;color:#94a3b8;font-size:13px;">
                {ticket_line}
                <b>Opened:</b> {processed_at}<br>
                <b>Time elapsed:</b> {minutes}+ minutes
              </p>
            </div>
            <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;">
              Please investigate immediately and update the ticket status.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#0f172a;padding:14px 32px;
                     border-top:1px solid #1e293b;">
            <p style="margin:0;color:#475569;font-size:11px;">
              AI Operations Center — Escalation Engine
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


async def _send_escalation_email(subject: str, processed_at: str,
                                  ticket_key: str, minutes: int) -> None:
    def _send():
        smtp_host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        username  = os.getenv("EMAIL_USERNAME", "")
        password  = os.getenv("EMAIL_PASSWORD", "")
        oncall    = os.getenv("ONCALL_EMAIL", username)

        if not username or not password:
            return

        html = _build_escalation_html(subject, processed_at, ticket_key, minutes)
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"AI Operations Center <{username}>"
        msg["To"]      = oncall
        msg["Subject"] = f"🚨 ESCALATION: P1 Unresolved — {subject[:50]}"
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
                s.ehlo(); s.starttls(); s.login(username, password)
                s.sendmail(username, [oncall], msg.as_string())
            logger.warning(f"[Escalation] 🚨 Escalation email sent for: {subject[:50]}")
        except Exception as e:
            logger.error(f"[Escalation] Email failed: {e}")

    await asyncio.to_thread(_send)


async def run_escalation_check() -> None:
    """Check for unresolved P1s and escalate. Persists state to DB."""
    try:
        from app.core.db import fetch_unresolved_p1
        from app.services.telegram_client import telegram_service

        unresolved = fetch_unresolved_p1(older_than_minutes=30)
        for item in unresolved:
            eid = item.get("id", "")
            if not eid:
                continue

            # Check how many times we've already escalated this incident
            count = _get_escalation_count(eid)
            if count >= MAX_ESCALATIONS_PER_INCIDENT:
                logger.debug(f"[Escalation] Silenced (max {MAX_ESCALATIONS_PER_INCIDENT}x): {eid[:16]}")
                continue

            subject    = item.get("subject", "Unknown")
            proc_at    = item.get("processed_at", "")
            ticket_key = item.get("ticket_key", "")

            logger.warning(f"[Escalation] P1 unresolved 30+ min (escalation #{count+1}): {subject[:50]}")

            # Send escalation email
            await _send_escalation_email(subject, proc_at, ticket_key, 30)

            # Send Telegram alert
            await telegram_service.send_escalation(
                subject=subject, minutes=30, ticket_key=ticket_key
            )

            # Persist this escalation so restarts don't re-send
            _mark_escalated(eid)

    except Exception as e:
        logger.error(f"[Escalation] Check failed: {e}")


async def escalation_loop() -> None:
    """Background loop — checks every 5 minutes."""
    logger.info("[Escalation] Engine started — checking every 5 minutes.")
    while True:
        await asyncio.sleep(300)  # 5 minutes
        await run_escalation_check()


