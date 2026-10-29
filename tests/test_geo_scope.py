import json
import pytest

from core import auth
from core.db import insert_complaint, insert_public_submission, fetch_all
from core.geo import (area_options, approve_area_request, request_area_assignment,
                      scoped_complaints, staff_area_scope, seed_demo_staff_assignments,
                      CITY_WIDE_AREA_CODE, DEMO_ASSIGNMENT_ACTOR)
from core.attachment import get_attachments
from core.reviews import submit_review
from core.audit import generate_audit_export
from core.geo import partial_geography_names
from core.geo import revoke_area_assignment, sync_allowlisted_assignments


def make_complaint(case_id, *, state="mp", city="mp-gwalior", area="mp-gwalior-morar"):
    return insert_complaint({
        "case_id": case_id, "original_text": f"Road issue near {area}", "language": "english",
        "normalized_text": f"road issue near {area}", "channel": "portal", "location": area,
        "issue": "road", "requested_action": None, "missing_fields": "", "is_synthetic": 1,
        "state_code": state, "city_code": city, "area_code": area,
        "state_name": "Madhya Pradesh", "city_name": "Gwalior", "area_name": area,
    })


def gov_account(monkeypatch, email):
    from core.db import execute
    execute("INSERT OR IGNORE INTO staff_directory(staff_email,full_name,role,department,status,registered,tag) "
            "VALUES(?,?,'reviewer','Grievance Cell','active',0,'SYNTHETIC')", (email, "Staff"))
    flow = auth.begin_staff_registration(email, "Staff", "Secure!River72", "Secure!River72")
    return auth.verify_staff_registration(email, flow["simulated_code"])


def test_geo_options_are_cascading_and_include_requested_gwalior_localities():
    options = area_options()
    assert options["mp"]["name"] == "Madhya Pradesh"
    assert "mp-gwalior" in options["mp"]["cities"]
    areas = options["mp"]["cities"]["mp-gwalior"]["areas"]
    assert {"mp-gwalior-morar", "mp-gwalior-gole-ka-mandir", "mp-gwalior-dd-nagar",
            "mp-gwalior-phool-bagh", "mp-gwalior-maharaj-bada", "mp-gwalior-jayendraganj",
            "mp-gwalior-station-road", "mp-gwalior-jhansi-road", "mp-gwalior-tansen-road",
            "mp-gwalior-sirol-road"}.issubset(areas)


def test_demo_staff_seed_is_opt_in_exact_account_only_and_idempotent(db, monkeypatch):
    from core.geo import DEMO_STAFF_ASSIGNMENTS, demo_staff_seed_enabled

    operator = gov_account(monkeypatch, "operator01@staff.nagriksetu-demo.example")
    assert not demo_staff_seed_enabled()
    assert staff_area_scope(operator["id"]) == []

    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "1")
    assert auth.authenticate_email(operator["email"], "Secure!River72")["id"] == operator["id"]
    assert seed_demo_staff_assignments() == 0
    assert seed_demo_staff_assignments() == 0
    rows = fetch_all("SELECT * FROM government_area_events WHERE user_id=?", (operator["id"],))
    assert len(rows) == 1
    assert (rows[0]["state_code"], rows[0]["city_code"], rows[0]["area_code"]) == (
        "mp", "mp-gwalior", CITY_WIDE_AREA_CODE)
    assert rows[0]["event_type"] == "approved"
    assert rows[0]["actor_email"] == DEMO_ASSIGNMENT_ACTOR
    assert rows[0]["created_at"]
    assert "DEMO MODE" in rows[0]["reason"]
    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "0")
    assert staff_area_scope(operator["id"]) == []
    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "1")
    assert staff_area_scope(operator["id"])[0]["area_name"] == "All areas (city-wide)"
    admin = gov_account(monkeypatch, "reviewer05@staff.nagriksetu-demo.example")
    from core.geo import revoke_area_assignment
    revoke_area_assignment(rows[0]["id"], admin["email"], "Revoke demo scope for regression test")
    assert staff_area_scope(operator["id"]) == []
    assert seed_demo_staff_assignments() == 0  # A startup/login seed never undoes an admin revocation.

    # The configured flag never grants another account, even in demo mode.
    ordinary = gov_account(monkeypatch, "ordinary@staff.example.test")
    assert ordinary["email"] not in DEMO_STAFF_ASSIGNMENTS
    assert staff_area_scope(ordinary["id"]) == []


