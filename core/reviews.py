"""Human review writes its ledger event and correction example atomically."""
import json

from .auth import enforce_rbac
from .config import REASON_CODES, REVIEW_ACTIONS
from .db import get_conn


def submit_review(complaint_id: int, actor_role: str, action: str, final_dept: str | None = None,
                  reason: str | None = None, reason_code: str | None = None,
                  actor_email: str | None = None) -> None:
    enforce_rbac(actor_role, "can_review")
    if action not in REVIEW_ACTIONS:
        raise ValueError("Choose a supported human review action.")
    if action in {"edit", "escalate", "transfer"}:
        if not (reason or "").strip():
            raise ValueError("A reason is required for this action.")
        if reason_code not in REASON_CODES:
            raise ValueError("Choose a valid transfer-reason code.")
    if action in {"accept", "edit", "transfer"} and not (final_dept or "").strip():
        raise ValueError("A final department is required for this action.")

    conn = get_conn()
    try:
        complaint = conn.execute("SELECT original_text FROM complaints WHERE id=?", (complaint_id,)).fetchone()
        if not complaint:
            raise ValueError("Complaint not found.")
        suggestion = conn.execute("SELECT top3 FROM suggestions WHERE complaint_id=? ORDER BY id DESC LIMIT 1",
                                  (complaint_id,)).fetchone()
        top3 = json.loads(suggestion["top3"]) if suggestion else []
        suggested = top3[0]["dept"] if top3 else None
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,suggested_dept,final_dept,reason,reason_code,details) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (complaint_id, action, actor_email or actor_role, suggested,
                      (final_dept or "").strip() or None, (reason or "").strip() or None,
                      reason_code if action in {"edit", "escalate", "transfer"} else None,
                      json.dumps({"suggestion_recorded": bool(suggestion)})))
        if action == "edit" and suggested and final_dept.strip() != suggested:
            conn.execute("INSERT INTO corrections (complaint_id,text,wrong_dept,correct_dept,suggested_dept,reason,reason_code,label_source) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (complaint_id, complaint["original_text"], suggested, final_dept.strip(),
                          suggested, (reason or "").strip(), reason_code, "reviewer_override"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
