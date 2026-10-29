"""Duplicate/incident candidate support. Similarity is a review signal, never a verdict."""
import re
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

from .auth import enforce_rbac
from .geo import authorize_staff_complaint, scoped_complaint_ids
from .geo import STAFF_ROLES
from .db import fetch_all, get_conn
from .intake import normalize_location

_TOKEN = re.compile(r"[\w\u0900-\u097f]+", re.UNICODE)
_STOP = {"the", "and", "for", "near", "this", "that", "with", "from", "road", "at", "on",
         "has", "have", "been", "is", "are", "was", "were", "mein", "me", "hai", "hain",
         "pe", "par", "ki", "ka", "ke", "और", "है", "हैं", "में", "पर", "की", "का", "के"}
DECISIONS = {"same_incident", "related", "different", "needs_info", "unlink"}
DECISION_REASON_CODES = {
    "same_incident": "same_incident",
    "related": "related_not_duplicate",
    "different": "different_incident",
    "needs_info": "insufficient_information",
    "unlink": "reopen_after_review",
}
CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "duplicate_threshold.json"
DEFAULT_CONFIG = {
    "threshold": 0.55,
    "time_window_days": 7,
    "weights": {"text": 0.65, "location": 0.2, "time": 0.15},
}


def _tokens(text):
    return {word for word in _TOKEN.findall((text or "").casefold()) if len(word) > 2 and word not in _STOP}


def _date(value):
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def load_duplicate_config():
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    weights = config.get("weights", {})
    if set(weights) != {"text", "location", "time"} or any(float(value) < 0 for value in weights.values()):
        raise ValueError("Duplicate score config must contain non-negative text/location/time weights.")
    if abs(sum(float(value) for value in weights.values()) - 1) > 1e-6:
        raise ValueError("Duplicate score weights must sum to 1.")
    if not 0 <= float(config.get("threshold", -1)) <= 1:
        raise ValueError("Duplicate match threshold must be between 0 and 1.")
    return config


