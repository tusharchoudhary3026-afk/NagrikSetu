"""Downloadable, permission-checked ledger export."""
import json
from datetime import datetime, timezone

from core.auth import enforce_rbac, authorize_user_action
from core.db import fetch_all
from core.privacy import mask_text
from core.geo import STAFF_ROLES, authorize_staff_complaint, scoped_ids_clause


def generate_audit_export(actor_role: str, actor_user: dict | None = None) -> str:
    enforce_rbac(actor_role, "can_audit")
    if actor_role in STAFF_ROLES:
        if not actor_user or actor_user.get("role") != actor_role:
            raise PermissionError("Pass the authenticated staff account to export its assigned-area audit.")
        authorize_user_action(actor_user.get("id"), "can_audit")
        condition, ids = scoped_ids_clause(actor_user, "complaint_id", include_unassigned=True)
        events = fetch_all(f"SELECT * FROM ledger WHERE {condition} ORDER BY id ASC", ids)
    else:
        events = fetch_all("SELECT * FROM ledger ORDER BY id ASC")
    for event in events:
        if event.get("reason"):
            event["reason"] = mask_text(event["reason"])
    audit_package = {
        "system": "NagrikSetu human decision ledger",
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_events": len(events),
        "events": events,
    }
    return json.dumps(audit_package, indent=2, ensure_ascii=False)
