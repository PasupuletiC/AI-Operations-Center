"""
Email Poller — reads real emails from Gmail/Outlook via IMAP.

Setup for Gmail:
  1. Go to Google Account → Security → 2-Step Verification → App Passwords
  2. Generate an App Password for "Mail"
  3. Add to .env:
       EMAIL_IMAP_HOST=imap.gmail.com
       EMAIL_USERNAME=you@gmail.com
       EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   (App Password, not your real password)

Setup for Outlook/Hotmail:
  1. Enable IMAP in Outlook settings
  2. Add to .env:
       EMAIL_IMAP_HOST=imap-mail.outlook.com
       EMAIL_USERNAME=you@outlook.com
       EMAIL_PASSWORD=your_password

The poller runs as a FastAPI background task.
It checks for UNSEEN emails every POLL_INTERVAL_SECONDS seconds,
processes each through the full agent pipeline, then marks them as SEEN.
"""
import os
import json
import imaplib
import email
import asyncio
import logging
from email.header import decode_header
from typing import Optional, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = int(os.getenv("EMAIL_POLL_INTERVAL", "30"))

# Path to persist processed UIDs across restarts
_UID_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "processed_uids.json")
_UID_CACHE_FILE = os.path.normpath(_UID_CACHE_FILE)

# Senders to skip (system/bot emails — not real incidents)
SKIP_SENDERS = [
    "no-reply@accounts.google.com",
    "no-reply@google.com",
    "noreply@",
    "mailer-daemon@",
    "postmaster@",
    "donotreply@",
    "do-not-reply@",
    "notifications@",
    "alerts@",
    "bounce@",
    "security@accounts.google.com",
]


def _load_uid_cache() -> set:
    """Load persisted UIDs from disk (survives server restarts)."""
    try:
        if os.path.exists(_UID_CACHE_FILE):
            with open(_UID_CACHE_FILE, "r") as f:
                data = json.load(f)
                # Only keep UIDs from today to prevent the file growing unbounded
                today = datetime.now().strftime("%Y-%m-%d")
                return set(data.get(today, []))
    except Exception:
        pass
    return set()


def _save_uid_cache(uids: set) -> None:
    """Persist current UIDs to disk."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        existing = {}
        if os.path.exists(_UID_CACHE_FILE):
            with open(_UID_CACHE_FILE, "r") as f:
                existing = json.load(f)
        # Keep only today's UIDs in the file (auto-cleanup old days)
        existing = {today: list(uids)}
        with open(_UID_CACHE_FILE, "w") as f:
            json.dump(existing, f)
    except Exception as e:
        logger.warning(f"[EmailPoller] Could not save UID cache: {e}")


def _is_bot_sender(sender: str) -> bool:
    """Return True if this email is from an automated system (not a real person)."""
    sender_lower = sender.lower()
    return any(skip in sender_lower for skip in SKIP_SENDERS)



def _decode_header_value(value: str) -> str:
    """Decode encoded email header (handles UTF-8, base64, etc)."""
    parts = decode_header(value)
    decoded = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    """Extract plain text body from email (handles multipart)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition   = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body += payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body.strip()


# In-memory set of already-processed email UIDs — loaded from disk on startup
_processed_uids: set = _load_uid_cache()

# Max email body length sent to LLM (saves tokens)
_MAX_BODY_CHARS = 2000


