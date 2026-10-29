import json
import pytest

from core import auth
from core.db import insert_complaint, fetch_all
from core.geo import (area_options, approve_area_request, request_area_assignment,
                      scoped_complaints, staff_area_scope)
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
    assert {"mp-gwalior-morar", "mp-gwalior-gole-ka-mandir"}.issubset(areas)


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
