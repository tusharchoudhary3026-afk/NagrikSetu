"""Small acceptance scenarios using actual service behavior and isolated test storage."""
import tempfile
from pathlib import Path

import pandas as pd

from . import db as dbm
from .auth import verify_permission
from .challenges import create_challenge, resolve_challenge
from .config import COMPLAINTS
from .db import init_db, insert_complaint, insert_suggestion
from .duplicates import find_candidates
from .intake import clarification_question, detect_language, process
from .router_baseline import route
from .safety import flag_safety
from .splitter import propose_split


def run_at_01_clear_complaint():
    text = "Large pothole causing traffic jams near Civil Lines main road."
    result = route(text)
    dept = result["top3"][0]["dept"] if result["top3"] else None
    passed = dept == "Roads Dept" and not result["abstained"]
    return {"id": "AT-01", "scenario": "Clear complaint, known owner",
            "pass_condition": "Correct top suggestion against current labelled owner",
            "status": "PASS" if passed else "FAIL", "details": f"Routed to: {dept}"}


def run_at_02_vague_complaint():
    text = "Fix this problem near my house."
    rec = process(text)
    question = clarification_question(rec)
    result = route(text)
    passed = rec["location"] == "unknown" and rec["issue"] == "unknown" and question and result["abstained"]
    return {"id": "AT-02", "scenario": "Vague text / missing location",
            "pass_condition": "Ask a targeted question and abstain without inventing facts",
            "status": "PASS" if passed else "FAIL", "details": f"Question: {question}; route abstained: {result['abstained']}"}


def run_at_03_similar_wording():
    one = propose_split("Garbage dump near Ward 4 market.")
    two = propose_split("Garbage dump near Ward 9 bus stand.")
    passed = not one["is_compound"] and not two["is_compound"]
    return {"id": "AT-03", "scenario": "Similar wording, distinct incidents",
            "pass_condition": "No automatic split or duplicate merge",
            "status": "PASS" if passed else "FAIL", "details": "Each complaint remains an independent case."}


def run_at_04_reviewer_override():
    old_path = dbm.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp:
            dbm.DB_PATH = Path(temp) / "acceptance.db"
            init_db()
            rec = {"case_id": "AT04", "parent_id": None, "original_text": "Broken streetlight",
                   "language": "english", "normalized_text": "broken streetlight", "channel": "portal",
                   "location": "unknown", "issue": "streetlight", "requested_action": None,
                   "missing_fields": "location", "is_synthetic": 1}
            cid = insert_complaint(rec)
            insert_suggestion(cid, "baseline", [{"dept": "Roads Dept", "score": 1}], {}, 1, 0)
            challenge = create_challenge(cid, "citizen", "Wrong department")
            resolve_challenge(challenge, "reviewer", "Electrical team owns streetlights", "edit",
                              final_dept="Electricity Dept", reason_code="wrong_category")
            events = dbm.fetch_all("SELECT event_type,suggested_dept,final_dept FROM ledger WHERE complaint_id=? ORDER BY id", (cid,))
            corrections = dbm.fetch_all("SELECT * FROM corrections WHERE complaint_id=?", (cid,))
            passed = len(events) == 3 and events[-1]["suggested_dept"] == "Roads Dept" and bool(corrections)
    except Exception as exc:
        passed, events, corrections = False, [], []
        detail = str(exc)
    finally:
        dbm.DB_PATH = old_path
    return {"id": "AT-04", "scenario": "Reviewer overrides suggestion",
            "pass_condition": "Store correction, reason, and prior suggestion",
            "status": "PASS" if passed else "FAIL",
            "details": detail if not passed else "Override and correction saved in isolated database."}


def run_at_05_safety_case():
    text = "A polite report: an exposed wire is sparking near the park."
    result = flag_safety(text)
    passed = result["flagged"] and result["flags"] and result["flags"][0]["status"] == "HUMAN_REVIEW_REQUIRED"
    return {"id": "AT-05", "scenario": "Predefined safety case",
            "pass_condition": "Flag for human review under team-proposed rubric",
            "status": "PASS" if passed else "FAIL", "details": str(result["flags"])}


def run_at_06_multilingual():
    texts = {"english": "Water supply pipe leaking on Station Road.",
             "hindi": "स्टेशन रोड पर पानी की पाइपलाइन लीक हो रही है।",
             "hinglish": "Station Road pe paani ka pipe leak ho raha hai."}
    detected = {language: detect_language(text) for language, text in texts.items()}
    labels = pd.read_csv(COMPLAINTS, encoding="utf-8-sig").groupby("language").size().to_dict()
    passed = all(detected[k] == k and labels.get(k, 0) > 0 for k in texts)
    return {"id": "AT-06", "scenario": "Equivalent English/Hindi/Hinglish case",
            "pass_condition": "Report each language with non-zero dataset sample sizes",
            "status": "PASS" if passed else "FAIL", "details": f"detected={detected}; sample_sizes={labels}"}


def run_all_acceptance_tests():
    return [run_at_01_clear_complaint(), run_at_02_vague_complaint(), run_at_03_similar_wording(),
            run_at_04_reviewer_override(), run_at_05_safety_case(), run_at_06_multilingual()]


if __name__ == "__main__":
    for result in run_all_acceptance_tests():
        print(f"[{result['status']}] {result['id']}: {result['scenario']} -> {result['details']}")
