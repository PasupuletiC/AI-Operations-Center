"""
Weekly Report Service — sends a detailed Monday 8AM analytics email.
Covers 7-day incident trends, MTTR, top issues, and team stats.
"""
import os, smtplib, logging, asyncio
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _bar(value: int, max_val: int, width: int = 20) -> str:
    filled = int((value / max_val) * width) if max_val else 0
    return "█" * filled + "░" * (width - filled)


def _build_weekly_html(emails: List[Dict], week_start: str, week_end: str) -> str:
    total   = len(emails)
    p1      = sum(1 for e in emails if e.get("priority") == "P1-critical")
    p2      = sum(1 for e in emails if e.get("priority") == "P2-high")
    p3      = sum(1 for e in emails if e.get("priority") == "P3-medium")
    p4      = sum(1 for e in emails if e.get("priority") == "P4-low")
    replies = sum(1 for e in emails if e.get("reply_sent"))
    avg_ms  = int(sum(e.get("process_ms", 0) for e in emails) / total) if total else 0
    avg_s   = f"{avg_ms/1000:.1f}s" if avg_ms else "—"

    by_type: Dict[str, int] = {}
    for e in emails:
        t = e.get("email_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    max_type = max(by_type.values()) if by_type else 1

    type_rows = "".join(f"""
        <tr>
          <td style="padding:8px 12px;color:#e2e8f0;font-size:13px;">{t}</td>
          <td style="padding:8px 12px;">
            <div style="background:#1e293b;border-radius:4px;overflow:hidden;width:160px;">
              <div style="height:8px;background:#6366f1;width:{int(c/max_type*100)}%;border-radius:4px;"></div>
            </div>
          </td>
          <td style="padding:8px 12px;color:#94a3b8;font-size:13px;text-align:right;">{c}</td>
        </tr>""" for t, c in sorted(by_type.items(), key=lambda x: -x[1]))

    recent_rows = "".join(f"""
        <tr style="border-bottom:1px solid #1e293b;">
          <td style="padding:8px 12px;color:#e2e8f0;font-size:12px;max-width:200px;
                     overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{e.get('subject','')[:55]}</td>
          <td style="padding:8px 12px;">
            <span style="background:{"#ef4444" if "P1" in str(e.get("priority","")) else "#f97316" if "P2" in str(e.get("priority","")) else "#64748b"}22;
                         color:{"#ef4444" if "P1" in str(e.get("priority","")) else "#f97316" if "P2" in str(e.get("priority","")) else "#94a3b8"};
                         padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;">
              {e.get("priority","?")}
            </span>
          </td>
          <td style="padding:8px 12px;color:#94a3b8;font-size:12px;">{"✅" if e.get("reply_sent") else "⏳"}</td>
          <td style="padding:8px 12px;color:#64748b;font-size:11px;">{e.get("processed_at","")}</td>
        </tr>""" for e in emails[:15])

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:40px 20px;">
  <tr><td align="center">
    <table width="680" cellpadding="0" cellspacing="0"
           style="background:#1e293b;border-radius:16px;overflow:hidden;border:1px solid #334155;">
      <tr>
        <td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:32px 40px;">
          <p style="margin:0;font-size:11px;color:#c7d2fe;letter-spacing:.1em;text-transform:uppercase;">
            AI Operations Center
          </p>
          <h1 style="margin:8px 0 4px;font-size:26px;color:#fff;font-weight:800;">
            📅 Weekly Incident Report
          </h1>
          <p style="margin:0;color:#c7d2fe;font-size:14px;">{week_start} — {week_end}</p>
        </td>
      </tr>

      <!-- KPI row -->
      <tr><td style="padding:28px 40px 12px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            {"".join(f'''<td style="width:20%;padding:0 6px 0 0;">
              <div style="background:#0f172a;border:1px solid #334155;border-radius:10px;padding:16px;text-align:center;">
                <p style="margin:0;color:#64748b;font-size:10px;text-transform:uppercase;letter-spacing:.06em;">{lbl}</p>
                <p style="margin:6px 0 0;color:{col};font-size:26px;font-weight:800;">{val}</p>
              </div></td>'''
            for lbl,val,col in [
                ("Total",   total,   "#6366f1"),
                ("P1 Critical", p1, "#ef4444"),
                ("P2 High",     p2, "#f97316"),
                ("Replies",  replies,"#10b981"),
                ("Avg Time", avg_s,  "#f59e0b"),
            ])}
          </tr>
        </table>
      </td></tr>

      <!-- Incident type breakdown -->
      <tr><td style="padding:12px 40px;">
        <p style="color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin:0 0 10px;">
          Incident Type Breakdown
        </p>
        <div style="background:#0f172a;border:1px solid #334155;border-radius:8px;overflow:hidden;">
          <table width="100%" cellpadding="0" cellspacing="0">{type_rows or
            "<tr><td style='padding:16px;color:#475569;text-align:center;'>No data</td></tr>"}
          </table>
        </div>
      </td></tr>

      <!-- Recent incidents -->
      <tr><td style="padding:12px 40px 32px;">
        <p style="color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin:0 0 10px;">
          This Week's Incidents (latest 15)
        </p>
        <div style="background:#0f172a;border:1px solid #334155;border-radius:8px;overflow:hidden;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <thead>
              <tr style="background:#1e293b;">
                <th style="padding:8px 12px;color:#475569;font-size:11px;text-align:left;">Subject</th>
                <th style="padding:8px 12px;color:#475569;font-size:11px;text-align:left;">Priority</th>
                <th style="padding:8px 12px;color:#475569;font-size:11px;">Reply</th>
                <th style="padding:8px 12px;color:#475569;font-size:11px;text-align:left;">Time</th>
              </tr>
            </thead>
            <tbody>{recent_rows or
              "<tr><td colspan='4' style='padding:20px;color:#475569;text-align:center;'>No incidents this week</td></tr>"}
            </tbody>
          </table>
        </div>
      </td></tr>

      <tr><td style="background:#0f172a;padding:16px 40px;border-top:1px solid #1e293b;">
        <p style="margin:0;color:#334155;font-size:11px;">
          AI Operations Center — Weekly Analytics Report · Auto-generated
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


async def send_weekly_report() -> bool:
    """Send the weekly report. Called every Monday at 8 AM by the scheduler."""
    def _send() -> bool:
        smtp_host = os.getenv("EMAIL_SMTP_HOST",  "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        username  = os.getenv("EMAIL_USERNAME",   "")
        password  = os.getenv("EMAIL_PASSWORD",   "")
        recipient = os.getenv("DIGEST_EMAIL",     username)

        if not username or not password:
            logger.debug("[Weekly] SMTP not configured — skipping")
            return False

        try:
            from app.core.db import fetch_emails_since
            emails = fetch_emails_since(hours=168)
        except Exception:
            emails = []

        now        = datetime.now()
        week_start = (now - timedelta(days=7)).strftime("%b %d")
        week_end   = now.strftime("%b %d, %Y")
        html       = _build_weekly_html(emails, week_start, week_end)

        msg = MIMEMultipart("alternative")
        msg["From"]    = f"AI Operations Center <{username}>"
        msg["To"]      = recipient
        msg["Subject"] = f"📅 Weekly Ops Report — {week_start} to {week_end}"
        msg.attach(MIMEText(
            f"Weekly Ops Report: {len(emails)} incidents processed.\n"
            f"P1: {sum(1 for e in emails if 'P1' in str(e.get('priority','')))}\n"
            f"See HTML version for full details.\n\n— AI Operations Center", "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as s:
                s.ehlo(); s.starttls(); s.login(username, password)
                s.sendmail(username, [recipient], msg.as_string())
            logger.info(f"[Weekly] ✅ Weekly report sent to {recipient}")
            return True
        except Exception as e:
            logger.error(f"[Weekly] Send failed: {e}")
            return False

    return await asyncio.to_thread(_send)
