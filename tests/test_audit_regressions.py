import pandas as pd
import pytest
import sqlite3

from core.db import execute, fetch_all, insert_complaint
from core.router_ml import fit_default


def test_full_dataframe_fit_uses_training_split_only():
    rows = pd.DataFrame([
        {"text": "road pothole", "owner_label": "Roads Dept", "split": "train"},
        {"text": "blocked drain", "owner_label": "Water Dept", "split": "train"},
        {"text": "held out validation phrase", "owner_label": "Validation Only", "split": "val"},
        {"text": "held out test phrase", "owner_label": "Test Only", "split": "test"},
    ])

    router = fit_default(rows)

    assert set(router.clf.classes_) == {"Roads Dept", "Water Dept"}


def test_duplicate_pair_metrics_are_reported_from_frozen_test_pairs():
    from scripts.evaluate_duplicates import evaluate_duplicate_pairs

    report = evaluate_duplicate_pairs()

    assert report["dataset_pairs"] == 40
    assert report["dev_pairs"] == 20
    assert report["test_pairs"] == 20
    assert report["threshold_source"] == "dev"
    assert report["test"]["precision_denominator"] >= 0
    assert report["test"]["recall_denominator"] == 10
    assert report["test"]["false_positives"] == 0
    assert report["test"]["accuracy_denominator"] == 20
    assert (report["test"]["precision"] is None) == (report["test"]["precision_denominator"] == 0)
    assert report["test"]["recall_denominator"] == 10
    assert 0 <= report["test"]["false_positives"] <= report["test"]["negative_denominator"]


def test_full_evaluation_has_a_configured_threshold_artifact_path():
    from core.config import THRESHOLD_FILE

    assert THRESHOLD_FILE.name == "threshold.json"


def test_full_evaluation_executes_against_the_frozen_test_split():
    from scripts.evaluate_full import evaluate

    report = evaluate("test")

    assert report["split"] == "test"
    assert report["tfidf"]["n_single"] > 0
    assert report["tfidf_threshold"] is None
    assert report["threshold_source"] is None
    assert report["threshold_met_target"] is False
    assert report["assumption_rules"][0] == report["assumption_rules"][1]


def test_ledger_database_triggers_refuse_updates_and_deletes(db):
    complaint_id = insert_complaint({
        "case_id": "AUDIT-LEDGER", "original_text": "Pothole near Ward 2", "language": "english",
        "normalized_text": "pothole near ward 2", "channel": "portal", "location": "Ward 2",
        "issue": "Road damage", "is_synthetic": 1,
    })
    execute("INSERT INTO ledger (complaint_id,event_type,actor,reason) VALUES (?,?,?,?)",
            (complaint_id, "accept", "reviewer", "human confirmed"))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute("UPDATE ledger SET reason=? WHERE complaint_id=?", ("rewritten", complaint_id))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute("DELETE FROM ledger WHERE complaint_id=?", (complaint_id,))

    rows = fetch_all("SELECT event_type,reason FROM ledger WHERE complaint_id=?", (complaint_id,))
    assert rows == [{"event_type": "accept", "reason": "human confirmed"}]


def test_automatic_final_actions_are_rejected_by_service_and_database(db):
    from core.ledger import log_event

    complaint_id = insert_complaint({
        "case_id": "AUDIT-LEDGER-NO-AUTO", "original_text": "Streetlight out", "language": "english",
        "normalized_text": "streetlight out", "channel": "portal", "location": "unknown",
        "issue": "Electricity", "is_synthetic": 1,
    })
    prohibited = ("close", "reject", "deprioritize", "auto_close", "auto_merge")

    for event_type in prohibited:
        with pytest.raises(ValueError, match="prohibited"):
            log_event(complaint_id, event_type, "system")
        with pytest.raises(sqlite3.IntegrityError, match="automatic complaint final action"):
            execute(
                "INSERT INTO ledger (complaint_id,event_type,actor) VALUES (?,?,?)",
                (complaint_id, event_type, "system"),
            )

    assert fetch_all("SELECT * FROM ledger WHERE complaint_id=?", (complaint_id,)) == []


