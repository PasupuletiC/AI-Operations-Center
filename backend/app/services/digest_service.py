"""
Daily Digest Service — sends a morning summary email every day at 8 AM.

Reports yesterday's incident stats, top priorities, and any unresolved items.
Uses the same SMTP credentials as email_reply.py — zero new dependencies.
"""
import os
import smtplib
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _priority_color(priority: str) -> str:
    return {
        "P1-critical": "#ef4444",
        "P2-high":     "#f97316",
        "P3-medium":   "#eab308",
        "P4-low":      "#22c55e",
    }.get(priority, "#64748b")


def _build_digest_html(emails: List[Dict], stats: Dict) -> str:
    today      = datetime.now().strftime("%A, %B %d %Y")
    total      = stats.get("total_processed", len(emails))
    p1_count   = stats.get("by_priority", {}).get("P1", 0)
    p2_count   = stats.get("by_priority", {}).get("P2", 0)
    avg_ms     = stats.get("avg_process_ms", 0)
    avg_s      = f"{avg_ms/1000:.1f}s" if avg_ms else "—"
    replies    = stats.get("replies_sent", 0)

    # Build email rows
    rows_html = ""
    for em in emails[:20]:  # Show max 20
        color = _priority_color(em.get("priority", ""))
        ticket = f'<span style="color:#60a5fa;">{em["ticket_key"]}</span>' \
                 if em.get("ticket_key") else "—"
        reply_icon = "✅" if em.get("reply_sent") else "❌"
        rows_html += f"""
        <tr style="border-bottom:1px solid #334155;">
          <td style="padding:10px 12px;color:#f1f5f9;font-size:13px;max-width:220px;
                     overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            {em.get("subject","")[:60]}
          </td>
          <td style="padding:10px 12px;">
            <span style="background:{color}22;color:{color};padding:2px 8px;
                         border-radius:999px;font-size:11px;font-weight:600;">
              {em.get("priority","unknown")}
            </span>
          </td>
          <td style="padding:10px 12px;color:#94a3b8;font-size:12px;">
            {em.get("email_type","—")}
          </td>
          <td style="padding:10px 12px;color:#94a3b8;font-size:12px;">{ticket}</td>
          <td style="padding:10px 12px;font-size:12px;text-align:center;">{reply_icon}</td>
        </tr>"""

    if not rows_html:
        rows_html = """<tr><td colspan="5" style="padding:20px;text-align:center;
                       color:#64748b;font-size:13px;">No emails processed yesterday.</td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;
             font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#0f172a;padding:40px 20px;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="background:#1e293b;border-radius:12px;overflow:hidden;
                    border:1px solid #334155;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);
                     padding:28px 32px;">
            <p style="margin:0;font-size:11px;color:#c7d2fe;letter-spacing:.1em;
                      text-transform:uppercase;">AI Operations Center</p>
            <h1 style="margin:6px 0 0;font-size:22px;color:#fff;font-weight:700;">
              📊 Daily Incident Digest
            </h1>
            <p style="margin:6px 0 0;color:#c7d2fe;font-size:13px;">{today}</p>
          </td>
        </tr>

        <!-- Stats cards -->
        <tr>
          <td style="padding:24px 32px 8px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                {"".join(f'''
                <td style="width:25%;padding:0 6px 0 0;">
                  <div style="background:#0f172a;border:1px solid #334155;
                              border-radius:8px;padding:14px;text-align:center;">
                    <p style="margin:0;color:#94a3b8;font-size:11px;
                              text-transform:uppercase;letter-spacing:.05em;">{label}</p>
                    <p style="margin:4px 0 0;color:{color};font-size:24px;font-weight:700;">{val}</p>
                  </div>
                </td>''' for label, val, color in [
                    ("Total Processed", total, "#6366f1"),
                    ("P1 Critical",     p1_count, "#ef4444"),
                    ("Replies Sent",    replies, "#10b981"),
                    ("Avg Process Time",avg_s, "#f97316"),
                ])}
              </tr>
            </table>
          </td>
        </tr>

        <!-- Email table -->
        <tr>
          <td style="padding:16px 32px 28px;">
            <p style="color:#94a3b8;font-size:12px;text-transform:uppercase;
                      letter-spacing:.05em;margin:0 0 12px;">
              Yesterday's Processed Emails
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#0f172a;border-radius:8px;
                          border:1px solid #334155;overflow:hidden;">
              <thead>
                <tr style="background:#1e293b;border-bottom:1px solid #334155;">
                  <th style="padding:10px 12px;color:#64748b;font-size:11px;
                             font-weight:600;text-align:left;">Subject</th>
                  <th style="padding:10px 12px;color:#64748b;font-size:11px;
                             font-weight:600;text-align:left;">Priority</th>
                  <th style="padding:10px 12px;color:#64748b;font-size:11px;
                             font-weight:600;text-align:left;">Type</th>
                  <th style="padding:10px 12px;color:#64748b;font-size:11px;
                             font-weight:600;text-align:left;">Ticket</th>
                  <th style="padding:10px 12px;color:#64748b;font-size:11px;
                             font-weight:600;text-align:center;">Reply</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#0f172a;padding:16px 32px;
                     border-top:1px solid #1e293b;">
            <p style="margin:0;color:#475569;font-size:11px;">
              AI Operations Center &mdash; Automated Daily Digest
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def send_daily_digest() -> bool:
    """
    Send the daily digest email. Called every morning at 8 AM by the scheduler.
    Reads yesterday's emails from SQLite and sends a formatted summary.
    """
    import asyncio
    from app.core.db import fetch_emails_since, get_aggregate_stats

    def _send() -> bool:
        smtp_host    = os.getenv("EMAIL_SMTP_HOST",  "smtp.gmail.com")
        smtp_port    = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        username     = os.getenv("EMAIL_USERNAME",   "")
        password     = os.getenv("EMAIL_PASSWORD",   "")
        digest_email = os.getenv("DIGEST_EMAIL", username)  # defaults to self

        if not username or not password:
            logger.debug("[Digest] SMTP not configured — skipping digest.")
            return False

        try:
            emails = fetch_emails_since(hours=24)
            stats  = get_aggregate_stats()
        except Exception as e:
            logger.warning(f"[Digest] Could not read DB: {e}")
            emails, stats = [], {}

        html = _build_digest_html(emails, stats)
        date_str = datetime.now().strftime("%b %d, %Y")

        plain = (
            f"AI Operations Center — Daily Digest ({date_str})\n\n"
            f"Total processed: {stats.get('total_processed', 0)}\n"
            f"P1 Critical    : {stats.get('by_priority', {}).get('P1', 0)}\n"
            f"Replies sent   : {stats.get('replies_sent', 0)}\n\n"
            f"See full HTML digest for details.\n\n— AI Operations Center"
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = f"AI Operations Center <{username}>"
        msg["To"]      = digest_email
        msg["Subject"] = f"📊 Daily Incident Digest — {date_str}"
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(username, password)
                server.sendmail(username, [digest_email], msg.as_string())
            logger.info(f"[Digest] ✅ Daily digest sent to {digest_email}")
            return True
        except Exception as e:
            logger.error(f"[Digest] Failed to send digest: {e}")
            return False

    return await asyncio.to_thread(_send)
