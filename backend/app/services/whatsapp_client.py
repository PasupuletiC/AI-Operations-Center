"""
WhatsApp Client — sends P1/P2 alerts via Twilio WhatsApp API.

Setup (free sandbox, 5 minutes):
  1. Go to https://www.twilio.com/try-twilio → Free account
  2. Console → Messaging → Try it out → Send a WhatsApp message
  3. Follow sandbox join instructions (send "join <word>" to +14155238886)
  4. In Console → Account Info → copy Account SID and Auth Token
  5. Set in .env:
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your-auth-token
       TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   ← Twilio sandbox number
       TWILIO_WHATSAPP_TO=whatsapp:+91XXXXXXXXXX    ← your number with country code

For production: buy a Twilio number and enable WhatsApp on it.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Reads credentials lazily so load_dotenv() order doesn't matter."""

    def _creds(self):
        return {
            "sid":   os.getenv("TWILIO_ACCOUNT_SID",    "").strip(),
            "token": os.getenv("TWILIO_AUTH_TOKEN",      "").strip(),
            "from_": os.getenv("TWILIO_WHATSAPP_FROM",  "").strip(),
            "to":    os.getenv("TWILIO_WHATSAPP_TO",    "").strip(),
        }

    def _is_configured(self) -> bool:
        c = self._creds()
        return bool(
            c["sid"] and c["token"] and c["from_"] and c["to"]
            and c["sid"].startswith("AC")
            and "whatsapp:" in c["from_"]
            and "whatsapp:" in c["to"]
        )

    async def send_message(self, body: str) -> bool:
        """Send a WhatsApp message via Twilio REST API."""
        if not self._is_configured():
            logger.debug(f"[WhatsApp] Not configured — skipping: {body[:60]}")
            return False
        c = self._creds()
        try:
            import httpx, base64
            auth = base64.b64encode(f"{c['sid']}:{c['token']}".encode()).decode()
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{c['sid']}/Messages.json",
                    headers={"Authorization": f"Basic {auth}"},
                    data={"From": c["from_"], "To": c["to"], "Body": body},
                )
            data = r.json()
            if r.status_code in (200, 201):
                logger.info(f"[WhatsApp] ✅ Message sent: {data.get('sid')}")
                return True
            else:
                logger.warning(f"[WhatsApp] Error {r.status_code}: {data.get('message')}")
                return False
        except Exception as e:
            logger.warning(f"[WhatsApp] Request failed: {e}")
            return False

    async def send_p1_alert(
        self,
        subject:    str,
        priority:   str,
        email_type: str,
        department: str,
        ticket_key: str = "",
    ) -> bool:
        """Send a formatted P1/P2 WhatsApp alert."""
        emoji      = "🔴" if "P1" in priority else "🟠"
        ticket_line = f"\n🎫 Ticket: {ticket_key}" if ticket_key else ""
        body = (
            f"{emoji} *{priority.upper()} — AI Ops Center*\n\n"
            f"📧 {subject[:80]}\n"
            f"🏢 {department} | {email_type}"
            f"{ticket_line}\n\n"
            f"⚡ Check dashboard: http://localhost:3000"
        )
        return await self.send_message(body)

    async def send_escalation(self, subject: str, minutes: int, ticket_key: str = "") -> bool:
        """Send escalation alert when P1 is unresolved."""
        ticket_line = f"\n🎫 Ticket: {ticket_key}" if ticket_key else ""
        body = (
            f"🚨 *ESCALATION — P1 Unresolved {minutes}+ min*\n\n"
            f"📧 {subject[:80]}"
            f"{ticket_line}\n\n"
            f"⚠️ Immediate attention required!"
        )
        return await self.send_message(body)


whatsapp_service = WhatsAppClient()
