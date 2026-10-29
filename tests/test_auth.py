import re
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from core import auth
from core.db import execute, fetch_all


PASSWORD = "Secure!River72"


def _public(email="resident@public.example", phone=None, password=PASSWORD):
    if phone:
        flow = auth.begin_public_phone_registration(phone, "Resident Citizen", password, password)
        return auth.verify_public_phone_registration(phone, flow["simulated_code"])
    return auth.register_user(email, "Resident Citizen", password, password_confirm=password,
                              phone=phone)


def test_staff_directory_is_synthetic_and_normalized(db):
    rows = fetch_all("SELECT * FROM staff_directory")
    assert 20 <= len(rows) <= 30
    assert all(row["staff_email"].endswith("@staff.nagriksetu-demo.example") for row in rows)
    assert all(row["tag"] == "SYNTHETIC" for row in rows)
    assert all(row["staff_email"] == row["staff_email"].strip().lower() for row in rows)
    common = [line for line in (Path(__file__).resolve().parent.parent / "data" / "common_passwords.txt")
              .read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    assert len(common) == 200 and len({word.casefold() for word in common}) == 200


def test_staff_directory_seed_is_idempotent_and_preserves_registration(db):
    email = fetch_all("SELECT staff_email FROM staff_directory LIMIT 1")[0]["staff_email"]
    execute("UPDATE staff_directory SET registered=1 WHERE staff_email=?", (email,))
    db.init_db()
    assert fetch_all("SELECT registered FROM staff_directory WHERE staff_email=?", (email,))[0]["registered"] == 1


def test_staff_email_code_registration_assigns_directory_role_and_department(db):
    email = "operator01@staff.nagriksetu-demo.example"
    flow = auth.begin_staff_registration(email.upper(), "Directory Operator", PASSWORD, PASSWORD)
    account = auth.verify_staff_registration(email, flow["simulated_code"])
    record = fetch_all("SELECT role,department,phone FROM users WHERE id=?", (account["id"],))[0]
    assert record == {"role": "operator", "department": "Roads Dept", "phone": None}
    assert fetch_all("SELECT registered FROM staff_directory WHERE staff_email=?", (email,))[0]["registered"] == 1


@pytest.mark.parametrize("email,reason", [
    ("nobody@staff.nagriksetu-demo.example", "not allowlisted"),
    ("disabled01@staff.nagriksetu-demo.example", "disabled"),
    ("registered01@staff.nagriksetu-demo.example", "already registered"),
])
def test_staff_registration_rejects_unknown_disabled_or_registered_email(db, email, reason):
    if reason == "already registered":
        execute("UPDATE staff_directory SET registered=1 WHERE staff_email=?", (email,))
    with pytest.raises(ValueError):
        auth.begin_staff_registration(email, "Someone", PASSWORD, PASSWORD)


def test_staff_email_code_expires_and_is_single_use(db, monkeypatch):
    flow = auth.begin_staff_registration("reviewer01@staff.nagriksetu-demo.example", "Reviewer", PASSWORD, PASSWORD)
    execute("UPDATE verification_challenges SET expires_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), flow["challenge_id"]))
    with pytest.raises(ValueError, match="expired"):
        auth.verify_staff_registration("reviewer01@staff.nagriksetu-demo.example", flow["simulated_code"])

    flow = auth.begin_staff_registration("reviewer02@staff.nagriksetu-demo.example", "Reviewer", PASSWORD, PASSWORD)
    auth.verify_staff_registration("reviewer02@staff.nagriksetu-demo.example", flow["simulated_code"])
    with pytest.raises(ValueError):
        auth.verify_staff_registration("reviewer02@staff.nagriksetu-demo.example", flow["simulated_code"])


def test_staff_email_code_locks_after_five_wrong_attempts(db):
    email = "auditor01@staff.nagriksetu-demo.example"
    auth.begin_staff_registration(email, "Auditor", PASSWORD, PASSWORD, code="135790")
    for _ in range(5):
        with pytest.raises(ValueError):
            auth.verify_staff_registration(email, "000000")
    with pytest.raises(ValueError, match="attempt"):
        auth.verify_staff_registration(email, "000000")


def test_staff_registration_ignores_tampered_role_and_public_email_refused(db):
    with pytest.raises(ValueError, match="staff registration"):
        _public("operator01@staff.nagriksetu-demo.example")
    flow = auth.begin_staff_registration("operator02@staff.nagriksetu-demo.example", "Staff", PASSWORD, PASSWORD,
                                         requested_role="auditor")
    user = auth.verify_staff_registration("operator02@staff.nagriksetu-demo.example", flow["simulated_code"])
    assert user["role"] == "operator"
    with pytest.raises(ValueError):
        auth.register_user("tampered@public.example", "Tampered", PASSWORD, password_confirm=PASSWORD,
                           requested_role="reviewer")


@pytest.mark.parametrize("value,expected", [
    ("9876543210", "+919876543210"), ("09876543210", "+919876543210"),
    ("919876543210", "+919876543210"), ("+919876543210", "+919876543210"),
    ("+91 98765-43210", "+919876543210"),
])
def test_indian_phone_normalization(value, expected):
    assert auth.normalize_indian_phone(value) == expected


@pytest.mark.parametrize("value", ["123456789", "5123456789", "abc9876543", "+11234567890", "99999999999"])
def test_invalid_indian_phone_formats_rejected(value):
    with pytest.raises(ValueError):
        auth.normalize_indian_phone(value)


def test_public_email_registration_and_email_login(db):
    user = _public()
    assert auth.authenticate("RESIDENT@PUBLIC.EXAMPLE", PASSWORD)["id"] == user["id"]


def test_public_phone_registration_and_login_requires_otp(db):
    flow = auth.begin_public_phone_registration("9876543210", "Phone Resident", PASSWORD, PASSWORD)
    assert not fetch_all("SELECT id FROM users WHERE phone=?", ("+919876543210",))
    user = auth.verify_public_phone_registration("+91 98765-43210", flow["simulated_code"])
    assert user["role"] == "public"
    assert auth.authenticate("09876543210", PASSWORD)["id"] == user["id"]


def test_public_duplicate_email_and_phone_refused(db):
    _public("duplicate@public.example")
    _public("another@public.example", "9876543210")
    with pytest.raises(ValueError):
        _public("DUPLICATE@public.example")
    with pytest.raises(ValueError):
        _public("another@public.example", "09876543210")


def test_staff_login_by_phone_refused_and_generic_credentials_error(db):
    account = _public()
    staff_flow = auth.begin_staff_registration("reviewer03@staff.nagriksetu-demo.example", "Staff", PASSWORD, PASSWORD)
    staff = auth.verify_staff_registration("reviewer03@staff.nagriksetu-demo.example", staff_flow["simulated_code"])
    execute("UPDATE users SET phone='+919876543210',phone_verified=1 WHERE id=?", (staff["id"],))
    assert auth.authenticate("9876543210", PASSWORD) is None
    assert auth.authenticate(staff["email"], PASSWORD)["id"] == staff["id"]
    assert auth.authenticate("unknown@public.example", PASSWORD) is None
    assert auth.authenticate(account["email"], "Wrong!River55") is None


def test_login_lockout_window_expires(db, monkeypatch):
    user = _public()
    for _ in range(5):
        auth.authenticate(user["email"], "Wrong!River55")
    with pytest.raises(auth.LoginLockedError):
        auth.authenticate(user["email"], PASSWORD)
    execute("UPDATE auth_login_attempts SET locked_until=?,window_started_at=? WHERE identifier_hash=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
             (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(),
             auth.identifier_hash(user["email"])))
    assert auth.authenticate(user["email"], PASSWORD)["id"] == user["id"]


def test_otp_request_cooldown_persists(db):
    flow = auth.begin_public_phone_registration("9876543210", "Resident", PASSWORD, PASSWORD)
    with pytest.raises(ValueError, match="wait"):
        auth.resend_public_phone_otp("9876543210")
    assert flow["simulated_code"]


def test_otp_requests_are_limited_in_the_database(db):
    flow = auth.begin_public_phone_registration("9876543210", "Resident", PASSWORD, PASSWORD)
    for _ in range(4):
        execute("UPDATE verification_challenges SET last_sent_at=? WHERE id=?",
                ((datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat(), flow["challenge_id"]))
        flow = auth.resend_public_phone_otp("9876543210")
    execute("UPDATE verification_challenges SET last_sent_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat(), flow["challenge_id"]))
    with pytest.raises(ValueError, match="Too many code requests"):
        auth.resend_public_phone_otp("9876543210")


def test_password_database_contains_no_plain_passwords_or_codes(db):
    code = "246810"
    flow = auth.begin_staff_registration("auditor02@staff.nagriksetu-demo.example", "Auditor", PASSWORD, PASSWORD,
                                         code=code)
    rows = fetch_all("SELECT password_hash FROM verification_challenges WHERE id=?", (flow["challenge_id"],))
    assert PASSWORD not in repr(rows)
    assert code not in repr(fetch_all("SELECT code_hash FROM verification_challenges"))
    auth.verify_staff_registration("auditor02@staff.nagriksetu-demo.example", code)
    assert PASSWORD not in repr(fetch_all("SELECT password_hash FROM users"))


def test_auth_events_are_append_only_and_identifiers_masked(db):
    _public("private.person@example.test")
    row = fetch_all("SELECT * FROM auth_events ORDER BY id DESC LIMIT 1")[0]
    assert "private.person@example.test" not in repr(row)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute("UPDATE auth_events SET outcome='tampered' WHERE id=?", (row["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        execute("DELETE FROM auth_events WHERE id=?", (row["id"],))


def test_session_expiry_is_30_minutes(db):
    account = _public()
    session = {}
    auth.start_session(session, account)
    assert auth.refresh_session(session)["id"] == account["id"]
    session["auth_last_activity"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    assert auth.refresh_session(session) is None
    assert "authenticated_user" not in session


@pytest.mark.parametrize("password,accepted", [
    ("Secure!River72", True), ("Crystal-Banyan-Copper-Meadow", True),
    ("short", False), ("Password123!", False), ("1234567890", False),
    ("qwerty12345!", False), ("Aaaaaaaa!1", False), ("Aa123456789 " * 12, False),
    ("Secure!123456", False),
    ("MyEmail!river2026", False), ("PersonName!2026", False),
])
def test_password_policy_accepts_and_rejects(password, accepted):
    result = auth.assess_password(password, email="myemail@example.test", name="Person Name", phone="+919999999999")
    assert result["accepted"] is accepted


def test_password_policy_suggestions_and_secret_generator(monkeypatch):
    weak = auth.assess_password("weak", email="citizen@example.test")
    assert weak["score"] in range(5)
    assert weak["failed_rules"] and weak["suggestions"]
    assert any("passphrase" in suggestion.lower() for suggestion in weak["suggestions"])
    generated = auth.generate_strong_password()
    assert len(generated) >= 16
    assert auth.assess_password(generated)["accepted"]
    # Prove the generator delegates randomness to the standard secrets API.
    from core import password_policy
    calls = []
    original = password_policy.secrets.choice
    monkeypatch.setattr(password_policy.secrets, "choice", lambda source: (calls.append(1), original(source))[1])
    password_policy.generate_strong_password()
    assert len(calls) >= 16


def test_service_role_policy_deny_citizen_reviewer_and_auditor_write(db):
    citizen = _public()
    with pytest.raises(PermissionError):
        auth.authorize_user_action(citizen["id"], "can_review")
    staff_flow = auth.begin_staff_registration("auditor03@staff.nagriksetu-demo.example", "Auditor", PASSWORD, PASSWORD)
    auditor = auth.verify_staff_registration("auditor03@staff.nagriksetu-demo.example", staff_flow["simulated_code"])
    with pytest.raises(PermissionError):
        auth.authorize_user_action(auditor["id"], "can_review")
    from core.db import insert_complaint
    from core.reviews import submit_review
    cid = insert_complaint({"case_id": "AUTH-RBAC", "original_text": "Broken streetlight",
                            "language": "english", "normalized_text": "broken streetlight",
                            "channel": "portal", "location": "Morar", "issue": "electricity",
                            "requested_action": "repair", "missing_fields": "", "is_synthetic": 1})
    with pytest.raises(PermissionError):
        submit_review(cid, "public", "accept", "Electricity Dept", actor_user=citizen)
    with pytest.raises(PermissionError):
        submit_review(cid, "auditor", "accept", "Electricity Dept", actor_user=auditor)


def test_login_identifier_validation_strips_controls(db):
    assert auth.authenticate_identifier("\nBAD@EMAIL", PASSWORD) is None


def test_disabling_a_directory_row_invalidates_existing_staff_authentication(db):
    email = "operator04@staff.nagriksetu-demo.example"
    flow = auth.begin_staff_registration(email, "Ignored", PASSWORD, PASSWORD)
    account = auth.verify_staff_registration(email, flow["simulated_code"])
    execute("UPDATE staff_directory SET status='disabled' WHERE staff_email=?", (email,))
    assert auth.get_active_user(account["id"]) is None
    assert auth.authenticate_identifier(email, PASSWORD) is None


def test_unauthenticated_app_visit_shows_only_sign_in(db):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path(__file__).resolve().parent.parent / "app.py", default_timeout=20).run()
    assert not app.exception
    assert any("NagrikSetu" in element.value for element in app.markdown)
    assert not any("Submit a civic concern" in element.value for element in app.markdown)


@pytest.mark.parametrize("role,email", [
    ("operator", "operator03@staff.nagriksetu-demo.example"),
    ("reviewer", "reviewer04@staff.nagriksetu-demo.example"),
    ("auditor", "auditor04@staff.nagriksetu-demo.example"),
])
def test_every_page_boots_for_each_staff_role(db, role, email):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    flow = auth.begin_staff_registration(email, "Ignored Form Name", PASSWORD, PASSWORD)
    account = auth.verify_staff_registration(email, flow["simulated_code"])
    assert account["role"] == role
    pages = [f"pages/{name}" for name in (
        "0_Home.py", "1_Intake.py", "2_Review.py", "3_Challenge.py", "4_Evaluation.py",
        "5_Relabel.py", "6_Inbox.py", "7_Replay.py", "8_Request_Review.py",
        "9_Security.py", "10_Public_Portal.py", "11_Request_Review_Queue.py", "12_Area_Access_Admin.py")]
    app = AppTest.from_file(Path(__file__).resolve().parent.parent / "app.py", default_timeout=20)
    auth.start_session(app.session_state, account)
    app.run()
    assert not app.exception
    for page in pages:
        app.switch_page(page).run()
        assert not app.exception, f"{role} failed to render {page}: {app.exception}"
