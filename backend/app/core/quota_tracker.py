"""
Model Quota Tracker — tracks LLM API calls per model in-memory.

Exposed via GET /api/health/agents so you can see which models are being used
and how close you are to free-tier limits.

Free tier limits (for reference):
  Groq:          14,400 requests/day per model
  Gemini Flash:   1,500 requests/day
  Gemini Pro:        50 requests/day
"""
from collections import defaultdict
from datetime import datetime, date
from typing import Dict, Any

# In-memory call counter  {model_name: {date: count}}
_call_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
_error_counts: Dict[str, int] = defaultdict(int)

# Free-tier limits per model
FREE_TIER_LIMITS = {
    "llama-3.3-70b-versatile":  14400,
    "llama-3.1-70b-versatile":  14400,
    "llama3-70b-8192":          14400,
    "llama-3.1-8b-instant":     14400,
    "gemma2-9b-it":             14400,
    "llama3-8b-8192":           14400,
    "mixtral-8x7b-32768":       14400,
    "gemini-2.0-flash":          1500,
    "gemini-1.5-flash":          1500,
    "gemini-1.5-pro":              50,
    "gemini-2.0-pro":              50,
}


def record_call(model_name: str) -> None:
    """Record a successful LLM call for the given model."""
    today = str(date.today())
    # Strip provider prefix if present (e.g. "groq/llama-3.3..." → "llama-3.3...")
    name = model_name.split("/")[-1] if "/" in model_name else model_name
    _call_counts[name][today] += 1


def record_error(model_name: str) -> None:
    """Record a failed LLM call."""
    name = model_name.split("/")[-1] if "/" in model_name else model_name
    _error_counts[name] += 1


def get_stats() -> Dict[str, Any]:
    """Return today's usage stats for all models."""
    today = str(date.today())
    stats = {}
    all_models = set(list(_call_counts.keys()) + list(FREE_TIER_LIMITS.keys()))

    for model in all_models:
        today_calls = _call_counts[model][today]
        limit = FREE_TIER_LIMITS.get(model, None)
        errors = _error_counts.get(model, 0)

        stats[model] = {
            "calls_today": today_calls,
            "errors": errors,
            "limit_per_day": limit,
            "usage_pct": round((today_calls / limit * 100), 1) if limit else None,
            "status": (
                "ok" if limit is None or today_calls < limit * 0.8
                else "warning" if today_calls < limit
                else "exhausted"
            ),
        }

    # Filter out models with 0 calls and no errors (keep only active ones)
    active = {k: v for k, v in stats.items() if v["calls_today"] > 0 or v["errors"] > 0}
    # Always include known models even if 0 calls so user sees all limits
    known = {k: v for k, v in stats.items() if k in FREE_TIER_LIMITS}
    return {**known, **active}


def get_total_calls_today() -> int:
    today = str(date.today())
    return sum(counts[today] for counts in _call_counts.values())
