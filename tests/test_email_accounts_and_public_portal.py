import io
import sqlite3
import secrets

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from pathlib import Path

from core import auth
from core.attachment import read_attachment, save_attachment
from core.db import fetch_all, insert_complaint
from core import db as dbm
from core.portal import list_own_complaints
from core.reviews import submit_review


def _complaint(case_id, submitted_by=None):
    return insert_complaint({
        "case_id": case_id, "parent_id": None, "original_text": "Streetlight is broken near Ward 4",
        "language": "english", "normalized_text": "streetlight broken ward 4", "channel": "portal",
        "location": "Ward 4", "issue": "electricity", "requested_action": "repair",
        "missing_fields": "", "is_synthetic": 1,
    }, submitted_by=submitted_by)


def test_email_password_hash_and_verification():
    encoded = auth.hash_password("example-password")
    assert encoded != "example-password"
    assert auth.verify_password("example-password", encoded)
    assert not auth.verify_password("wrong-password", encoded)


def test_email_login_locks_after_five_failed_attempts(db):
    auth.register_user("resident@example.test", "Resident", "example-password",
                       password_confirm="example-password")
    for _ in range(5):
        assert auth.authenticate_email("resident@example.test", "wrong-password") is None
    with pytest.raises(auth.LoginLockedError):
        auth.authenticate_email("resident@example.test", "example-password")


def test_unverified_government_registration_is_public(db, monkeypatch):
    monkeypatch.setattr(auth, "government_allowlisted", lambda email: False)
    account = auth.register_user("not-listed@example.test", "Resident", "example-password",
                                 password_confirm="example-password", requested_role="government",
                                 invite_code="invalid")
    assert account["role"] == "public"
    assert not account["government_access_verified"]


def test_old_username_accounts_are_preserved_as_legacy_during_migration(tmp_path, monkeypatch):
    path = tmp_path / "old-accounts.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, "
                 "role TEXT, active INTEGER, created_at TEXT)")
    conn.execute("INSERT INTO users VALUES (1,'old-reviewer','unchanged-hash','reviewer',1,'2024-01-01')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(dbm, "DB_PATH", path)
    dbm.init_db()
    legacy = dbm.fetch_all("SELECT username,password_hash,role FROM legacy_users WHERE id=1")[0]
    assert legacy == {"username": "old-reviewer", "password_hash": "unchanged-hash", "role": "reviewer"}
    assert "email" in {row["name"] for row in dbm.fetch_all("PRAGMA table_info(users)")}
    assert dbm.fetch_all("SELECT * FROM users") == []


def test_public_account_cannot_pass_government_role_check(db, monkeypatch):
    account = auth.register_user("resident@example.test", "Resident", "example-password",
                                 password_confirm="example-password")
    assert not auth.role_allowed(account, "government")
    assert auth.role_allowed(account, "public")


def test_public_can_open_portal_but_not_government_page(db):
    account = auth.register_user("resident@example.test", "Resident", "example-password",
                                 password_confirm="example-password")
    root = Path(__file__).resolve().parent.parent
    app = AppTest.from_file(root / "app.py", default_timeout=20)
    app.session_state["authenticated_user"] = account
    app.run()
    app.switch_page("pages/10_Public_Portal.py").run()
    assert not app.exception
    assert any("Submit a civic concern" in item.value for item in app.markdown)
    app.switch_page("pages/9_Security.py").run()
    assert not app.exception
    assert any("isn't available to your account" in item.value for item in app.markdown)


def test_public_portal_returns_only_the_owner_cases(db):
    owner = auth.register_user("one@example.test", "One", "example-password",
                               password_confirm="example-password")
    other = auth.register_user("two@example.test", "Two", "example-password",
                               password_confirm="example-password")
    own_id = _complaint("CASE-OWN", owner["id"])
    other_id = _complaint("CASE-OTHER", other["id"])
    assert [row["case_id"] for row in list_own_complaints(owner["id"])] == ["CASE-OWN"]
    assert other_id != own_id


def test_government_email_is_written_as_review_ledger_actor(db):
    complaint_id = _complaint("CASE-ACTOR")
    submit_review(complaint_id, "government", "accept", "Roads Dept", actor_email="staff@example.test")
    row = fetch_all("SELECT actor FROM ledger WHERE complaint_id=?", (complaint_id,))[0]
    assert row["actor"] == "staff@example.test"


def test_photo_validation_size_extension_and_exif_removal(db, monkeypatch, tmp_path):
    monkeypatch.setenv("NYAYAFLOW_ATTACHMENT_KEY", secrets.token_hex(32))
    monkeypatch.setattr("core.attachment.ATTACHMENT_DIR", tmp_path)
    complaint_id = _complaint("CASE-PHOTO")

    bad_extension = io.BytesIO(b"not image")
    bad_extension.name = "proof.exe"
    with pytest.raises(ValueError, match="PNG, JPG"):
        save_attachment(complaint_id, bad_extension, "operator")

    oversized = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024))
    oversized.name = "large.png"
    with pytest.raises(ValueError, match="5 MB"):
        save_attachment(complaint_id, oversized, "operator")

    exif = Image.Exif()
    exif[271] = "Camera brand"
    image = io.BytesIO()
    Image.new("RGB", (3, 3), "red").save(image, format="PNG", exif=exif)
    image.name = "evidence.png"
    attachment_id = save_attachment(complaint_id, image, "operator")
    assert (tmp_path / attachment_id).is_file()
    clean = Image.open(io.BytesIO(read_attachment(
        fetch_all("SELECT id FROM attachments WHERE filename=?", (attachment_id,))[0]["id"], "reviewer")))
    assert not clean.getexif()
