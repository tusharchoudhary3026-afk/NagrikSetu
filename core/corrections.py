"""Correction review provenance. Nothing is used for training until a reviewer verifies it."""
import json

from .auth import enforce_rbac
from .db import get_conn, fetch_all
from .geo import authorize_staff_complaint, scoped_complaint_ids, is_geography_admin


def review_correction(correction_id: int, reviewer: str, actor_role: str,
                      status: str, reason: str, actor_email: str | None = None,
                      actor_user: dict | None = None) -> None:
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
        authorize_staff_complaint(actor_role, correction["complaint_id"], actor_user)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO correction_reviews (correction_id,reviewer,status,reason) VALUES (?,?,?,?)",
                     (correction_id, reviewer.strip(), status, reason.strip()))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,reason,details) VALUES (?,?,?,?,?)",
                     (correction["complaint_id"], "correction_reviewed", actor_email or actor_role, reason.strip(),
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


def list_corrections(actor_user: dict, status: str = "all") -> list[dict]:
    """Return provenance rows only from the reviewer's verified geography."""
    enforce_rbac((actor_user or {}).get("role"), "can_manage_corrections")
    ids = scoped_complaint_ids(actor_user,
                               include_unassigned=is_geography_admin((actor_user or {}).get("email", "")))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = fetch_all(
        "SELECT c.*,p.case_id,p.issue,p.location,p.area_name, "
        "(SELECT r.status FROM correction_reviews r WHERE r.correction_id=c.id ORDER BY r.id DESC LIMIT 1) AS review_status, "
        "(SELECT r.reason FROM correction_reviews r WHERE r.correction_id=c.id ORDER BY r.id DESC LIMIT 1) AS review_reason, "
        "(SELECT r.reviewer FROM correction_reviews r WHERE r.correction_id=c.id ORDER BY r.id DESC LIMIT 1) AS reviewed_by "
        f"FROM corrections c JOIN complaints p ON p.id=c.complaint_id WHERE c.complaint_id IN ({marks}) ORDER BY c.id DESC",
        ids)
    if status == "verified":
        return [row for row in rows if row.get("review_status") == "verified"]
    if status == "excluded":
        return [row for row in rows if row.get("review_status") == "rejected"]
    if status == "unreviewed":
        return [row for row in rows if row.get("review_status") is None]
    if status != "all":
        raise ValueError("Choose all, verified, excluded, or unreviewed corrections.")
    return rows
