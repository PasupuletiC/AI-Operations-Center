"""
Email Reply Service — sends automated confirmation replies to email senders.

Improvements (v2 + v3):
  1. Remediation steps included in HTML from incident_agent output
  2. SMTP retry with exponential backoff (3 attempts)
  3. Duplicate reply guard — persisted to disk, survives restarts
  4. CC on-call team for P1-Critical (set ONCALL_EMAIL in .env)
  5. Jira ticket clickable link (uses ticket URL, not just key)
  6. Returns reply_sent bool so dashboard can show ✅/❌ badge
  I. Auto language detection — reply in sender's language

Zero new dependencies — uses only Python built-ins + existing LLM router.
"""
import os
import json
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Priority → display label + accent color
_PRIORITY_LABEL = {
    "P1-critical": ("🔴 P1 — Critical", "#ef4444"),
    "P2-high":     ("🟠 P2 — High",     "#f97316"),
    "P3-medium":   ("🟡 P3 — Medium",   "#eab308"),
    "P4-low":      ("🟢 P4 — Low",      "#22c55e"),
}

# Priority → SLA target text
_PRIORITY_SLA = {
    "P1-critical": "within 30 minutes",
    "P2-high":     "within 2 hours",
    "P3-medium":   "within 8 hours",
    "P4-low":      "within 2 business days",
}

# File that persists UIDs of emails we've already replied to
_REPLIED_UIDS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "replied_uids.json")
)


# ── Duplicate Guard ────────────────────────────────────────────────────────────

def _load_replied_uids() -> set:
    try:
        if os.path.exists(_REPLIED_UIDS_FILE):
            with open(_REPLIED_UIDS_FILE, "r") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()


def _save_replied_uid(uid: str) -> None:
    try:
        existing = _load_replied_uids()
        existing.add(uid)
        # Keep only last 500 UIDs to prevent unbounded growth
        trimmed = list(existing)[-500:]
        with open(_REPLIED_UIDS_FILE, "w") as f:
            json.dump(trimmed, f)
    except Exception as e:
        logger.warning(f"[EmailReply] Could not save replied UID cache: {e}")


def _already_replied(uid: str) -> bool:
    return uid in _load_replied_uids()


# ── Language Detection (Feature I) ────────────────────────────────────────────

# Common non-English keyword patterns → language tag
_LANG_PATTERNS = {
    "es": ["gracias", "hola", "problema", "urgente", "servidor", "ayuda", "por favor"],
    "fr": ["bonjour", "problème", "urgent", "serveur", "merci", "aide", "s'il vous plaît"],
    "de": ["hallo", "problem", "dringend", "server", "danke", "hilfe", "bitte"],
    "pt": ["olá", "problema", "urgente", "servidor", "obrigado", "ajuda", "por favor"],
    "it": ["ciao", "problema", "urgente", "server", "grazie", "aiuto", "per favore"],
    "ar": ["مرحبا", "مشكلة", "عاجل", "خادم", "شكرا", "مساعدة"],
    "ja": ["こんにちは", "問題", "緊急", "サーバー", "ありがとう"],
    "zh": ["你好", "问题", "紧急", "服务器", "谢谢", "帮助"],
    "hi": ["नमस्ते", "समस्या", "जरूरी", "सर्वर", "धन्यवाद", "मदद"],
}

_LANG_GREETINGS = {
    "es": "Hemos recibido su solicitud y la estamos procesando automáticamente.",
    "fr": "Nous avons reçu votre demande et la traitons automatiquement.",
    "de": "Wir haben Ihre Anfrage erhalten und bearbeiten sie automatisch.",
    "pt": "Recebemos sua solicitação e estamos processando automaticamente.",
    "it": "Abbiamo ricevuto la sua richiesta e la stiamo elaborando automaticamente.",
    "ar": "لقد تلقينا طلبك ونعالجه تلقائيًا.",
    "ja": "リクエストを受信し、自動的に処理しています。",
    "zh": "我们已收到您的请求并正在自动处理。",
    "hi": "हमें आपका अनुरोध मिल गया है और हम इसे स्वचालित रूप से संसाधित कर रहे हैं।",
}