def _fetch_new_emails(
    host: str,
    username: str,
    password: str,
    since_minutes: int = 60,
    max_fetch: int = 10,
) -> list[dict]:
    """
    Connect via IMAP, fetch recent emails (last `since_minutes` minutes).
    Uses time-based search + UID deduplication instead of UNSEEN-only,
    so it catches emails Gmail auto-marks as read.
    """
    from datetime import datetime, timedelta

    results = []
    try:
        mail = imaplib.IMAP4_SSL(host, 993)
        mail.login(username, password)

        # Try primary INBOX first; fall back to "[Gmail]/All Mail" if empty
        folders_to_try = ["INBOX", '"[Gmail]/All Mail"']
        found_uids = []

        for folder in folders_to_try:
            try:
                status, _ = mail.select(folder, readonly=False)
                if status != "OK":
                    continue

                # Search emails received in the last `since_minutes` minutes
                since_dt  = datetime.now() - timedelta(minutes=since_minutes)
                since_str = since_dt.strftime("%d-%b-%Y")
                status2, data = mail.search(None, f"SINCE {since_str}")
                if status2 == "OK" and data[0]:
                    found_uids = data[0].split()
                    # Filter out already-processed UIDs
                    new_uids = [u for u in found_uids if u.decode() not in _processed_uids]
                    if new_uids:
                        found_uids = new_uids
                        break  # Use this folder
            except Exception:
                continue

        if not found_uids:
            mail.logout()
            return []

        # Re-select last successful folder (now writable to mark as SEEN)
        for uid in reversed(found_uids[-max_fetch:]):
            try:
                status, msg_data = mail.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject  = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender   = _decode_header_value(msg.get("From", "unknown"))
                date_str = msg.get("Date", "")
                body     = _extract_body(msg)

                uid_str = uid.decode()

                # Skip bot / system emails
                if _is_bot_sender(sender):
                    logger.debug(f"[EmailPoller] Skipping bot email from {sender}")
                    _processed_uids.add(uid_str)
                    _save_uid_cache(_processed_uids)
                    continue

                _processed_uids.add(uid_str)
                _save_uid_cache(_processed_uids)  # persist immediately

                if not body.strip():
                    continue  # Skip image-only / empty emails

                # Truncate body to save LLM tokens
                if len(body) > _MAX_BODY_CHARS:
                    body = body[:_MAX_BODY_CHARS] + "\n...[truncated]"

                full_text = (
                    f"From: {sender}\n"
                    f"Subject: {subject}\n"
                    f"Date: {date_str}\n\n"
                    f"{body}"
                )

                results.append({
                    "uid":         uid_str,
                    "subject":     subject,
                    "sender":      sender,
                    "body":        full_text,
                    "received_at": date_str,
                })

                # Mark as SEEN so inbox stays clean
                mail.store(uid, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.warning(f"[EmailPoller] Error reading uid {uid}: {e}")
                continue

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error(f"[EmailPoller] IMAP login failed: {e}")
        raise e
    except Exception as e:
        logger.error(f"[EmailPoller] Unexpected error: {e}")
        raise e

    return results


class EmailPoller:
    """
    Background service that polls an IMAP inbox and routes
    new emails through the AI agent pipeline automatically.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.processed_count = 0
        self.last_poll: Optional[str] = None
        self.last_error: Optional[str] = None

    # ── Read env vars fresh each time (survives uvicorn hot-reload) ──────────
    @property
    def host(self)     -> str: return os.getenv("EMAIL_IMAP_HOST", "")
    @property
    def username(self) -> str: return os.getenv("EMAIL_USERNAME",  "")
    @property
    def password(self) -> str: return os.getenv("EMAIL_PASSWORD",  "")
    @property
    def enabled(self)  -> bool: return bool(self.host and self.username and self.password)

    def is_configured(self) -> bool:
        return self.enabled

    async def start(self, process_fn: Callable[[str], Awaitable[None]]) -> None:
        """
        Start polling in background.
        process_fn: async function that accepts raw_email string and runs the pipeline.
        """
        if not self.enabled:
            logger.info("[EmailPoller] Not configured — set EMAIL_IMAP_HOST, EMAIL_USERNAME, EMAIL_PASSWORD in .env")
            return

        logger.info(f"[EmailPoller] Starting — polling {self.username} every {POLL_INTERVAL_SECONDS}s")
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(process_fn))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self, process_fn: Callable[[str], Awaitable[None]]) -> None:
        backoff = 0
        while self._running:
            try:
                self.last_poll = datetime.now().strftime("%H:%M:%S")
                emails = await asyncio.to_thread(
                    _fetch_new_emails,
                    self.host, self.username, self.password
                )
                # Cap to 3 emails per poll cycle to avoid rate-limit storms
                for em in emails[:3]:
                    logger.info(f"[EmailPoller] Auto-processing: {em['subject']} from {em['sender']}")
                    try:
                        await process_fn(em["body"])
                        self.processed_count += 1
                    except Exception as e:
                        logger.error(f"[EmailPoller] Agent pipeline error for email: {e}")
                        self.last_error = str(e)
                    # Small pause between emails to respect Groq rate limits
                    await asyncio.sleep(3)
                
                # Success! Reset backoff
                backoff = 0

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"[EmailPoller] Poll loop error: {e}")
                # Exponential backoff: max 300 seconds (5 mins)
                backoff = min(backoff * 2 if backoff > 0 else POLL_INTERVAL_SECONDS, 300)
                logger.warning(f"[EmailPoller] Backing off for {backoff} seconds before retrying...")
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def status(self) -> dict:
        return {
            "enabled":         self.enabled,
            "username":        self.username if self.enabled else None,
            "host":            self.host     if self.enabled else None,
            "poll_interval_s": POLL_INTERVAL_SECONDS,
            "running":         self._running,
            "processed_count": self.processed_count,
            "last_poll":       self.last_poll,
            "last_error":      self.last_error,
        }


# Module-level singleton
email_poller = EmailPoller()