def test_automatic_final_actions_are_rejected_without_mutation(db, staff_user):
    from core.reviews import submit_review
    reviewer = staff_user("reviewer")

    complaint_id = insert_complaint({
        "case_id": "AUDIT-NO-AUTO", "original_text": "Broken streetlight", "language": "english",
        "normalized_text": "broken streetlight", "channel": "portal", "location": "unknown",
        "issue": "Electricity", "is_synthetic": 1,
    })

    for action in ("close", "reject", "deprioritize", "auto_close", "auto_merge"):
        with pytest.raises(ValueError, match="supported human review action"):
            submit_review(complaint_id, "reviewer", action, actor_user=reviewer)

    assert fetch_all("SELECT * FROM ledger WHERE complaint_id=?", (complaint_id,)) == []
    assert fetch_all("SELECT * FROM incident_links") == []
    assert fetch_all("SELECT original_text FROM complaints WHERE id=?", (complaint_id,))[0]["original_text"] == "Broken streetlight"


def test_same_street_different_numbered_asset_is_a_hard_conflict():
    from core.duplicates import compare_pair

    result = compare_pair(
        "Streetlight pole 12 is dead on Sundar Marg.",
        "Streetlight pole 31 is dead on Sundar Marg.",
        "Sundar Marg", "Sundar Marg", "2026-10-05", "2026-10-05", "Electricity", "Electricity",
    )

    assert result["hard_conflict"] is True
    assert "different numbered asset, ward, or lane" in result["conflicts"]


def test_duplicate_candidate_outcomes_are_review_labels_only():
    from core.duplicates import candidate_outcome

    config = {"threshold": 0.6}
    assert candidate_outcome({"score": 0.8, "hard_conflict": False}, config) == "likely same"
    assert candidate_outcome({"score": 0.4, "hard_conflict": False}, config) == "related"
    assert candidate_outcome({"score": 0.9, "hard_conflict": True}, config) == "distinct"
    assert candidate_outcome({"score": 0.1, "hard_conflict": False,
                              "missing_fields": ["location"]}, config) == "insufficient evidence"


def test_intake_strips_articles_and_rejects_generic_road_as_location():
    from core.intake import extract_location

    assert extract_location("The pothole is in the DD Nagar area.") == "DD Nagar"
    assert extract_location("Streetlight is out on the main road.") == "unknown"


def test_intake_extracts_devanagari_ward_and_landmark():
    from core.intake import extract_location

    assert extract_location("वार्ड 12 में पानी की समस्या है।") == "वार्ड 12"
    assert extract_location("सोमनाथ मार्ग के पास नाली जाम है।") == "सोमनाथ मार्ग"


def test_intake_preserves_unicode_and_markup_characters_in_original_text():
    from core.intake import process

    original = "  <script>alert('x')</script> कचरा 😊 O'Neil & \"Main Road\"\r\n"
    rec = process(original, location_hint="Gole Ka Mandir")
    assert rec["original_text"] == original
    assert rec["location"] == "Gole Ka Mandir"
    assert rec["normalized_text"] != original


def test_duplicate_location_match_uses_normalized_field():
    from core.duplicates import compare_pair

    evidence = compare_pair("streetlight is broken", "streetlight is broken",
                            "  Gole   Ka Mandir  ", "gole ka mandir")
    assert evidence["location_match"] is True


def test_intake_issue_extraction_exposes_matched_words():
    from core.intake import process

    result = process("गली में बड़ा गड्ढा है, कृपया मरम्मत करें।")

    assert result["issue"] == "Road damage"
    assert "गड्ढा" in result["issue_evidence"]


def test_requested_action_examples_are_positive_and_missing_action_stays_unspecified():
    from core.intake import extract_requested_action

    assert extract_requested_action("Please repair the broken streetlight.") == "repair"
    assert extract_requested_action("Please clean this garbage pile.") == "clean"
    assert extract_requested_action("Unblock the drain.") == "clear"
    assert extract_requested_action("Please inspect the hanging wire.") == "inspect"
    assert extract_requested_action("There is a broken streetlight.") is None


def test_duplicate_decision_requires_a_structured_reason_code(db, staff_user):
    from core.duplicates import record_decision
    reviewer = staff_user("reviewer")

    first = insert_complaint({
        "case_id": "AUDIT-DUP-A", "original_text": "Pothole on Marg", "language": "english",
        "normalized_text": "pothole on marg", "channel": "portal", "location": "Marg",
        "issue": "Road damage", "is_synthetic": 1,
    })
    second = insert_complaint({
        "case_id": "AUDIT-DUP-B", "original_text": "Pothole on Marg", "language": "english",
        "normalized_text": "pothole on marg", "channel": "portal", "location": "Marg",
        "issue": "Road damage", "is_synthetic": 1,
    })

    with pytest.raises(ValueError, match="reason code"):
        record_decision(first, second, "same_incident", "reviewer", "same pothole", actor_user=reviewer)

    with pytest.raises(ValueError, match="reason code"):
        record_decision(first, second, "same_incident", "reviewer", "same pothole",
                        reason_code="different_incident", actor_user=reviewer)

    record_decision(first, second, "same_incident", "reviewer", "same pothole",
                    reason_code="same_incident", actor_user=reviewer)
    assert fetch_all("SELECT reason_code FROM duplicate_reviews")[0]["reason_code"] == "same_incident"


