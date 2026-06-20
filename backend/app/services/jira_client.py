"""
Jira Client — creates real Jira tickets for P1/P2 incidents.

Setup:
  1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
  2. Create API Token → copy it
  3. Set in .env:
       JIRA_URL=https://your-domain.atlassian.net
       JIRA_EMAIL=you@yourcompany.com
       JIRA_API_TOKEN=your-api-token
       JIRA_PROJECT_KEY=OPS    ← your project key (e.g. OPS, IT, INFRA)
"""
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class JiraClient:
    """Reads credentials lazily so load_dotenv() order doesn't matter."""

    def _creds(self):
        return {
            "url":         os.getenv("JIRA_URL",          "").strip().rstrip("/"),
            "email":       os.getenv("JIRA_EMAIL",         "").strip(),
            "token":       os.getenv("JIRA_API_TOKEN",     "").strip(),
            "project_key": os.getenv("JIRA_PROJECT_KEY",  "OPS").strip().upper(),
        }

    def _is_configured(self) -> bool:
        c = self._creds()
        return bool(
            c["url"] and c["email"] and c["token"]
            and "your-domain" not in c["url"]
            and "your-api-token" not in c["token"]
        )

    async def create_ticket(
        self,
        summary:     str,
        description: str,
        priority:    str = "P3-medium",
        email_type:  str = "incident",
    ) -> Dict[str, Any]:
        """
        Creates a Jira ticket. Falls back to mock if credentials not set.
        Returns {"key": "OPS-123", "url": "https://..."}
        """
        if not self._is_configured():
            mock_key = f"MOCK-{abs(hash(summary)) % 9000 + 1000}"
            logger.info(f"[Jira] MOCK ticket: {mock_key} — {summary[:50]}")
            return {
                "key": mock_key,
                "url": f"https://mock.atlassian.net/browse/{mock_key}",
                "mock": True,
            }

        c = self._creds()

        # Map priority string to Jira priority name
        priority_map = {
            "P1-critical": "Highest",
            "P2-high":     "High",
            "P3-medium":   "Medium",
            "P4-low":      "Low",
        }
        jira_priority = priority_map.get(priority, "Medium")

        # Map email_type to Jira issue type
        issue_type_map = {
            "incident":   "Bug",
            "outage":     "Bug",
            "bug":        "Bug",
            "task":       "Task",
            "question":   "Task",
            "feature":    "Story",
            "meeting":    "Task",
        }
        issue_type = issue_type_map.get(email_type.lower(), "Task")

        payload = {
            "fields": {
                "project":     {"key": c["project_key"]},
                "summary":     summary[:255],
                "description": {
                    "type":    "doc",
                    "version": 1,
                    "content": [
                        {
                            "type":    "paragraph",
                            "content": [{"type": "text", "text": description[:3000]}]
                        }
                    ]
                },
                "issuetype":   {"name": issue_type},
                "priority":    {"name": jira_priority},
                "labels":      ["ai-ops-center", priority.lower().replace("-", "_")],
            }
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{c['url']}/rest/api/3/issue",
                    json=payload,
                    auth=(c["email"], c["token"]),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
            if r.status_code in (200, 201):
                data = r.json()
                key = data["key"]
                url = f"{c['url']}/browse/{key}"
                logger.info(f"[Jira] ✅ Ticket created: {key} — {summary[:50]}")
                return {"key": key, "url": url}
            else:
                logger.warning(f"[Jira] API error {r.status_code}: {r.text[:200]}")
                return {"error": f"Jira {r.status_code}", "key": "", "url": ""}
        except Exception as e:
            logger.error(f"[Jira] Request failed: {e}")
            return {"error": str(e), "key": "", "url": ""}

    async def add_comment(self, ticket_key: str, comment: str) -> bool:
        """Add a comment to an existing Jira ticket."""
        if not self._is_configured() or not ticket_key or "MOCK" in ticket_key:
            return False
        c = self._creds()
        payload = {
            "body": {
                "type":    "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": comment}]}
                ]
            }
        }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{c['url']}/rest/api/3/issue/{ticket_key}/comment",
                    json=payload,
                    auth=(c["email"], c["token"]),
                    headers={"Accept": "application/json"},
                )
            return r.status_code in (200, 201)
        except Exception as e:
            logger.warning(f"[Jira] Comment failed: {e}")
            return False


jira_service = JiraClient()
