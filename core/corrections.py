"""Correction review provenance. Nothing is used for training until a reviewer verifies it."""
import json

from .auth import enforce_rbac
from .db import get_conn, fetch_all


def review_correction(correction_id: int, reviewer: str, actor_role: str,
                      status: str, reason: str, actor_email: str | None = None) -> None:
    enforce_rbac(actor_role, "can_review")
    if status not in {"verified", "rejected"}:
        raise ValueError("Correction status must be verified or rejected.")
    if not (reviewer or "").strip() or not (reason or "").strip():
        raise ValueError("A reviewer identity and reason are required.")
    conn = get_conn()
    try:
        correction = conn.execute("SELECT complaint_id FROM corrections WHERE id=?", (correction_id,)).fetchone()
        if not correction:
            raise ValueError("Correction example not found.")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO correction_reviews (correction_id,reviewer,status,reason) VALUES (?,?,?,?)",
                     (correction_id, reviewer.strip(), status, reason.strip()))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,reason,details) VALUES (?,?,?,?,?)",
                     (correction["complaint_id"], "correction_verified", actor_email or actor_role, reason.strip(),
                      json.dumps({"correction_id": correction_id, "status": status, "reviewer": reviewer.strip()})))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_verified_corrections():
    """Only the latest explicit verification can admit a correction to future offline training."""
    return fetch_all("SELECT c.* FROM corrections c WHERE (SELECT r.status FROM correction_reviews r "
                     "WHERE r.correction_id=c.id ORDER BY r.id DESC LIMIT 1)='verified' ORDER BY c.id")