def _detect_language(text: str) -> str:
    """
    Detect email language from subject/body using keyword matching.
    Returns ISO 639-1 code or 'en' (English) if unknown.
    """
    lower = text.lower()
    scores: dict = {}
    for lang, keywords in _LANG_PATTERNS.items():
        scores[lang] = sum(1 for kw in keywords if kw in lower)
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    return best_lang if best_score >= 1 else "en"


# ── Header helpers ─────────────────────────────────────────────────────────────

def _extract_sender_email(sender_header: str) -> str:
    _, addr = parseaddr(sender_header)
    return addr.strip() if addr else sender_header.strip()


def _extract_sender_name(sender_header: str) -> str:
    name, addr = parseaddr(sender_header)
    return name.strip() if name else addr.split("@")[0]


# ── HTML Builder ───────────────────────────────────────────────────────────────

def _build_remediation_html(steps: list) -> str:
    """Builds a numbered remediation steps section from the incident agent output."""
    if not steps:
        return ""
    items = "".join(
        f'<li style="padding:5px 0;color:#cbd5e1;font-size:13px;line-height:1.5;">'
        f'<span style="color:#6366f1;font-weight:700;margin-right:8px;">&#x25BA;</span>'
        f"{step}</li>"
        for step in steps
    )
    return f"""
    <div style="margin-top:20px;padding:14px;background:#1e293b;
                border-left:3px solid #10b981;border-radius:6px;">
      <p style="margin:0 0 10px;color:#94a3b8;font-size:12px;
                text-transform:uppercase;letter-spacing:.05em;">
        📋 Remediation Plan
      </p>
      <ol style="margin:0;padding-left:16px;list-style:none;">{items}</ol>
    </div>"""