def test_demo_accounts_see_city_complaints_and_manual_queue_without_role_leakage(db, monkeypatch):
    from core import auth
    from core.geo import known_area_for_location, seed_demo_staff_assignments
    from core.staff_dashboard import list_staff_cases
    from core.challenges import create_challenge, resolve_challenge

    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "1")
    accounts = {}
    for email in ("operator01@staff.nagriksetu-demo.example",
                  "reviewer01@staff.nagriksetu-demo.example",
                  "auditor01@staff.nagriksetu-demo.example"):
        accounts[email.split("@")[0]] = gov_account(monkeypatch, email)
    assert seed_demo_staff_assignments() == 0

    location = "  Gole ka Mandir  "
    area = known_area_for_location("mp", "mp-gwalior", location)
    assert area and area["area_code"] == "mp-gwalior-gole-ka-mandir"
    resident = auth.register_user("demo-resident@example.test", "Demo Resident", "Secure!River72",
                                  password_confirm="Secure!River72")
    gole_id = insert_public_submission({
        "case_id": "CASE-DEMO-CITY-AREA", "original_text": "A pothole needs repair.",
        "language": "english", "normalized_text": "a pothole needs repair", "channel": "portal",
        "location": location, "issue": "Road damage", "is_synthetic": 1,
        "state_code": "mp", "state_name": "Madhya Pradesh", "city_code": "mp-gwalior",
        "city_name": "Gwalior", **area,
    }, {"top3": [{"dept": "Roads Dept", "score": 0.8}], "evidence": {"matched": ["pothole"]},
       "confidence": 0.8, "abstained": False})
    manual_id = insert_public_submission({
        "case_id": "CASE-DEMO-CITY-UNKNOWN", "original_text": "सड़क पर गड्ढा है",
        "language": "hindi", "normalized_text": "सड़क पर गड्ढा है", "channel": "portal",
        "location": "unknown", "issue": "Road damage", "is_synthetic": 1,
        "state_code": "mp", "state_name": "Madhya Pradesh", "city_code": "mp-gwalior",
        "city_name": "Gwalior", "area_code": None, "area_name": None,
        "missing_fields": "location",
    }, {"top3": [], "evidence": {}, "confidence": 0.0, "abstained": True},
        submitted_by=resident["id"])
    missing_location_id = insert_public_submission({
        "case_id": "CASE-DEMO-CITY-NO-LOCATION", "original_text": "Streetlight not working",
        "language": "uncertain", "normalized_text": "streetlight not working", "channel": "portal",
        "location": None, "issue": "Electricity", "is_synthetic": 1,
        "state_code": "mp", "state_name": "Madhya Pradesh", "city_code": "mp-gwalior",
        "city_name": "Gwalior", "area_code": None, "area_name": None,
        "missing_fields": "location",
    }, {"top3": [], "evidence": {}, "confidence": 0.0, "abstained": True})
    hinglish_id = insert_public_submission({
        "case_id": "CASE-DEMO-CITY-HINGLISH", "original_text": "Sadak par pothole hai",
        "language": "hinglish", "normalized_text": "road par pothole hai", "channel": "portal",
        "location": "गोले का मंदिर", "issue": "Road damage", "is_synthetic": 1,
        "state_code": "mp", "state_name": "Madhya Pradesh", "city_code": "mp-gwalior",
        "city_name": "Gwalior", **known_area_for_location("mp", "mp-gwalior", "गोले का मंदिर"),
    }, {"top3": [{"dept": "Roads Dept", "score": 0.8}], "evidence": {"matched": ["pothole"]},
       "confidence": 0.8, "abstained": False})
    unknown_city_id = insert_public_submission({
        "case_id": "CASE-DEMO-NO-CITY", "original_text": "Streetlight is out", "language": "english",
        "normalized_text": "streetlight is out", "channel": "portal", "location": "unknown",
        "issue": "Electricity", "is_synthetic": 1,
    }, {"top3": [], "evidence": {}, "confidence": 0.0, "abstained": True})

    for name, account in accounts.items():
        rows = list_staff_cases(account)
        ids = {row["id"] for row in rows}
        assert gole_id in ids, name
        assert manual_id in ids, name
        assert missing_location_id in ids, name
        assert hinglish_id in ids, name
        assert unknown_city_id not in ids, name  # No facts are invented to widen city access.
        gole = next(row for row in rows if row["id"] == gole_id)
        assert gole["original_text"] == "A pothole needs repair."
        assert gole["location"] == location
        assert gole["language"] == "english" and gole["channel"] == "portal" and gole["created_at"]
        assert gole["suggested_department"] == "Roads Dept" and not gole["uncertain"]
        manual = next(row for row in rows if row["id"] == manual_id)
        assert manual["location"] == "unknown" and manual["uncertain"]
        assert manual["language"] == "hindi" and manual["suggestion"]["abstained"] == 1
        assert next(row for row in rows if row["id"] == missing_location_id)["location"] is None
        assert next(row for row in rows if row["id"] == hinglish_id)["language"] == "hinglish"

    operator = accounts["operator01"]
    reviewer = accounts["reviewer01"]
    auditor = accounts["auditor01"]
    challenge_id = create_challenge(manual_id, "citizen", "Please review this routing",
                                    actor_email=resident["email"], citizen_user_id=resident["id"])
    with pytest.raises(PermissionError, match="Only an authorized reviewer"):
        resolve_challenge(challenge_id, "operator", "reviewed", "accept", actor_user=operator)
    with pytest.raises(PermissionError, match="Only an authorized reviewer"):
        resolve_challenge(challenge_id, "auditor", "reviewed", "accept", actor_user=auditor)
    resolve_challenge(challenge_id, "reviewer", "Verified after review", "accept",
                      actor_email=reviewer["email"], actor_user=reviewer)

    from core.staff_dashboard import perform_staff_action
    with pytest.raises(PermissionError, match="read-only"):
        perform_staff_action(auditor, gole_id, "resolve", note="Should be denied")
    with pytest.raises(PermissionError, match="authenticated government staff"):
        scoped_complaints(None)


