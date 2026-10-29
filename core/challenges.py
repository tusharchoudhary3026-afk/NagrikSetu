"""Citizen/staff review requests with transactional, append-only resolution events."""
from .auth import enforce_rbac
from .db import get_conn
from .geo import authorize_staff_complaint
from .auth import enforce_rbac


def create_challenge(complaint_id: int, raised_by: str, reason: str, actor_email: str | None = None,
                     actor_user: dict | None = None, citizen_user_id: int | None = None) -> int:
    if raised_by not in {"citizen", "staff"} or not (reason or "").strip():
        raise ValueError("A valid requester and a reason are required.")
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
        cur = conn.execute("INSERT INTO challenges (complaint_id,raised_by,reason) VALUES (?,?,?)",
                           (complaint_id, raised_by, reason.strip()))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,reason) VALUES (?,?,?,?)",
                     (complaint_id, "challenge", actor_email or raised_by, reason.strip()))
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_challenge(challenge_id: int, actor_role: str, resolution: str, outcome: str,
                      final_dept: str | None = None, reason_code: str | None = None,
                      actor_email: str | None = None, actor_user: dict | None = None) -> None:
    enforce_rbac(actor_role, "can_review")
    resolution = (resolution or "").strip()
    if not resolution:
        raise ValueError("A resolution reason is required.")
    if outcome not in {"accept", "edit", "escalate"}:
        raise ValueError("Choose accept, edit, or escalate.")
    if outcome == "edit" and not (final_dept or "").strip():
        raise ValueError("A final department is required when changing the route.")
    if outcome in {"edit", "escalate"} and reason_code not in {
        "wrong_category", "missing_info", "overlapping_ownership", "duplicate_report", "other"
    }:
        raise ValueError("Choose a valid reason code for this decision.")

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        challenge = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if not challenge:
            raise ValueError("Review request not found.")
        if challenge["status"] != "open":
            raise ValueError("This review request has already been resolved.")
        authorize_staff_complaint(actor_role, challenge["complaint_id"], actor_user)
        suggestion = conn.execute(
            "SELECT top3,abstained FROM suggestions WHERE complaint_id=? ORDER BY id DESC LIMIT 1",
            (challenge["complaint_id"],)).fetchone()
        import json
        top3 = json.loads(suggestion["top3"]) if suggestion else []
        from .suggestions import selected_department
        suggested = selected_department({"top3": top3, "abstained": bool(suggestion and suggestion["abstained"])}) if suggestion else None
        conn.execute("UPDATE challenges SET status='resolved',resolved_by=?,resolution=?,outcome=?,"
                     "resolved_at=datetime('now') WHERE id=? AND status='open'",
                     (actor_email or actor_role, resolution, outcome, challenge_id))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,suggested_dept,final_dept,reason,reason_code,details) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (challenge["complaint_id"], "challenge_resolved", actor_email or actor_role, suggested,
                      final_dept if outcome == "edit" else suggested, resolution, reason_code,
                      json.dumps({"challenge_id": challenge_id, "outcome": outcome})))
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
