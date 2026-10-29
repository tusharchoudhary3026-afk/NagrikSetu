"""Citizen/staff review requests with transactional, append-only resolution events."""
import json

from .auth import enforce_rbac
from .db import get_conn
from .geo import authorize_staff_complaint
from .auth import enforce_rbac


REVIEW_REASON_CATEGORIES = {"wrong_department", "multiple_issues", "missing_context", "other"}


def create_challenge(complaint_id: int, raised_by: str, reason: str, actor_email: str | None = None,
                     actor_user: dict | None = None, citizen_user_id: int | None = None,
                     reason_category: str = "other") -> int:
    if raised_by not in {"citizen", "staff"} or not (reason or "").strip():
        raise ValueError("A valid requester and a reason are required.")
    if reason_category not in REVIEW_REASON_CATEGORIES:
        raise ValueError("Choose a valid review reason category.")
    from .config import feature_enabled
    if raised_by == "citizen" and not feature_enabled("citizen_review"):
        raise PermissionError("Citizen routing review is temporarily unavailable.")
    conn = get_conn()
    try:
        complaint = conn.execute("SELECT submitted_by FROM complaints WHERE id=?", (complaint_id,)).fetchone()
        if not complaint:
            raise ValueError("Complaint not found.")
        if raised_by == "staff":
            if not actor_user:
                raise PermissionError("Pass the authenticated staff account to check its assigned area.")
            enforce_rbac(actor_user.get("role"), "can_review")
            authorize_staff_complaint(actor_user.get("role"), complaint_id, actor_user)
        elif citizen_user_id is None or complaint["submitted_by"] != citizen_user_id:
            raise PermissionError("Residents can request review only for their own complaint.")
        else:
            account = conn.execute("SELECT role,active FROM users WHERE id=?", (citizen_user_id,)).fetchone()
            if not account or not account["active"] or account["role"] != "public":
                raise PermissionError("An active resident account is required.")
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM challenges WHERE complaint_id=? AND status='open' LIMIT 1",
                         (complaint_id,)).fetchone():
            raise ValueError("A review request is already open for this complaint.")
        cur = conn.execute("INSERT INTO challenges (complaint_id,raised_by,reason,reason_category) VALUES (?,?,?,?)",
                           (complaint_id, raised_by, reason.strip(), reason_category))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,reason,reason_code,details) "
                     "VALUES (?,?,?,?,?,?)",
                     (complaint_id, "challenge", actor_email or raised_by, reason.strip(), None,
                      json.dumps({"reason_category": reason_category})))
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_challenge(challenge_id: int, actor_user: dict) -> None:
    """Assign an open in-scope request to the acting reviewer with an audit event."""
    if not actor_user or actor_user.get("role") != "reviewer":
        raise PermissionError("Only a reviewer can claim a citizen review request.")
    enforce_rbac(actor_user["role"], "can_review")
    actor_email = (actor_user.get("email") or "").strip().casefold()
    if not actor_email:
        raise PermissionError("An authenticated reviewer account is required.")
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        challenge = conn.execute("SELECT complaint_id,status,assigned_reviewer FROM challenges WHERE id=?",
                                 (challenge_id,)).fetchone()
        if not challenge or challenge["status"] != "open":
            raise ValueError("This review request is no longer open.")
        authorize_staff_complaint(actor_user["role"], challenge["complaint_id"], actor_user)
        if challenge["assigned_reviewer"] and challenge["assigned_reviewer"].casefold() != actor_email:
            raise PermissionError("This review request is assigned to another reviewer.")
        if not challenge["assigned_reviewer"]:
            conn.execute("UPDATE challenges SET assigned_reviewer=? WHERE id=? AND status='open' "
                         "AND assigned_reviewer IS NULL", (actor_email, challenge_id))
            conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,details) VALUES (?,?,?,?)",
                         (challenge["complaint_id"], "challenge_assigned", actor_email,
                          json.dumps({"challenge_id": challenge_id, "assigned_reviewer": actor_email})))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_challenge(challenge_id: int, actor_role: str, resolution: str, outcome: str,
                      final_dept: str | None = None, reason_code: str | None = None,
                      actor_email: str | None = None, actor_user: dict | None = None,
                      split_parts: list[dict] | None = None) -> None:
    if actor_role != "reviewer":
        raise PermissionError("Only an authorized reviewer can resolve a citizen review request.")
    enforce_rbac(actor_role, "can_review")
    resolution = (resolution or "").strip()
    if not resolution:
        raise ValueError("A resolution reason is required.")
    if outcome not in {"accept", "edit", "escalate", "split"}:
        raise ValueError("Choose keep routing, change department, split, or escalate.")
    if outcome == "edit" and not (final_dept or "").strip():
        raise ValueError("A final department is required when changing the route.")
    if outcome in {"edit", "escalate"} and reason_code not in {
        "wrong_category", "missing_info", "overlapping_ownership", "duplicate_report", "other"
    }:
        raise ValueError("Choose a valid reason code for this decision.")
    if outcome == "split" and (not split_parts or len(split_parts) < 2):
        raise ValueError("A split decision needs at least two reviewed sub-issues.")

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        challenge = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if not challenge:
            raise ValueError("Review request not found.")
        if challenge["status"] != "open":
            raise ValueError("This review request has already been resolved.")
        authorize_staff_complaint(actor_role, challenge["complaint_id"], actor_user)
        if (challenge["assigned_reviewer"] and actor_user and
                challenge["assigned_reviewer"].casefold() != (actor_user.get("email") or "").casefold()):
            raise PermissionError("This review request is assigned to another reviewer.")
        suggestion = conn.execute(
            "SELECT top3,abstained FROM suggestions WHERE complaint_id=? ORDER BY id DESC LIMIT 1",
            (challenge["complaint_id"],)).fetchone()
        import json
        top3 = json.loads(suggestion["top3"]) if suggestion else []
        from .suggestions import selected_department
        suggested = selected_department({"top3": top3, "abstained": bool(suggestion and suggestion["abstained"])}) if suggestion else None
        conn.execute("UPDATE challenges SET status='resolved',resolved_by=?,resolution=?,outcome=?,"
                     "resolved_at=datetime('now'),assigned_reviewer=COALESCE(assigned_reviewer,?) "
                     "WHERE id=? AND status='open'",
                     (actor_email or actor_role, resolution, outcome, actor_email, challenge_id))
        details = {"challenge_id": challenge_id, "outcome": outcome}
        if outcome == "split":
            from .splitter import persist_confirmed_split
            case = conn.execute("SELECT case_id FROM complaints WHERE id=?",
                                (challenge["complaint_id"],)).fetchone()
            details["child_ids"] = persist_confirmed_split(
                conn, challenge["complaint_id"], case["case_id"], split_parts, actor_role,
                actor_email=actor_email, actor_user=actor_user, write_parent_event=False)
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,suggested_dept,final_dept,reason,reason_code,details) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (challenge["complaint_id"], "challenge_resolved", actor_email or actor_role, suggested,
                      final_dept if outcome == "edit" else suggested, resolution, reason_code,
                      json.dumps(details)))
        if outcome == "split":
            conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,details) VALUES (?,?,?,?)",
                         (challenge["complaint_id"], "split_confirmed", actor_email or actor_role,
                          json.dumps({"child_ids": details["child_ids"], "challenge_id": challenge_id})))
        if outcome != "split":
            conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,suggested_dept,final_dept,reason,reason_code,details) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (challenge["complaint_id"], outcome, actor_email or actor_role, suggested,
                          final_dept if outcome == "edit" else suggested, resolution,
                          reason_code if outcome in {"edit", "escalate"} else None,
                          json.dumps({"challenge_id": challenge_id})))
        if outcome == "edit" and suggested != final_dept:
            complaint = conn.execute("SELECT original_text FROM complaints WHERE id=?",
                                     (challenge["complaint_id"],)).fetchone()
            conn.execute("INSERT INTO corrections (complaint_id,text,wrong_dept,correct_dept,suggested_dept,reason,reason_code,label_source) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (challenge["complaint_id"], complaint["original_text"], suggested, final_dept.strip(),
                          suggested, resolution, reason_code, "citizen_challenge_resolution"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
