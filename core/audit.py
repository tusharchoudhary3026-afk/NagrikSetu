"""Downloadable, permission-checked ledger export."""
import json
from datetime import datetime, timezone

from core.auth import enforce_rbac
from core.db import fetch_all
from core.privacy import mask_text


def generate_audit_export(actor_role: str) -> str:
    enforce_rbac(actor_role, "can_audit")
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