def test_demo_seed_stays_off_without_demo_mode_and_new_staff_keeps_area_gate(db, monkeypatch):
    account = gov_account(monkeypatch, "operator01@staff.nagriksetu-demo.example")
    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "1")
    monkeypatch.setenv("NAGRIKSETU_DEMO_MODE", "0")
    monkeypatch.setenv("NAGRIKSETU_AUTH_SECRET", "test-secret")
    assert seed_demo_staff_assignments() == 0
    assert staff_area_scope(account["id"]) == []
    from core.geo import staff_location_snapshot
    assert staff_location_snapshot(account)["assigned"] == []

    monkeypatch.setenv("NAGRIKSETU_DEMO_MODE", "1")
    monkeypatch.setenv("NYAYAFLOW_SEED_DEMO_STAFF", "0")
    ordinary = gov_account(monkeypatch, "newstaff@staff.example.test")
    assert staff_location_snapshot(ordinary)["assigned"] == []
    assert scoped_complaints(ordinary) == []


def test_partial_public_location_stays_partial_instead_of_being_invented():
    assert partial_geography_names(None) == {
        "state_code": None, "state_name": None, "city_code": None, "city_name": None,
        "area_code": None, "area_name": None,
    }
    partial = partial_geography_names("mp", "mp-gwalior", None)
    assert partial["state_name"] == "Madhya Pradesh"
    assert partial["city_name"] == "Gwalior"
    assert partial["area_code"] is None
    with pytest.raises(ValueError, match="within the selected state"):
        partial_geography_names("mp", "up-lucknow", None)


def test_staff_location_request_is_pending_and_has_no_complaint_access(db, monkeypatch):
    staff = gov_account(monkeypatch, "staff@example.test")
    cid = make_complaint("CASE-GEO-PENDING")
    request_area_assignment(staff["id"], "mp", "mp-gwalior", "mp-gwalior-morar", staff["email"])

    assert staff_area_scope(staff["id"]) == []
    assert scoped_complaints(staff) == []
    with pytest.raises(PermissionError, match="assigned area"):
        from core.geo import require_complaint_area_access
        require_complaint_area_access(staff, cid)


