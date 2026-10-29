"""Helpers for distinguishing a ranked guess from an actionable suggestion."""


def selected_department(route_result: dict | None) -> str | None:
    """Return a top department only when routing did not abstain."""
    if not isinstance(route_result, dict) or route_result.get("abstained", True):
        return None
    top3 = route_result.get("top3") or []
    if not top3 or not isinstance(top3[0], dict):
        return None
    department = top3[0].get("dept")
    return department.strip() if isinstance(department, str) and department.strip() else None
