"""Area/category hotspot review signals, scoped to the authenticated staff member."""
from datetime import datetime, time, timedelta, timezone
import math

from .config import SIM_LABEL, feature_enabled
from .intake import normalize_location
from .staff_dashboard import _parse_time, list_staff_cases


def _date_start(value):
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _date_end(value):
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)


def detect_hotspot_signals(actor_user, *, window_days=7, as_of=None, start_date=None, end_date=None,
                           area_filter=None, category_filter=None, min_count=5, multiplier=2.0):
    """Compare a scoped current period with the preceding equal period.

    The default rule is a review signal only: at least five reports and at least
    twice the preceding comparable count. No location is inferred for unknown cases.
    """
    if not 1 <= int(window_days) <= 90 or int(min_count) < 1 or float(multiplier) < 1:
        raise ValueError("Choose a 1–90 day window and positive hotspot thresholds.")
    if not feature_enabled("hotspots"):
        raise PermissionError("Hotspot review signals are disabled by configuration.")
    cases = list_staff_cases(actor_user)
    now = as_of or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    if start_date is not None and end_date is not None:
        current_start, current_end = _date_start(start_date), _date_end(end_date)
        if current_end <= current_start or (current_end - current_start).days > 90:
            raise ValueError("Choose a valid date range of no more than 90 days.")
        duration = current_end - current_start
    else:
        current_end = now
        duration = timedelta(days=int(window_days))
        current_start = current_end - duration
    baseline_start = current_start - duration
    if (area_filter or "All authorized areas") not in {"", "All authorized areas"}:
        area_key_filter = normalize_location(area_filter)
    else:
        area_key_filter = None
    category_key_filter = normalize_location(category_filter) if category_filter and category_filter != "All categories" else None

    current_rows, baseline_rows = [], []
    groups = {}
    areas, categories = set(), set()
    for case in cases:
        created = _parse_time(case.get("created_at"))
        if not created or not baseline_start <= created < current_end:
            continue
        area_code = (case.get("area_code") or "").strip().casefold()
        raw_area = case.get("area_name") or case.get("location")
        if not raw_area or normalize_location(str(raw_area)) in {"unknown", "not known"}:
            display_area, group_area = "Unknown area", "__unknown_area__"
        else:
            display_area = str(raw_area)
            group_area = area_code or (normalize_location(display_area) or "__unknown_area__")
        raw_category = case.get("issue") or "Uncategorized"
        category_key = normalize_location(str(raw_category)) or "uncategorized"
        areas.add(display_area)
        categories.add(str(raw_category))
        if area_key_filter and area_key_filter not in {normalize_location(display_area), group_area}:
            continue
        if category_key_filter and category_key_filter != category_key:
            continue
        group = groups.setdefault((group_area, category_key), {
            "area": display_area, "category": str(raw_category), "current_ids": [],
            "baseline_ids": [], "synthetic": False,
        })
        group["synthetic"] = group["synthetic"] or bool(case.get("is_synthetic"))
        if current_start <= created < current_end:
            current_rows.append(case)
            group["current_ids"].append(case["id"])
        else:
            baseline_rows.append(case)
            group["baseline_ids"].append(case["id"])

    rule = f"at least {multiplier:g}x baseline and at least {int(min_count)} complaints in the current period"
    signals = []
    for group in groups.values():
        current_count, baseline_count = len(group["current_ids"]), len(group["baseline_ids"])
        if current_count < int(min_count) or current_count < math.ceil(baseline_count * float(multiplier)):
            continue
        signals.append({
            "area": group["area"], "category": group["category"],
            "current_count": current_count, "baseline_count": baseline_count,
            "increase": current_count - baseline_count,
            "change_percent": round((current_count - baseline_count) * 100 / baseline_count, 1)
            if baseline_count else None,
            "comparison_start": baseline_start.isoformat(timespec="seconds"),
            "comparison_end": current_start.isoformat(timespec="seconds"),
            "current_start": current_start.isoformat(timespec="seconds"),
            "current_end": current_end.isoformat(timespec="seconds"),
            "window_days": duration.days, "rule": rule,
            "complaint_ids": sorted(group["current_ids"]),
            "data_label": SIM_LABEL if group["synthetic"] else "OBSERVED",
            "interpretation": "Potential hotspot review signal; not proof of cause, negligence, or department failure.",
        })
    signals.sort(key=lambda item: (-item["increase"], -item["current_count"], item["area"], item["category"]))
    sufficient = bool(current_rows or baseline_rows)
    return {
        "status": "ready" if sufficient else "insufficient_data",
        "rule": rule, "current_count": len(current_rows), "baseline_count": len(baseline_rows),
        "areas_flagged": len(signals), "current_start": current_start.isoformat(timespec="seconds"),
        "current_end": current_end.isoformat(timespec="seconds"),
        "comparison_start": baseline_start.isoformat(timespec="seconds"),
        "comparison_end": current_start.isoformat(timespec="seconds"),
        "window_days": duration.days, "hotspots": signals,
        "available_areas": sorted(areas, key=str.casefold),
        "available_categories": sorted(categories, key=str.casefold),
        "data_label": SIM_LABEL if any(bool(case.get("is_synthetic")) for case in current_rows + baseline_rows)
        else "OBSERVED",
    }


# Backward-compatible name used by older pages/scripts.
def detect_hotspots(min_count=5, window_days=7, as_of=None, actor_user=None):
    if actor_user is None:
        raise PermissionError("An authenticated staff account is required for hotspot results.")
    return detect_hotspot_signals(actor_user, min_count=min_count, window_days=window_days, as_of=as_of)
