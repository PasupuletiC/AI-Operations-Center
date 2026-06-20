"""
Duplicate Detector — groups emails about the same incident.

Uses lightweight text similarity (difflib, zero new deps).
Compares incoming email subject + body against last 24h incidents.
If similarity >= threshold, marks as duplicate and links to parent.

Saves noisy environments from creating 10 tickets for one outage.
"""
import logging
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.72   # 72% similar → duplicate
WINDOW_HOURS        = 24      # Only compare against last 24h


def _similarity(a: str, b: str) -> float:
    """Compute normalized similarity ratio between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _normalize(text: str) -> str:
    """Remove common noise words from subject lines."""
    noise = ["re:", "fwd:", "fw:", "[urgent]", "[critical]", "[p1]", "[p2]",
             "alert:", "warning:", "critical:", "urgent:", "!!"]
    text = text.lower().strip()
    for n in noise:
        text = text.replace(n, "")
    return text.strip()


def find_duplicate(
    subject: str,
    body_preview: str = "",
    priority: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Check if this email is a duplicate of a recent incident.

    Returns:
      None if no duplicate found.
      {"parent_id": str, "parent_subject": str, "similarity": float}
      if a duplicate is found.
    """
    try:
        from app.core.db import fetch_emails_since
        recent = fetch_emails_since(hours=WINDOW_HOURS)
    except Exception as e:
        logger.warning(f"[DuplicateDetector] DB read failed: {e}")
        return None

    norm_subject = _normalize(subject)

    best_match: Optional[Dict] = None
    best_score = 0.0

    for email in recent:
        candidate_subject = _normalize(email.get("subject", ""))
        candidate_summary = email.get("summary", "") or ""

        # Subject similarity
        subj_score = _similarity(norm_subject, candidate_subject)

        # Body/summary similarity (lower weight)
        body_score = _similarity(body_preview[:200], candidate_summary[:200]) if body_preview else 0

        # Combined score — subject is more reliable
        combined = subj_score * 0.7 + body_score * 0.3

        if combined >= SIMILARITY_THRESHOLD and combined > best_score:
            best_score = combined
            best_match = {
                "parent_id":      email.get("id"),
                "parent_subject": email.get("subject", ""),
                "parent_priority": email.get("priority", ""),
                "similarity":     round(combined, 3),
                "subject_score":  round(subj_score, 3),
                "body_score":     round(body_score, 3),
            }

    return best_match


def get_duplicate_groups() -> List[Dict[str, Any]]:
    """
    Return all incidents grouped by similarity (for the analytics dashboard).
    Groups incidents that share subject similarity >= threshold.
    """
    try:
        from app.core.db import fetch_emails_since
        emails = fetch_emails_since(hours=168)  # 7 days
    except Exception as e:
        logger.error(f"[DuplicateDetector] get_groups failed: {e}")
        return []

    groups: List[Dict] = []
    assigned: set = set()

    for i, email in enumerate(emails):
        if email["id"] in assigned:
            continue
        group = {
            "parent_id":      email["id"],
            "parent_subject": email.get("subject", ""),
            "priority":       email.get("priority", ""),
            "duplicates":     [],
            "count":          1,
        }
        norm_a = _normalize(email.get("subject", ""))

        for j, other in enumerate(emails):
            if i == j or other["id"] in assigned:
                continue
            norm_b = _normalize(other.get("subject", ""))
            if _similarity(norm_a, norm_b) >= SIMILARITY_THRESHOLD:
                group["duplicates"].append({
                    "id":      other["id"],
                    "subject": other.get("subject", ""),
                    "processed_at": other.get("processed_at", ""),
                })
                group["count"] += 1
                assigned.add(other["id"])

        if group["count"] > 1:
            groups.append(group)
        assigned.add(email["id"])

    # Sort by most duplicates first
    groups.sort(key=lambda g: g["count"], reverse=True)
    return groups


def get_duplicate_stats() -> Dict[str, Any]:
    """Return summary stats on duplicate incidents."""
    groups = get_duplicate_groups()
    total_duplicates = sum(g["count"] - 1 for g in groups)
    return {
        "total_groups":     len(groups),
        "total_duplicates": total_duplicates,
        "top_groups":       groups[:5],
    }
