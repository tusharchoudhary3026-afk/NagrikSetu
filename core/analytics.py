"""Transparent reassignment and hotspot summaries; counts are not blame attribution."""
from datetime import datetime, timedelta, timezone

from .config import REASON_CODES, SIM_LABEL
from .db import fetch_all


def get_reassignment_breakdown():
    rows = fetch_all("SELECT reason_code, COUNT(*) AS count FROM ledger "
                     "WHERE event_type='transfer' AND reason_code IS NOT NULL GROUP BY reason_code")
    counts = {row["reason_code"]: row["count"] for row in rows}
    total = sum(counts.values())
    return {"total": total, "by_reason": {
        code: {"count": counts.get(code, 0), "denominator": total}
        for code in REASON_CODES
    }}


def get_ownership_gap_report():
    """Counts explicitly recorded ownership-overlap transfers by department pair."""
    rows = fetch_all("SELECT suggested_dept, final_dept, COUNT(*) AS count FROM ledger "
                     "WHERE event_type='transfer' AND reason_code='overlapping_ownership' "
                     "AND suggested_dept IS NOT NULL AND final_dept IS NOT NULL "
                     "GROUP BY suggested_dept, final_dept ORDER BY count DESC")
    denominator = sum(row["count"] for row in rows)
    return [{"from_department": row["suggested_dept"], "to_department": row["final_dept"],
             "count": row["count"], "denominator": denominator, "status_label": SIM_LABEL}
            for row in rows]


def get_case_reassignment_timeline(complaint_id: int):
    cases = fetch_all("SELECT case_id FROM complaints WHERE id=?", (complaint_id,))
    if not cases:
        return []
    return fetch_all(
        "SELECT l.id,l.complaint_id,c.case_id,c.parent_id,l.event_type,l.actor,l.suggested_dept,"
        "l.final_dept,l.reason,l.reason_code,l.details,l.created_at "
        "FROM ledger l JOIN complaints c ON c.id=l.complaint_id "
        "WHERE c.case_id=? ORDER BY l.id ASC", (cases[0]["case_id"],))


def detect_emerging_hotspots(min_count: int = 3, window_days: int = 7,
                             as_of: datetime | None = None, min_increase: int = 1):
    """Compare the latest window with the immediately preceding equal-length window."""
    if min_count < 1 or window_days < 1 or min_increase < 1:
        raise ValueError("Counts and time window must be positive.")
    end = as_of or datetime.now(timezone.utc)
    end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
    start = end - timedelta(days=window_days)
    baseline_start = start - timedelta(days=window_days)
    rows = fetch_all("SELECT location,issue,created_at,is_synthetic FROM complaints "
                     "WHERE location IS NOT NULL AND TRIM(location)<>'' AND LOWER(location)<>'unknown' "
                     "AND issue IS NOT NULL")
    groups = {}
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)
        except (AttributeError, TypeError, ValueError):
            continue
        key = (row["location"], row["issue"])
        item = groups.setdefault(key, {"observed": 0, "baseline": 0, "synthetic": False})
        if start <= created <= end:
            item["observed"] += 1
            item["synthetic"] = item["synthetic"] or bool(row["is_synthetic"])
        elif baseline_start <= created < start:
            item["baseline"] += 1
            item["synthetic"] = item["synthetic"] or bool(row["is_synthetic"])
    result = []
    for (location, category), values in groups.items():
        observed, baseline = values["observed"], values["baseline"]
        if observed < min_count or observed - baseline < min_increase:
            continue
        result.append({
            "location": location, "category": category,
            "window_start": start.isoformat(timespec="seconds"),
            "window_end": end.isoformat(timespec="seconds"),
            "window_days": window_days, "observed_count": observed,
            "baseline_count": baseline, "baseline_average": round(baseline / window_days, 3),
            "increase": observed - baseline,
            "status_label": SIM_LABEL if values["synthetic"] else "OBSERVED",
            "interpretation": "Potential concentration for staff review; not proof of cause or negligence.",
        })
    return sorted(result, key=lambda row: (-row["increase"], -row["observed_count"], row["location"]))


# Backward-compatible name used by older pages/scripts.
def detect_hotspots(min_count: int = 3, window_days: int = 7, as_of: datetime | None = None):
    return detect_emerging_hotspots(min_count=min_count, window_days=window_days, as_of=as_of)
