"""
PDF Post-Mortem Generator — creates a styled HTML post-mortem report
and emails it as an attachment after a P1 incident is processed.

The HTML can be opened in any browser and printed to PDF (Ctrl+P → Save as PDF).
Zero new dependencies — pure Python standard library.
"""
import os
import smtplib
import logging
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def generate_postmortem_html(
    subject:     str,
    email_data:  Dict[str, Any],
    incident:    Dict[str, Any],
    ticket:      Dict[str, Any],
    summary:     str,
) -> str:
    """Generate a printable post-mortem HTML document."""
    now        = datetime.now().strftime("%B %d, %Y at %H:%M")
    priority   = email_data.get("priority",   "unknown")
    dept       = email_data.get("department", "unknown")
    etype      = email_data.get("email_type", "incident")
    ticket_key = ticket.get("key", "N/A")
    ticket_url = ticket.get("url", "")

    triage  = incident.get("triage", {})
    rca     = incident.get("rca",    {})
    logs    = incident.get("logs",   [])

    severity      = triage.get("severity",         priority)
    urgency       = triage.get("urgency_score",    0)
    affected_sys  = triage.get("affected_systems", [])
    affected_usr  = triage.get("affected_users",   "Unknown")
    triage_sum    = triage.get("triage_summary",   "")

    root_cause    = rca.get("root_cause",              "Not determined")
    remediation   = rca.get("remediation_plan",        [])
    postmortem    = rca.get("post_mortem_draft",       "")
    est_res       = rca.get("estimated_resolution_time","Unknown")

    # Systems list
    sys_items = "".join(
        f'<li style="padding:3px 0;color:#475569;">{s}</li>'
        for s in (affected_sys or ["No data"])
    )

    # Remediation steps
    rem_items = "".join(
        f'<li style="padding:5px 0;color:#374151;">'
        f'<span style="color:#6366f1;font-weight:700;margin-right:6px;">{i+1}.</span>{s}</li>'
        for i, s in enumerate(remediation)
    ) or '<li style="color:#9ca3af;">No remediation steps recorded.</li>'

    # Log entries
    log_rows = "".join(
        f'<tr style="border-bottom:1px solid #f3f4f6;">'
        f'<td style="padding:6px 8px;font-size:11px;color:#6b7280;white-space:nowrap;">'
        f'{lg.get("timestamp","")}</td>'
        f'<td style="padding:6px 8px;">'
        f'<span style="color:{"#ef4444" if "error" in lg.get("status","").lower() else "#f97316"};'
        f'font-size:11px;font-weight:600;">{lg.get("status","").upper()}</span></td>'
        f'<td style="padding:6px 8px;font-size:12px;color:#374151;">{lg.get("message","")}</td>'
        f'<td style="padding:6px 8px;font-size:11px;color:#9ca3af;">{lg.get("service","")}</td>'
        f'</tr>'
        for lg in logs[:10]
    ) or '<tr><td colspan="4" style="padding:12px;color:#9ca3af;text-align:center;">No log data</td></tr>'

    ticket_link = (
        f'<a href="{ticket_url}" style="color:#6366f1;">{ticket_key}</a>'
        if ticket_url else ticket_key
    )

    urgency_pct = int(urgency * 100) if urgency else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Post-Mortem: {subject}</title>
  <style>
    @media print {{
      body {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
      .no-print {{ display: none; }}
    }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0;
            background: #f9fafb; color: #111827; }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 40px 30px; }}
    h1 {{ font-size: 26px; font-weight: 800; color: #111827; margin: 0 0 4px; }}
    h2 {{ font-size: 16px; font-weight: 700; color: #1e293b;
          margin: 24px 0 10px; padding-bottom: 6px;
          border-bottom: 2px solid #e5e7eb; }}
    .badge {{ display:inline-block; padding: 3px 12px; border-radius: 999px;
              font-size: 12px; font-weight: 700; }}
    .p1 {{ background:#fef2f2; color:#ef4444; }}
    .p2 {{ background:#fff7ed; color:#f97316; }}
    .meta-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr;
                  gap:12px; margin: 16px 0; }}
    .meta-card {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px;
                 padding:14px; }}
    .meta-label {{ font-size:11px; color:#9ca3af; text-transform:uppercase;
                   letter-spacing:.05em; margin:0 0 4px; }}
    .meta-val {{ font-size:18px; font-weight:700; color:#111827; margin:0; }}
    .section {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px;
                padding:18px 20px; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th {{ font-size:11px; color:#9ca3af; text-align:left; padding:8px;
          border-bottom:2px solid #f3f4f6; font-weight:600;
          text-transform:uppercase; letter-spacing:.04em; }}
    .progress-bar {{ height:8px; background:#e5e7eb; border-radius:4px;
                     overflow:hidden; margin-top:4px; }}
    .progress-fill {{ height:100%; background:#6366f1; border-radius:4px; }}
    .footer {{ margin-top:30px; padding-top:16px; border-top:1px solid #e5e7eb;
               font-size:11px; color:#9ca3af; text-align:center; }}
  </style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);
              border-radius:12px;padding:28px 32px;color:#fff;margin-bottom:28px;">
    <p style="margin:0;font-size:11px;letter-spacing:.1em;
              text-transform:uppercase;opacity:.8;">AI Operations Center</p>
    <h1 style="color:#fff;margin:8px 0 4px;font-size:26px;">
      📄 Incident Post-Mortem
    </h1>
    <p style="margin:0;opacity:.8;font-size:13px;">{subject}</p>
    <p style="margin:6px 0 0;opacity:.6;font-size:12px;">Generated: {now}</p>
  </div>

  <!-- Meta cards -->
  <div class="meta-grid">
    <div class="meta-card">
      <p class="meta-label">Severity</p>
      <span class="badge {'p1' if 'P1' in severity else 'p2'}">{severity}</span>
    </div>
    <div class="meta-card">
      <p class="meta-label">Ticket</p>
      <p class="meta-val" style="font-size:16px;">{ticket_link}</p>
    </div>
    <div class="meta-card">
      <p class="meta-label">Department</p>
      <p class="meta-val" style="font-size:16px;text-transform:capitalize;">{dept}</p>
    </div>
    <div class="meta-card">
      <p class="meta-label">Est. Resolution</p>
      <p class="meta-val" style="font-size:15px;">{est_res}</p>
    </div>
    <div class="meta-card">
      <p class="meta-label">Affected Users</p>
      <p class="meta-val" style="font-size:15px;">{affected_usr}</p>
    </div>
    <div class="meta-card">
      <p class="meta-label">Urgency Score</p>
      <p class="meta-val">{urgency_pct}%</p>
      <div class="progress-bar">
        <div class="progress-fill" style="width:{urgency_pct}%;"></div>
      </div>
    </div>
  </div>

  <!-- Triage Summary -->
  <h2>1. Triage Summary</h2>
  <div class="section">
    <p style="margin:0;color:#374151;line-height:1.6;font-size:14px;">
      {triage_sum or "No triage summary available."}
    </p>
    <h3 style="font-size:13px;color:#6b7280;margin:14px 0 6px;">
      Affected Systems
    </h3>
    <ul style="margin:0;padding-left:20px;">{sys_items}</ul>
  </div>

  <!-- Root Cause -->
  <h2>2. Root Cause Analysis</h2>
  <div class="section">
    <p style="margin:0;color:#374151;line-height:1.6;font-size:14px;">
      {root_cause}
    </p>
  </div>

  <!-- Remediation -->
  <h2>3. Remediation Plan</h2>
  <div class="section">
    <ol style="margin:0;padding:0;list-style:none;">{rem_items}</ol>
  </div>

  <!-- System Logs -->
  <h2>4. System Logs at Time of Incident</h2>
  <div class="section" style="padding:0;overflow:hidden;">
    <table>
      <thead>
        <tr>
          <th>Timestamp</th><th>Status</th>
          <th>Message</th><th>Service</th>
        </tr>
      </thead>
      <tbody>{log_rows}</tbody>
    </table>
  </div>

  <!-- Executive Summary -->
  <h2>5. Executive Summary</h2>
  <div class="section">
    <p style="margin:0;color:#374151;line-height:1.6;font-size:14px;">
      {postmortem or summary or "No executive summary available."}
    </p>
  </div>

  <div class="footer">
    AI Operations Center — Post-Mortem Report &nbsp;|&nbsp; {now}
  </div>

</div>
</body>
</html>"""


async def send_postmortem(
    subject:    str,
    result:     Dict[str, Any],
) -> bool:
    """Generate and email a post-mortem HTML report as an attachment."""
    def _send() -> bool:
        smtp_host = os.getenv("EMAIL_SMTP_HOST",  "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        username  = os.getenv("EMAIL_USERNAME",   "")
        password  = os.getenv("EMAIL_PASSWORD",   "")
        oncall    = os.getenv("ONCALL_EMAIL",     username)

        if not username or not password:
            return False

        email_data = result.get("email_data",      {})
        incident   = result.get("incident_result", {})
        ticket     = result.get("ticket_result",   {})
        summary    = result.get("executive_summary","")

        html_report = generate_postmortem_html(
            subject, email_data, incident, ticket, summary
        )

        date_str   = datetime.now().strftime("%Y%m%d_%H%M")
        filename   = f"postmortem_{date_str}.html"
        ticket_key = ticket.get("key","")

        msg = MIMEMultipart("mixed")
        msg["From"]    = f"AI Operations Center <{username}>"
        msg["To"]      = oncall
        msg["Subject"] = f"📄 Post-Mortem Report — {ticket_key or subject[:40]}"

        body = MIMEText(
            f"Please find the post-mortem report attached.\n\n"
            f"Incident: {subject}\nTicket: {ticket_key}\n\n"
            f"Open the HTML file in your browser and print to PDF.\n\n"
            f"— AI Operations Center", "plain"
        )
        msg.attach(body)

        attachment = MIMEBase("text", "html")
        attachment.set_payload(html_report.encode("utf-8"))
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        msg.attach(attachment)

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as s:
                s.ehlo(); s.starttls(); s.login(username, password)
                s.sendmail(username, [oncall], msg.as_string())
            logger.info(f"[PostMortem] ✅ Sent report for: {subject[:50]}")
            return True
        except Exception as e:
            logger.error(f"[PostMortem] Send failed: {e}")
            return False

    return await asyncio.to_thread(_send)
