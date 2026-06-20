"""
Telegram Bot Client — sends P1/P2 alerts and escalation notices to Telegram.

Setup (optional — works without it, just logs instead):
  1. Message @BotFather on Telegram → /newbot → copy token
  2. Get your chat ID: message your bot, then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env

Uses httpx (already installed). Zero new dependencies.
"""
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TelegramClient:
    """Reads credentials lazily so load_dotenv() order doesn't matter."""

    def _creds(self):
        """Always read fresh from env (supports runtime reload)."""
        token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
        return token, chat_id

    def _is_configured(self) -> bool:
        token, chat_id = self._creds()
        return bool(
            token and chat_id
            and "your-token" not in token
            and "your-chat" not in chat_id
            and len(token) > 10
        )

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a markdown-formatted message to the configured Telegram chat."""
        if not self._is_configured():
            logger.debug(f"[Telegram] Not configured — skipping: {text[:60]}")
            return False

        token, chat_id = self._creds()
        base = f"https://api.telegram.org/bot{token}"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{base}/sendMessage",
                    json={
                        "chat_id":    chat_id,
                        "text":       text,
                        "parse_mode": parse_mode,
                    },
                )
            data = r.json()
            if data.get("ok"):
                logger.info("[Telegram] ✅ Message sent")
                return True
            else:
                logger.warning(f"[Telegram] API error: {data.get('description')}")
                return False
        except Exception as e:
            logger.warning(f"[Telegram] Request failed: {e}")
            return False

    async def send_p1_alert(self, email_data: Dict[str, Any],
                             ticket_key: str = "") -> bool:
        """Send a P1/P2 incident alert with priority and context."""
        priority   = email_data.get("priority",   "unknown")
        email_type = email_data.get("email_type", "incident")
        dept       = email_data.get("department", "unknown")
        subject    = email_data.get("subject",    "No subject")

        emoji      = "🔴" if "P1" in priority else "🟠"
        ticket_line = f"\n🎫 *Ticket:* `{ticket_key}`" if ticket_key else ""

        text = (
            f"{emoji} *{priority.upper()} — AI Ops Center*\n\n"
            f"📧 *Subject:* {subject}\n"
            f"🏢 *Dept:* {dept}   •   *Type:* {email_type}"
            f"{ticket_line}\n\n"
            f"⚡ Processing automatically. Check the dashboard."
        )
        return await self.send_message(text)

    async def send_escalation(self, subject: str, minutes: int,
                               ticket_key: str = "") -> bool:
        """Send an escalation alert when P1 is unresolved after N minutes."""
        ticket_line = f"🎫 Ticket: `{ticket_key}`\n" if ticket_key else ""
        text = (
            f"🚨 *ESCALATION — P1 Unresolved {minutes}+ min*\n\n"
            f"📧 *Subject:* {subject}\n"
            f"{ticket_line}"
            f"⚠️ *Immediate attention required!*"
        )
        return await self.send_message(text)

    async def send_digest_summary(self, stats: Dict[str, Any]) -> bool:
        """Send a brief daily stats ping to Telegram."""
        total   = stats.get("total_processed", 0)
        p1      = stats.get("by_priority", {}).get("P1", 0)
        replies = stats.get("replies_sent", 0)
        text    = (
            f"📊 *Daily Ops Digest*\n\n"
            f"Processed: *{total}* emails\n"
            f"P1 Critical: *{p1}*\n"
            f"Replies sent: *{replies}*"
        )
        return await self.send_message(text)


# Singleton — imported by manager.py and escalation_engine.py
telegram_service = TelegramClient()