def test_verified_staff_only_sees_and_can_act_on_assigned_area(db, monkeypatch):
    staff = gov_account(monkeypatch, "staff@example.test")
    request_id = request_area_assignment(staff["id"], "mp", "mp-gwalior", "mp-gwalior-morar", staff["email"])
    monkeypatch.setenv("NYAYAFLOW_GEO_ADMIN_EMAILS", "admin@example.test")
    admin = gov_account(monkeypatch, "admin@example.test")
    approve_area_request(request_id, admin["email"], "Verified demo assignment")
    morer = make_complaint("CASE-GEO-MORAR")
    gole = make_complaint("CASE-GEO-GOLE", area="mp-gwalior-gole-ka-mandir")

    assert [row["case_id"] for row in scoped_complaints(staff)] == ["CASE-GEO-MORAR"]
    from core.geo import require_complaint_area_access
    require_complaint_area_access(staff, morer)
    submit_review(morer, "reviewer", "accept", "Roads Dept", actor_user=staff)
    with pytest.raises(PermissionError, match="outside your assigned area"):
        require_complaint_area_access(staff, gole)
    with pytest.raises(PermissionError, match="outside your assigned area"):
        submit_review(gole, "reviewer", "accept", "Roads Dept", actor_user=staff)
    with pytest.raises(PermissionError, match="outside your assigned area"):
        get_attachments(gole, "reviewer", actor_user=staff)
    export = generate_audit_export("reviewer", actor_user=staff)
    assert json.loads(export)["total_events"] == 1


def test_staff_cannot_self_approve_or_change_another_users_scope(db, monkeypatch):
    staff = gov_account(monkeypatch, "staff@example.test")
    request_id = request_area_assignment(staff["id"], "mp", "mp-gwalior", "mp-gwalior-morar", staff["email"])
    with pytest.raises(PermissionError, match="geography administrator"):
        approve_area_request(request_id, staff["email"], "self approve")


def test_location_assignment_history_is_append_only(db, monkeypatch):
    staff = gov_account(monkeypatch, "staff@example.test")
    request_area_assignment(staff["id"], "mp", "mp-gwalior", "mp-gwalior-morar", staff["email"])
    rows = fetch_all("SELECT id FROM government_area_events")
    assert rows
    with pytest.raises(Exception, match="append-only"):
        from core.db import execute
        execute("DELETE FROM government_area_events WHERE id=?", (rows[0]["id"],))


def test_staff_area_scope_cannot_be_forged_or_used_after_deactivation(db, monkeypatch):
    staff = gov_account(monkeypatch, "staff@example.test")
    request_id = request_area_assignment(staff["id"], "mp", "mp-gwalior", "mp-gwalior-morar", staff["email"])
    monkeypatch.setenv("NYAYAFLOW_GEO_ADMIN_EMAILS", "admin@example.test")
    admin = gov_account(monkeypatch, "admin@example.test")
    approve_area_request(request_id, admin["email"], "Verified demo assignment")
    make_complaint("CASE-GEO-FORGED")
    forged = {**staff, "email": "someone-else@example.test"}
    with pytest.raises(PermissionError, match="session is no longer valid"):
        scoped_complaints(forged)
    from core.db import execute
    execute("UPDATE users SET active=0 WHERE id=?", (staff["id"],))
    with pytest.raises(PermissionError, match="session is no longer valid"):
        scoped_complaints(staff)


def test_area_revocation_is_append_only_and_not_reopened_by_allowlist_sync(db, monkeypatch, tmp_path):
    staff = gov_account(monkeypatch, "staff@example.test")
    from core import geo
    allowlist = tmp_path / "gov_allowlist.csv"
    allowlist.write_text("email,state_code,city_code,area_codes\nstaff@example.test,mp,mp-gwalior,mp-gwalior-morar\n",
                         encoding="utf-8")
    monkeypatch.setattr(geo, "GOV_ALLOWLIST_PATH", allowlist)
    assert sync_allowlisted_assignments(staff["id"], staff["email"]) == 1
    assert staff_area_scope(staff["id"])
    grant = fetch_all("SELECT id FROM government_area_events WHERE user_id=? AND event_type='approved'",
                      (staff["id"],))[0]
    monkeypatch.setenv("NYAYAFLOW_GEO_ADMIN_EMAILS", "admin@example.test")
    admin = gov_account(monkeypatch, "admin@example.test")
    revoke_area_assignment(grant["id"], admin["email"], "Staff changed assignment")
    assert staff_area_scope(staff["id"]) == []
    assert sync_allowlisted_assignments(staff["id"], staff["email"]) == 0
    assert fetch_all("SELECT event_type FROM government_area_events ORDER BY id")[-1]["event_type"] == "revoked"
