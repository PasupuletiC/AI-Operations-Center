"""
Slack Client — sends P1/P2 incident alerts to a Slack channel.

Setup (2 minutes, no coding):
  1. Go to https://api.slack.com/apps → Create New App → From Scratch
  2. App Name: "AI Ops Center"  |  Workspace: your workspace
  3. Left sidebar → Incoming Webhooks → Toggle ON
  4. Click "Add New Webhook to Workspace" → pick #incidents channel
  5. Copy the webhook URL → set SLACK_WEBHOOK_URL in .env

That's it — no bot token, no OAuth, just the URL.
"""
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SlackClient:
    """Reads credentials lazily so load_dotenv() order doesn't matter."""

    def _webhook_url(self) -> str:
        return os.getenv("SLACK_WEBHOOK_URL", "").strip()

    def _is_configured(self) -> bool:
        url = self._webhook_url()
        return bool(url and url.startswith("https://hooks.slack.com/"))

    async def _post(self, payload: dict) -> bool:
        """POST payload to Slack Incoming Webhook."""
        if not self._is_configured():
            logger.debug("[Slack] Not configured — skipping alert")
            return False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self._webhook_url(), json=payload)
            if r.status_code == 200:
                logger.info("[Slack] ✅ Alert sent")
                return True
            else:
                logger.warning(f"[Slack] Error {r.status_code}: {r.text}")
                return False
        except Exception as e:
            logger.warning(f"[Slack] Request failed: {e}")
            return False

    async def send_p1_alert(
        self,
        subject: str,
        priority: str,
        email_type: str,
        department: str,
        ticket_key: str = "",
        summary: str = "",
    ) -> bool:
        """Send a rich P1/P2 incident block message to Slack."""
        color   = "#ef4444" if "P1" in priority else "#f97316"   # red / orange
        emoji   = "🔴" if "P1" in priority else "🟠"
        ticket_text = f"*Ticket:* `{ticket_key}`\n" if ticket_key else ""
        summary_text = f"\n_{summary[:200]}_" if summary else ""

        payload = {
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": f"{emoji} {priority.upper()} — AI Ops Center Alert"
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Subject:*\n{subject[:80]}"},
                                {"type": "mrkdwn", "text": f"*Priority:*\n`{priority}`"},
                                {"type": "mrkdwn", "text": f"*Type:*\n{email_type}"},
                                {"type": "mrkdwn", "text": f"*Department:*\n{department}"},
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"{ticket_text}"
                                    f"*Dashboard:* http://localhost:3000"
                                    f"{summary_text}"
                                )
                            }
                        },
                        {"type": "divider"}
                    ]
                }
            ]
        }
        return await self._post(payload)

    async def send_escalation(self, subject: str, minutes: int, ticket_key: str = "") -> bool:
        """Send escalation alert when P1 unresolved after N minutes."""
        ticket_text = f"*Ticket:* `{ticket_key}`\n" if ticket_key else ""
        payload = {
            "attachments": [
                {
                    "color": "#dc2626",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": f"🚨 ESCALATION — P1 Unresolved {minutes}+ min"}
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"*Subject:* {subject}\n"
                                    f"{ticket_text}"
                                    f"*Immediate action required!* Check the dashboard."
                                )
                            }
                        }
                    ]
                }
            ]
        }
        return await self._post(payload)

    async def send_notification(self, text: str) -> bool:
        """Send a simple text message to Slack."""
        return await self._post({"text": text})

    # Legacy method kept for compatibility with manager.py
    async def send_approval_request(self, incident_data: Dict[str, Any]) -> str:
        subject  = incident_data.get("subject", "Incident")
        priority = incident_data.get("priority", "unknown")
        await self.send_p1_alert(
            subject=subject,
            priority=priority,
            email_type=incident_data.get("email_type", "incident"),
            department=incident_data.get("department", "unknown"),
        )
        return "sent"


slack_service = SlackClient()