def _build_html_reply(
    sender_name:    str,
    subject:        str,
    priority:       str,
    email_type:     str,
    ticket_key:     str | None,
    ticket_url:     str | None,
    root_cause:     str,
    remediation:    list,
    summary:        str,
) -> str:
    """Generates the full polished HTML confirmation email."""
    priority_label, priority_color = _PRIORITY_LABEL.get(
        priority, ("⚪ Unknown", "#64748b")
    )
    sla = _PRIORITY_SLA.get(priority, "as soon as possible")

    # ── Ticket row: key + clickable link ──────────────────────────────────────
    ticket_section = ""
    if ticket_key:
        link_html = (
            f'<a href="{ticket_url}" target="_blank" '
            f'style="color:#60a5fa;text-decoration:none;margin-left:10px;font-size:12px;">'
            f'View Ticket →</a>'
            if ticket_url else ""
        )
        ticket_section = f"""
        <tr>
          <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Ticket Created</td>
          <td style="padding:6px 0;font-weight:600;color:#60a5fa;">
            {ticket_key}{link_html}
          </td>
        </tr>"""

    # ── Root cause section ────────────────────────────────────────────────────
    rc_section = ""
    if root_cause and len(root_cause) > 20 and "failed" not in root_cause.lower():
        rc_section = f"""
        <div style="margin-top:20px;padding:14px;background:#1e293b;
                    border-left:3px solid #6366f1;border-radius:6px;">
          <p style="margin:0 0 6px;color:#94a3b8;font-size:12px;
                    text-transform:uppercase;letter-spacing:.05em;">Root Cause Analysis</p>
          <p style="margin:0;color:#cbd5e1;font-size:13px;line-height:1.5;">{root_cause}</p>
        </div>"""

    # ── Remediation steps (NEW) ───────────────────────────────────────────────
    remediation_section = _build_remediation_html(remediation)

    # ── Summary section ───────────────────────────────────────────────────────
    summary_section = ""
    if summary:
        summary_section = f"""
        <div style="margin-top:20px;padding:14px;background:#0f172a;
                    border-radius:6px;border:1px solid #334155;">
          <p style="margin:0 0 6px;color:#94a3b8;font-size:12px;
                    text-transform:uppercase;letter-spacing:.05em;">AI Summary</p>
          <p style="margin:0;color:#cbd5e1;font-size:13px;line-height:1.6;">{summary}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;
             font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#0f172a;padding:40px 20px;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#1e293b;border-radius:12px;overflow:hidden;
                    border:1px solid #334155;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);
                     padding:28px 32px;">
            <p style="margin:0;font-size:11px;color:#c7d2fe;letter-spacing:.1em;
                      text-transform:uppercase;">AI Operations Center</p>
            <h1 style="margin:6px 0 0;font-size:20px;color:#fff;font-weight:700;">
              Your Request Has Been Processed
            </h1>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px;">
            <p style="color:#e2e8f0;font-size:15px;margin:0 0 16px;">
              Hi {sender_name},
            </p>
            <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 24px;">
              Our AI Operations Center has automatically received and processed your
              email. Here's a complete summary of findings and actions taken:
            </p>

            <!-- Details table -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#0f172a;border-radius:8px;padding:16px 20px;
                          border:1px solid #334155;margin-bottom:8px;">
              <tr>
                <td style="padding:6px 0;color:#94a3b8;font-size:13px;width:120px;">
                  Subject
                </td>
                <td style="padding:6px 0;font-weight:600;color:#f1f5f9;font-size:13px;">
                  {subject}
                </td>
              </tr>
              <tr>
                <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Priority</td>
                <td style="padding:6px 0;">
                  <span style="background:{priority_color}22;color:{priority_color};
                               padding:2px 12px;border-radius:999px;font-size:12px;
                               font-weight:600;">{priority_label}</span>
                </td>
              </tr>
              <tr>
                <td style="padding:6px 0;color:#94a3b8;font-size:13px;">Type</td>
                <td style="padding:6px 0;color:#e2e8f0;font-size:13px;
                           text-transform:capitalize;">{email_type}</td>
              </tr>
              <tr>
                <td style="padding:6px 0;color:#94a3b8;font-size:13px;">SLA Target</td>
                <td style="padding:6px 0;color:#e2e8f0;font-size:13px;">
                  Resolution {sla}
                </td>
              </tr>
              {ticket_section}
            </table>

            {rc_section}
            {remediation_section}
            {summary_section}

            <p style="margin-top:28px;color:#64748b;font-size:12px;line-height:1.6;
                      border-top:1px solid #334155;padding-top:20px;">
              This is an automated message from your AI Operations Center.<br>
              If this classification seems incorrect, please reply with more details
              and a human operator will review it shortly.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#0f172a;padding:16px 32px;
                     border-top:1px solid #1e293b;">
            <p style="margin:0;color:#475569;font-size:11px;">
              AI Operations Center &mdash; Automated Email Processing System
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Main send function ─────────────────────────────────────────────────────────

async def send_reply(
    original_sender:  str,
    original_subject: str,
    result:           dict,
    uid:              str = "",
) -> bool:
    """
    Send an automated HTML reply to the original email sender.

    Features:
      - Remediation steps from incident_agent
      - 3 SMTP retries with exponential backoff
      - Duplicate guard (won't reply twice to same UID)
      - CC on-call team for P1 (ONCALL_EMAIL in .env)
      - Jira ticket clickable link

    Returns True on success, False on failure (non-fatal).
    """
    import asyncio

    def _send() -> bool:
        smtp_host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        username  = os.getenv("EMAIL_USERNAME", "")
        password  = os.getenv("EMAIL_PASSWORD", "")
        oncall    = os.getenv("ONCALL_EMAIL", "").strip()

        if not username or not password:
            logger.debug("[EmailReply] SMTP not configured — skipping reply.")
            return False

        to_addr = _extract_sender_email(original_sender)
        if not to_addr or "@" not in to_addr:
            logger.warning(f"[EmailReply] Invalid sender address: {original_sender}")
            return False

        # Skip bot / system addresses — avoid reply loops
        skip_keywords = ["noreply", "no-reply", "mailer-daemon", "postmaster",
                         "bounce", "donotreply"]
        if any(kw in to_addr.lower() for kw in skip_keywords):
            logger.debug(f"[EmailReply] Skipping bot sender: {to_addr}")
            return False

        # ── Duplicate guard ──────────────────────────────────────────────────
        if uid and _already_replied(uid):
            logger.info(f"[EmailReply] Already replied to UID {uid} — skipping.")
            return False

        # ── Extract fields from agent result ──────────────────────────────────
        sender_name  = _extract_sender_name(original_sender)
        email_data   = result.get("email_data", {})
        priority     = email_data.get("priority",   "unknown")
        email_type   = email_data.get("email_type", "request")
        ticket_key   = result.get("ticket_result",  {}).get("key")
        ticket_url   = result.get("ticket_result",  {}).get("url")
        rca          = result.get("incident_result", {}).get("rca", {})
        root_cause   = rca.get("root_cause",       "")
        remediation  = rca.get("remediation_plan", [])
        summary      = result.get("executive_summary", "")[:500]

        subject_line = (
            f"Re: {original_subject}"
            if not original_subject.lower().startswith("re:")
            else original_subject
        )

        # ── Language detection (Feature I) ───────────────────────────────────
        detected_lang = _detect_language(original_subject + " " + summary[:200])
        lang_note     = _LANG_GREETINGS.get(detected_lang, "")
        if detected_lang != "en":
            logger.info(f"[EmailReply] Detected language: {detected_lang} — appending translation")

        # ── Build message ─────────────────────────────────────────────────────
        html_body = _build_html_reply(
            sender_name=sender_name,
            subject=original_subject,
            priority=priority,
            email_type=email_type,
            ticket_key=ticket_key,
            ticket_url=ticket_url,
            root_cause=root_cause,
            remediation=remediation,
            summary=summary,
        )

        # Plain text fallback (includes remediation steps + translated note)
        steps_text = ""
        if remediation:
            steps_text = "\nRemediation Plan:\n" + "\n".join(
                f"  {i+1}. {s}" for i, s in enumerate(remediation)
            ) + "\n"

        plain = (
            f"Hi {sender_name},\n\n"
            f"Your email '{original_subject}' has been processed.\n"
            f"Priority  : {priority}\n"
            f"Type      : {email_type}\n"
            f"SLA Target: Resolution {_PRIORITY_SLA.get(priority, 'ASAP')}\n"
            + (f"Ticket    : {ticket_key}"
               + (f"  →  {ticket_url}" if ticket_url else "") + "\n"
               if ticket_key else "")
            + (f"\nRoot Cause:\n{root_cause}\n" if root_cause else "")
            + steps_text
            + (f"\nSummary:\n{summary}\n" if summary else "")
            + (f"\n---\n{lang_note}\n" if lang_note else "")
            + "\n— AI Operations Center"
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = f"AI Operations Center <{username}>"
        msg["To"]      = to_addr
        msg["Subject"] = subject_line

        # ── CC on-call team for P1 (NEW) ──────────────────────────────────────
        if priority == "P1-critical" and oncall and oncall != to_addr:
            msg["Cc"] = oncall
            recipients = [to_addr, oncall]
            logger.info(f"[EmailReply] CC-ing on-call team: {oncall}")
        else:
            recipients = [to_addr]

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # ── SMTP send with 3-attempt retry + exponential backoff (NEW) ───────
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(username, password)
                    server.sendmail(username, recipients, msg.as_string())

                logger.info(f"[EmailReply] ✅ Sent reply to {to_addr}"
                            + (f" (CC: {oncall})" if len(recipients) > 1 else ""))

                # Persist UID so we don't reply twice
                if uid:
                    _save_replied_uid(uid)

                return True

            except smtplib.SMTPException as smtp_err:
                wait = 2 ** attempt  # 2s, 4s, 8s
                if attempt < max_attempts:
                    logger.warning(
                        f"[EmailReply] Attempt {attempt}/{max_attempts} failed: "
                        f"{smtp_err} — retrying in {wait}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"[EmailReply] All {max_attempts} attempts failed for {to_addr}: {smtp_err}"
                    )
            except Exception as e:
                logger.warning(f"[EmailReply] Non-SMTP error sending reply: {e}")
                break   # Don't retry on non-SMTP errors

        return False

    # Run blocking SMTP call in thread pool — keeps event loop free
    return await __import__("asyncio").to_thread(_send)
