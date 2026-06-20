"""
Analytics Routes — provides data for the Analytics Dashboard section.

Endpoints:
  GET /api/analytics/overview    — total, priorities, avg processing time
  GET /api/analytics/sla         — SLA compliance per priority
  GET /api/analytics/trends      — daily counts for last 7 days
  GET /api/analytics/mttr        — mean time to resolve per priority
  GET /api/analytics/duplicates  — duplicate incident groups + stats
  GET /api/oncall/current        — who is on call right now
  GET /api/oncall/schedule       — upcoming schedule
  POST /api/oncall/schedule      — add on-call entry
  DELETE /api/oncall/{id}        — remove on-call entry
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

analytics_router = APIRouter()
oncall_router    = APIRouter()


# ── Pydantic models ─────────────────────────────────────────────────────────

class OnCallEntry(BaseModel):
    name:        str
    email:       str = ""
    phone:       str = ""
    telegram_id: str = ""
    whatsapp:    str = ""
    start_date:  str          # YYYY-MM-DD
    end_date:    str          # YYYY-MM-DD
    notes:       str = ""


# ── Analytics Endpoints ──────────────────────────────────────────────────────

@analytics_router.get("/overview")
async def analytics_overview() -> Dict[str, Any]:
    """High-level stats: totals, by-priority, avg speed."""
    try:
        from app.core.db import get_aggregate_stats, fetch_emails_since
        stats  = get_aggregate_stats()
        recent = fetch_emails_since(hours=24)
        today_count = len(recent)

        # By email type breakdown
        by_type: Dict[str, int] = {}
        for e in fetch_emails_since(hours=168):
            t = e.get("email_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            **stats,
            "today_count": today_count,
            "by_type":     by_type,
        }
    except Exception as e:
        logger.error(f"[Analytics] overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/sla")
async def analytics_sla() -> Dict[str, Any]:
    """SLA compliance stats for the last 7 days."""
    try:
        from app.services.sla_tracker import get_sla_compliance_stats, get_all_sla_statuses
        compliance = get_sla_compliance_stats()
        active     = get_all_sla_statuses()
        return {
            "compliance": compliance,
            "active_incidents": active,
            "sla_targets": {
                "P1-critical": "30 min",
                "P2-high":     "2 hours",
                "P3-medium":   "8 hours",
                "P4-low":      "24 hours",
            }
        }
    except Exception as e:
        logger.error(f"[Analytics] SLA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/trends")
async def analytics_trends() -> Dict[str, Any]:
    """Daily incident counts for the last 7 days."""
    try:
        from app.core.db import fetch_emails_since
        emails = fetch_emails_since(hours=168)

        # Group by date
        daily: Dict[str, Dict] = {}
        for i in range(7):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            daily[d] = {"date": d, "total": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}

        for e in emails:
            date = (e.get("processed_at") or "")[:10]
            if date in daily:
                daily[date]["total"] += 1
                priority = (e.get("priority") or "").split("-")[0]
                if priority in daily[date]:
                    daily[date][priority] += 1

        # Return sorted oldest → newest
        trend_list = sorted(daily.values(), key=lambda x: x["date"])
        return {"trends": trend_list}
    except Exception as e:
        logger.error(f"[Analytics] trends error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/mttr")
async def analytics_mttr() -> Dict[str, Any]:
    """
    Mean Time To Resolve per priority (based on kanban status changes).
    Uses process_ms as a proxy for now; resolved_at when available.
    """
    try:
        from app.core.db import fetch_emails_since
        emails = fetch_emails_since(hours=720)  # 30 days

        mttr: Dict[str, List[float]] = {}
        for e in emails:
            priority = e.get("priority", "unknown")
            if e.get("resolved"):
                # Use process_ms as proxy if resolved_at not stored
                ms = e.get("process_ms", 0)
                if ms > 0:
                    mttr.setdefault(priority, []).append(ms / 60000)  # convert to minutes

        result = {}
        for p, times in mttr.items():
            result[p] = {
                "avg_minutes":  round(sum(times) / len(times), 1),
                "min_minutes":  round(min(times), 1),
                "max_minutes":  round(max(times), 1),
                "sample_count": len(times),
            }

        return {"mttr_by_priority": result}
    except Exception as e:
        logger.error(f"[Analytics] MTTR error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/duplicates")
async def analytics_duplicates() -> Dict[str, Any]:
    """Duplicate incident groups and stats."""
    try:
        from app.services.duplicate_detector import get_duplicate_stats
        return get_duplicate_stats()
    except Exception as e:
        logger.error(f"[Analytics] duplicates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── On-Call Endpoints ────────────────────────────────────────────────────────

@oncall_router.get("/current")
async def oncall_current() -> Dict[str, Any]:
    """Who is on call right now."""
    try:
        from app.services.oncall_schedule import get_current_oncall
        person = get_current_oncall()
        return {"oncall": person, "as_of": datetime.now().strftime("%Y-%m-%d %H:%M")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@oncall_router.get("/schedule")
async def oncall_schedule_list() -> Dict[str, Any]:
    """Upcoming on-call schedule."""
    try:
        from app.services.oncall_schedule import get_oncall_schedule
        return {"schedule": get_oncall_schedule()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@oncall_router.post("/schedule")
async def oncall_add(entry: OnCallEntry) -> Dict[str, Any]:
    """Add a new on-call rotation entry."""
    try:
        from app.services.oncall_schedule import add_oncall_person
        result = add_oncall_person(entry.model_dump())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@oncall_router.delete("/schedule/{entry_id}")
async def oncall_delete(entry_id: int) -> Dict[str, Any]:
    """Remove an on-call entry."""
    try:
        from app.services.oncall_schedule import delete_oncall_entry
        ok = delete_oncall_entry(entry_id)
        return {"deleted": ok}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