def _asset_markers(text):
    markers = {}
    pattern = re.compile(r"\b(pole|lane|gali|ward|asset)\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I)
    for kind, number in pattern.findall(text or ""):
        markers.setdefault(kind.casefold(), set()).add(number)
    return markers


def compare_pair(text_a, text_b, location_a="unknown", location_b="unknown",
                 created_a=None, created_b=None, issue_a="unknown", issue_b="unknown",
                 time_window_days=None):
    """Return transparent candidate signals. The result is never a verdict."""
    config = load_duplicate_config()
    window = config.get("time_window_days", 7) if time_window_days is None else time_window_days
    if window < 0:
        raise ValueError("The candidate time window cannot be negative.")
    words_a, words_b = _tokens(text_a), _tokens(text_b)
    union = words_a | words_b
    shared = sorted(words_a & words_b)
    text_score = len(shared) / len(union) if union else 0.0
    loc_a = normalize_location(location_a) or "unknown"
    loc_b = normalize_location(location_b) or "unknown"
    location_known = loc_a not in {"", "unknown"} and loc_b not in {"", "unknown"}
    location_match = location_known and loc_a == loc_b
    date_a, date_b = _date(created_a), _date(created_b)
    days = abs((date_a - date_b).total_seconds()) / 86400 if date_a and date_b else None
    time_match = days is not None and days <= window
    weights = config["weights"]
    score = (float(weights["text"]) * text_score
             + (float(weights["location"]) if location_match else 0.0)
             + (float(weights["time"]) if time_match else 0.0))
    conflicts = []
    markers_a, markers_b = _asset_markers(text_a), _asset_markers(text_b)
    different_asset = any(markers_a[key].isdisjoint(markers_b[key])
                          for key in markers_a.keys() & markers_b.keys())
    if different_asset:
        conflicts.append("different numbered asset, ward, or lane")
        score *= 0.15
    if location_known and not location_match:
        conflicts.append("different location")
        score *= 0.7
    if issue_a and issue_b and issue_a.casefold() not in {"unknown", ""} \
            and issue_b.casefold() not in {"unknown", ""} and issue_a.casefold() != issue_b.casefold():
        conflicts.append("different extracted issue")
        score *= 0.35
    if days is not None and days > window:
        conflicts.append("outside configured time window")
        score *= 0.35
    missing = []
    if not location_known:
        missing.append("location")
    if days is None:
        missing.append("time")
    return {
        "score": round(score, 4), "text_score": round(text_score, 4),
        "location_match": bool(location_match),
        "time_difference_days": round(days, 2) if days is not None else None,
        "time_match": bool(time_match), "shared_terms": shared[:12],
        "conflicts": conflicts, "missing_fields": missing,
        "score_kind": "candidate_score_not_probability",
        "hard_conflict": bool(different_asset or "different extracted issue" in conflicts),
    }


def candidate_outcome(evidence, config=None):
    """Describe a review candidate; this label never links or suppresses a case."""
    config = config or load_duplicate_config()
    threshold = float(config["threshold"])
    score = float(evidence.get("score", 0.0))
    if score >= threshold and not evidence.get("hard_conflict"):
        return "likely same"
    if evidence.get("hard_conflict"):
        return "distinct"
    if score >= threshold * 0.55:
        return "related"
    if evidence.get("missing_fields"):
        return "insufficient evidence"
    return "distinct"


def _latest_decision(a, b):
    rows = fetch_all(
        "SELECT decision FROM duplicate_reviews WHERE "
        "(complaint_id=? AND candidate_complaint_id=?) OR "
        "(complaint_id=? AND candidate_complaint_id=?) ORDER BY id DESC LIMIT 1",
        (a, b, b, a))
    return rows[0]["decision"] if rows else "needs_review"


def _latest_link(a, b):
    rows = fetch_all("SELECT incident_id,active FROM incident_links WHERE "
                     "(complaint_id=? AND candidate_complaint_id=?) OR "
                     "(complaint_id=? AND candidate_complaint_id=?) ORDER BY id DESC LIMIT 1",
                     (a, b, b, a))
    return rows[0] if rows else {"incident_id": None, "active": 0}


def find_candidates(complaint_id: int, limit: int = 10, time_window_days: int | None = None,
                    actor_user: dict | None = None):
    config = load_duplicate_config()
    window = config.get("time_window_days", 7) if time_window_days is None else time_window_days
    if window < 0:
        raise ValueError("The candidate time window cannot be negative.")
    permitted = None
    if actor_user and actor_user.get("role") in STAFF_ROLES:
        authorize_staff_complaint(actor_user["role"], complaint_id, actor_user)
        permitted = set(scoped_complaint_ids(actor_user, include_unassigned=True))
        if int(complaint_id) not in permitted:
            raise PermissionError("This complaint is outside your department or verified service area.")
    source_rows = fetch_all("SELECT * FROM complaints WHERE id=? AND is_active=1", (complaint_id,))
    if not source_rows:
        raise ValueError("Complaint not found.")
    source = source_rows[0]
    source_words = _tokens(source.get("normalized_text") or source["original_text"])
    source_location = source.get("location_normalized") or normalize_location(source.get("location")) or "unknown"
    source_date = _date(source.get("created_at"))
    if permitted is None:
        rows = fetch_all("SELECT * FROM complaints WHERE id<>? AND is_active=1 ORDER BY id DESC", (complaint_id,))
    else:
        other_ids = sorted(permitted - {int(complaint_id)})
        if not other_ids:
            rows = []
        else:
            marks = ",".join("?" for _ in other_ids)
            rows = fetch_all(f"SELECT * FROM complaints WHERE id<>? AND is_active=1 AND id IN ({marks}) "
                             "ORDER BY id DESC", [complaint_id, *other_ids])
    candidates = []
    for row in rows:
        words = _tokens(row.get("normalized_text") or row["original_text"])
        evidence = compare_pair(
            source.get("normalized_text") or source["original_text"],
            row.get("normalized_text") or row["original_text"],
            source_location,
            row.get("location_normalized") or normalize_location(row.get("location")) or "unknown",
            source.get("created_at"), row.get("created_at"),
            source.get("issue") or "unknown", row.get("issue") or "unknown", window)
        text_score = evidence["text_score"]
        # Suppress unrelated rows. Missing fields are shown if text itself is a candidate.
        if text_score == 0 and not (evidence["location_match"] and source.get("issue") == row.get("issue")):
            continue
        link = _latest_link(complaint_id, row["id"])
        candidates.append({
            "complaint_id": row["id"], "case_id": row["case_id"],
            "original_text": row["original_text"], "location": row.get("location") or "unknown",
            "created_at": row.get("created_at"), "text_score": round(text_score, 4),
            **evidence,
            "candidate_outcome": candidate_outcome(evidence, config),
            "decision": _latest_decision(complaint_id, row["id"]),
            "active_link": bool(link["active"]), "incident_id": link["incident_id"] if link["active"] else None,
        })
    candidates.sort(key=lambda item: (-item["score"], item["complaint_id"]))
    return candidates[:max(0, min(int(limit), 100))]


def record_decision(complaint_id: int, candidate_id: int, decision: str, actor_role: str,
                    reason: str, actor_email: str | None = None, reason_code: str | None = None,
                    actor_user: dict | None = None):
    enforce_rbac(actor_role, "can_review")
    authorize_staff_complaint(actor_role, complaint_id, actor_user)
    authorize_staff_complaint(actor_role, candidate_id, actor_user)
    if decision not in DECISIONS:
        raise ValueError(f"Decision must be one of: {', '.join(sorted(DECISIONS))}.")
    if complaint_id == candidate_id:
        raise ValueError("A complaint cannot be linked to itself.")
    if not (reason or "").strip():
        raise ValueError("A reason is required for every duplicate decision.")
    expected_reason_code = DECISION_REASON_CODES[decision]
    if reason_code != expected_reason_code:
        raise ValueError(f"Decision '{decision}' requires reason code '{expected_reason_code}'.")
    ids = sorted((int(complaint_id), int(candidate_id)))
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id FROM complaints WHERE id IN (?,?)", ids).fetchall()
        if len(rows) != 2:
            raise ValueError("Both complaints must exist.")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO duplicate_reviews (complaint_id,candidate_complaint_id,decision,actor,reason,reason_code) "
            "VALUES (?,?,?,?,?,?)", (ids[0], ids[1], decision, actor_email or actor_role,
                                      reason.strip(), reason_code))
        if decision in {"same_incident", "unlink"}:
            latest_link = conn.execute(
                "SELECT incident_id,active FROM incident_links WHERE complaint_id=? AND candidate_complaint_id=? "
                "ORDER BY id DESC LIMIT 1", ids).fetchone()
            if decision == "same_incident":
                if latest_link and latest_link["active"]:
                    incident_id = latest_link["incident_id"]
                else:
                    member = conn.execute(
                        "SELECT incident_id FROM incident_links WHERE active=1 AND "
                        "(complaint_id IN (?,?) OR candidate_complaint_id IN (?,?)) ORDER BY id LIMIT 1",
                        (*ids, *ids)).fetchone()
                    incident_id = member["incident_id"] if member else f"INC-{uuid.uuid4().hex[:12].upper()}"
                conn.execute("INSERT INTO incident_links (complaint_id,candidate_complaint_id,incident_id,active) VALUES (?,?,?,1)",
                             (*ids, incident_id))
                event = "duplicate_linked"
            else:
                if not latest_link or not latest_link["active"]:
                    raise ValueError("These complaints do not have an active incident link.")
                conn.execute("INSERT INTO incident_links (complaint_id,candidate_complaint_id,incident_id,active) VALUES (?,?,?,0)",
                             (*ids, latest_link["incident_id"]))
                event = "duplicate_unlinked"
            import json
            details = json.dumps({"candidate_id": ids[1], "decision": decision})
            for cid in ids:
                conn.execute("INSERT INTO ledger (complaint_id,event_type,actor,reason,details) VALUES (?,?,?,?,?)",
                             (cid, event, actor_email or actor_role, reason.strip(), details))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
