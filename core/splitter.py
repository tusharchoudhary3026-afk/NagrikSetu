"""Engine 2: compound complaint splitter. Proposes only. A human confirms or merges back."""
import re
import json
from . import router_baseline
from .db import get_conn
from .auth import enforce_rbac
from .intake import process
from .suggestions import selected_department
from .geo import authorize_staff_complaint

CONNECTORS = r"\band\b|\baur\b|(?<!\S)और(?!\S)|\bplus\b|;|\.\s+(?=[A-Z\u0900-\u097F])"


def propose_split(text: str):
    parts = [p.strip() for p in re.split(CONNECTORS, text, flags=re.I) if p and len(p.strip()) > 8]
    if len(parts) < 2:
        return {"is_compound": False, "parts": [], "note": "single issue"}
    kw = router_baseline.load_keywords()
    routed = [(p, router_baseline.route(p, kw)) for p in parts]
    depts = {department for _, r in routed if (department := selected_department(r))}
    # Parts that map to one department, or have no signal, are NOT split.
    if len(depts) < 2:
        return {"is_compound": False, "parts": [],
                "note": "possible multi-clause text but one owner or unclear; kept intact"}
    return {"is_compound": True,
            "parts": [{"text": p, "suggestion": r} for p, r in routed],
            "note": "proposed split; needs human confirmation"}


def confirm_split(parent_id: int, case_id: str, parts: list[dict], actor_role: str,
                  actor_email: str | None = None, actor_user: dict | None = None) -> list[int]:
    """Persist human-confirmed child issues, keeping the original parent intact."""
    enforce_rbac(actor_role, "can_review")
    if len(parts) < 2 or any(not str(part.get("text", "")).strip() for part in parts):
        raise ValueError("A confirmed split needs at least two non-empty issues.")
    conn = get_conn()
    try:
        parent = conn.execute("SELECT * FROM complaints WHERE id=?", (parent_id,)).fetchone()
        if not parent:
            raise ValueError("Parent complaint not found.")
        authorize_staff_complaint(actor_role, parent_id, actor_user)
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute("SELECT id FROM complaints WHERE parent_id=? AND is_active=1", (parent_id,)).fetchall()
        if active:
            raise ValueError("This complaint already has an active split.")
        ids = []
        for part in parts:
            text = str(part["text"]).strip()
            rec = process(text, channel=parent["channel"])
            rec["case_id"], rec["parent_id"], rec["is_synthetic"] = case_id, parent_id, parent["is_synthetic"]
            cur = conn.execute(
                "INSERT INTO complaints (case_id,parent_id,original_text,language,normalized_text,channel,location,issue,requested_action,missing_fields,is_synthetic,state_code,state_name,city_code,city_name,area_code,area_name) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["case_id"], rec["parent_id"], rec["original_text"], rec["language"],
                 rec["normalized_text"], rec["channel"], rec["location"], rec["issue"],
                 rec["requested_action"], rec["missing_fields"], rec["is_synthetic"], parent["state_code"],
                 parent["state_name"], parent["city_code"], parent["city_name"], parent["area_code"], parent["area_name"]))
            child_id = cur.lastrowid
            ids.append(child_id)
            result = part.get("suggestion") or router_baseline.route(text)
            conn.execute("INSERT INTO suggestions (complaint_id,method,top3,evidence,confidence,abstained) VALUES (?,?,?,?,?,?)",
                         (child_id, "baseline", json.dumps(result.get("top3", [])),
                          json.dumps(result.get("evidence", {})), result.get("confidence", 0.0),
                          int(bool(result.get("abstained", True)))))
            conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,suggested_dept,details) VALUES (?,?,?,?,?)",
                         (child_id, "suggested", "system", selected_department(result),
                          json.dumps({"split_parent_id": parent_id, "abstained": bool(result.get("abstained", True)),
                                      "extracted_issue_evidence": rec.get("issue_evidence", [])})))
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,details) VALUES (?,?,?,?)",
                     (parent_id, "split_confirmed", actor_email or actor_role, json.dumps({"child_ids": ids})))
        conn.commit()
        return ids
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def merge_back(parent_id: int, actor_role: str, actor_email: str | None = None,
               actor_user: dict | None = None) -> int:
    """Deactivate current child views but preserve all child records and ledger history."""
    enforce_rbac(actor_role, "can_review")
    authorize_staff_complaint(actor_role, parent_id, actor_user)
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        children = conn.execute("SELECT id FROM complaints WHERE parent_id=? AND is_active=1 ORDER BY id",
                                (parent_id,)).fetchall()
        if not children:
            raise ValueError("No active split to merge back.")
        conn.executemany("UPDATE complaints SET is_active=0 WHERE id=?", [(row["id"],) for row in children])
        ids = [row["id"] for row in children]
        conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,details) VALUES (?,?,?,?)",
                     (parent_id, "split_merged_back", actor_email or actor_role, json.dumps({"child_ids": ids})))
        conn.commit()
        return len(ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
