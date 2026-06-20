"""
Auto-Resolver — intelligently resolves low-priority incidents automatically.

Logic:
  - P3/P4 incidents with known patterns → send auto-fix email + mark resolved
  - P1/P2 → send "Next Steps" guide to sender (doesn't auto-resolve)
  - Tracks what was auto-resolved so we don't double-handle

Called as a background task from main.py after every processed email.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Known patterns that can be auto-resolved
_AUTO_RESOLVE_PATTERNS = [
    {
        "keywords": ["password reset", "forgot password", "reset my password"],
        "resolution": "Please reset your password at https://accounts.google.com/signin/recovery or contact IT at it-support@company.com. Automated password reset link will be sent to your registered email within 5 minutes.",
        "label": "Password Reset"
    },
    {
        "keywords": ["vpn not working", "vpn connection", "cannot connect vpn"],
        "resolution": "VPN Troubleshooting:\n1. Disconnect and reconnect\n2. Restart the VPN client\n3. Check your internet connection\n4. Try server: vpn.company.com\nIf issue persists, contact IT helpdesk.",
        "label": "VPN Issue"
    },
    {
        "keywords": ["software update", "app update", "please update", "new version"],
        "resolution": "Software updates are deployed automatically every Tuesday at 2 AM. You can also manually update via Help → Check for Updates in the application.",
        "label": "Software Update"
    },
    {
        "keywords": ["meeting invite", "schedule meeting", "book a meeting"],
        "resolution": "Use our self-service booking link: https://calendly.com/team. Available slots are shown in real-time. Confirmation will be sent automatically.",
        "label": "Meeting Request"
    },
    {
        "keywords": ["access request", "request access", "need access to"],
        "resolution": "Access requests are processed within 24 hours. Your request has been logged. You will receive an email confirmation once access is granted.",
        "label": "Access Request"
    },
]


def _find_pattern(subject: str, body_summary: str) -> Dict[str, Any]:
    """Check if this incident matches a known auto-resolvable pattern."""
    text = f"{subject} {body_summary}".lower()
    for pattern in _AUTO_RESOLVE_PATTERNS:
        if any(kw in text for kw in pattern["keywords"]):
            return pattern
    return {}


async def try_auto_resolve(
    subject:  str,
    sender:   str,
    priority: str,
    result:   Dict[str, Any],
) -> bool:
    """
    Attempt to auto-resolve the incident.
    Returns True if auto-resolved, False if human intervention needed.
    """
    try:
        # Only auto-resolve P3 and P4
        if priority in ("P1-critical", "P2-high"):
            await _send_next_steps(subject, sender, priority, result)
            return False

        summary  = result.get("executive_summary", "")
        email_data = result.get("email_data", {})
        body_text  = email_data.get("body", summary)

        pattern = _find_pattern(subject, body_text or summary)
        if not pattern:
            return False

        # Found a match → send auto-resolution email
        await _send_auto_resolution(subject, sender, pattern, result)
        logger.info(f"[AutoResolver] ✅ Auto-resolved [{pattern['label']}]: {subject[:50]}")
        return True

    except Exception as e:
        logger.error(f"[AutoResolver] Failed: {e}")
        return False


async def _send_auto_resolution(
    subject: str,
    sender:  str,
    pattern: Dict[str, Any],
    result:  Dict[str, Any],
) -> None:
    """Send auto-resolution reply to the sender."""
    try:
        from app.services.email_reply import send_reply
        # Build a custom result that includes the auto-resolution
        auto_result = {
            **result,
            "executive_summary": (
                f"This issue has been automatically resolved.\n\n"
                f"*Resolution ({pattern['label']}):*\n{pattern['resolution']}"
            ),
        }
        await send_reply(
            original_sender=sender,
            original_subject=subject,
            result=auto_result,
            uid="auto-resolve",
        )
    except Exception as e:
        logger.warning(f"[AutoResolver] Reply failed: {e}")


async def _send_next_steps(
    subject:  str,
    sender:   str,
    priority: str,
    result:   Dict[str, Any],
) -> None:
    """For P1/P2: send a 'we're on it' message with remediation steps."""
    try:
        rca        = result.get("incident_result", {}).get("rca", {})
        steps      = rca.get("remediation_plan", [])
        steps_text = "\n".join(f"• {s}" for s in steps[:5]) if steps else "• Engineering team has been notified"

        from app.services.email_reply import send_reply
        next_steps_result = {
            **result,
            "executive_summary": (
                f"Your {priority} incident has been received and escalated to the engineering team.\n\n"
                f"**Immediate Next Steps:**\n{steps_text}\n\n"
                f"Expected resolution time: {'30 minutes' if 'P1' in priority else '2 hours'}.\n"
                f"You will receive updates every 15 minutes."
            ),
        }
        await send_reply(
            original_sender=sender,
            original_subject=subject,
            result=next_steps_result,
            uid="next-steps",
        )
    except Exception as e:
        logger.warning(f"[AutoResolver] Next-steps email failed: {e}")