def test_engine8_harness_does_not_fall_back_to_unvalidated_tfidf_threshold():
    from core.engine8_harness import evaluate_component_3_and_5

    report = evaluate_component_3_and_5("test")

    assert report["threshold_used"] is None
    assert report["threshold_met_target"] is False
    assert report["tfidf"]["answered_count"] == 0


def test_security_status_reports_sqlite_encryption_as_not_configured(monkeypatch):
    from scripts.security_status import security_report

    monkeypatch.delenv("NYAYAFLOW_ATTACHMENT_KEY", raising=False)
    monkeypatch.delenv("NYAYAFLOW_TLS_CERT", raising=False)
    monkeypatch.delenv("NYAYAFLOW_TLS_KEY", raising=False)
    report = security_report()
    assert "NOT CONFIGURED" in report["sqlite_at_rest_encryption"]
    assert "Not configured" in report["photo_attachment_encryption"]
    assert "Unverified" in report["tls"]


def test_abstained_route_has_no_selected_department():
    from core.suggestions import selected_department

    assert selected_department({"top3": [{"dept": "Roads Dept", "score": 0.5}],
                               "abstained": True}) is None


def test_split_proposal_does_not_use_abstained_dept_guesses(monkeypatch):
    from core import router_baseline, splitter

    monkeypatch.setattr(router_baseline, "route", lambda *_args, **_kwargs: {
        "top3": [{"dept": "Roads Dept", "score": 0.5}, {"dept": "Drainage Dept", "score": 0.5}],
        "confidence": 0.5, "abstained": True, "evidence": {},
    })

    proposal = splitter.propose_split("A large pothole is near Ward 4 and a blocked drain is flooding the lane.")

    assert proposal["is_compound"] is False


def test_split_ledger_never_records_abstained_top_guess(db, staff_user):
    from core.splitter import confirm_split
    reviewer = staff_user("reviewer")

    parent_id = insert_complaint({
        "case_id": "AUDIT-SPLIT", "original_text": "Pothole and blocked drain", "language": "english",
        "normalized_text": "pothole and blocked drain", "channel": "portal", "location": "unknown",
        "issue": "unknown", "is_synthetic": 1,
    })
    abstained = {"top3": [{"dept": "Roads Dept", "score": 0.5}], "confidence": 0.5,
                 "abstained": True, "evidence": {}}
    confirm_split(parent_id, "AUDIT-SPLIT", [
        {"text": "A large pothole is blocking traffic", "suggestion": abstained},
        {"text": "A drain is blocked and water is flowing", "suggestion": abstained},
    ], "reviewer", actor_user=reviewer)

    rows = fetch_all("SELECT suggested_dept FROM ledger WHERE complaint_id IN "
                     "(SELECT id FROM complaints WHERE parent_id=?)", (parent_id,))
    assert rows and all(row["suggested_dept"] is None for row in rows)


def test_review_ledger_keeps_abstained_department_unselected(db, staff_user):
    from core.db import insert_suggestion
    from core.reviews import submit_review
    reviewer = staff_user("reviewer")

    complaint_id = insert_complaint({
        "case_id": "AUDIT-ABSTAIN-REVIEW", "original_text": "A vague civic issue", "language": "english",
        "normalized_text": "a vague civic issue", "channel": "portal", "location": "unknown",
        "issue": "unknown", "is_synthetic": 1,
    })
    insert_suggestion(complaint_id, "baseline", [{"dept": "Roads Dept", "score": 0.5}], {}, 0.5, True)

    submit_review(complaint_id, "reviewer", "accept", "Roads Dept", actor_user=reviewer)

    row = fetch_all("SELECT suggested_dept,final_dept FROM ledger WHERE complaint_id=?", (complaint_id,))[0]
    assert row == {"suggested_dept": None, "final_dept": "Roads Dept"}
