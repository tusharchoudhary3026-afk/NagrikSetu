"""Append-only decision ledger. Corrections ADD rows; old rows are never changed."""
import json
from .config import REASON_REQUIRED
from .db import execute, fetch_all


def log_event(complaint_id, event_type, actor, suggested_dept=None, final_dept=None,
              reason=None, reason_code=None, details=None):
    if event_type in REASON_REQUIRED and not (reason or "").strip():
        raise ValueError(f"A reason is mandatory for '{event_type}'.")
    if event_type in {"edit", "escalate", "transfer"} and reason_code not in {
        "wrong_category", "missing_info", "overlapping_ownership", "duplicate_report", "other"
    }:
        raise ValueError(f"A valid reason code is mandatory for '{event_type}'.")
    execute(
        "INSERT INTO ledger (complaint_id, event_type, actor, suggested_dept, final_dept, "
        "reason, reason_code, details) VALUES (?,?,?,?,?,?,?,?)",
        (complaint_id, event_type, actor, suggested_dept, final_dept, reason, reason_code,
         json.dumps(details) if details else None))


def history(complaint_id):
    return fetch_all("SELECT * FROM ledger WHERE complaint_id=? ORDER BY id", (complaint_id,))


def save_correction(complaint_id, text, wrong_dept, correct_dept,
                    reason=None, reason_code=None, label_source="reviewer_correction"):
    """Append a provenance-tagged training candidate. It is unverified and never trains automatically."""
    execute("INSERT INTO corrections (complaint_id,text,wrong_dept,correct_dept,suggested_dept,reason,reason_code,label_source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (complaint_id, text, wrong_dept, correct_dept, wrong_dept, reason, reason_code, label_source))
