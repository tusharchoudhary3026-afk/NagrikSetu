from pathlib import Path

from streamlit.testing.v1 import AppTest
from core.auth import begin_staff_registration, register_user, verify_staff_registration
from core.db import execute


def _staff_account(email, name="Test Staff", role="reviewer"):
    execute("INSERT OR IGNORE INTO staff_directory(staff_email,full_name,role,department,status,registered,tag) "
            "VALUES(?,?,?,'Grievance Cell','active',0,'SYNTHETIC')", (email, name, role))
    flow = begin_staff_registration(email, name, "Safe!Green2026", "Safe!Green2026")
    return verify_staff_registration(email, flow["simulated_code"])


def test_logged_out_app_shell_keeps_navigation_registered_and_shows_login(monkeypatch, db):
    monkeypatch.delenv("NYAYAFLOW_SETUP_TOKEN", raising=False)
    root = Path(__file__).resolve().parent.parent
    app = AppTest.from_file(root / "app.py", default_timeout=20).run()
    assert not app.exception
    assert any(element.label == "Your name" for element in app.text_input)
    assert not any("Sign in to access this page" in element.value for element in app.error)


def test_opening_protected_file_page_without_session_shows_sign_in_link(monkeypatch, db):
    monkeypatch.delenv("NYAYAFLOW_SETUP_TOKEN", raising=False)
    root = Path(__file__).resolve().parent.parent
    app = AppTest.from_file(root / "app.py", default_timeout=20).run()
    app.switch_page("pages/5_Relabel.py").run()
    assert not app.exception
    assert any("requires a signed-in account" in item.value for item in app.info)
    assert any(link.label == "Go to NagrikSetu sign in" for link in app.page_link)


def test_reviewer_can_open_the_role_filtered_navigation(monkeypatch, db):
    account = _staff_account("reviewer01@staff.nagriksetu-demo.example")
    root = Path(__file__).resolve().parent.parent
    app = AppTest.from_file(root / "app.py", default_timeout=20)
    app.session_state["authenticated_user"] = account
    app.run()
    assert not app.exception
    assert any("NagrikSetu" in item.value for item in app.markdown)
    assert any("Reviewer" in item.value for item in app.markdown)
    assert sum(item.value.count("Reviewer") for item in app.markdown) == 1
    assert len(app.sidebar.get("caption")) == 0


def test_every_page_starts_headlessly_with_a_permitted_session(db):
    root = Path(__file__).resolve().parent.parent
    public = register_user("resident@app-test.example", "Test Resident", "Safe!Green2026",
                           password_confirm="Safe!Green2026")
    reviewer = _staff_account("reviewer01@staff.nagriksetu-demo.example")

    for page in sorted((root / "pages").glob("*.py")):
        account = public if page.name in {"10_Public_Portal.py", "8_Request_Review.py"} else reviewer
        app = AppTest.from_file(root / "app.py", default_timeout=30)
        app.session_state["authenticated_user"] = account
        app.run()
        app.switch_page(f"pages/{page.name}").run()
        assert not app.exception, f"{page.name} raised: {[error.message for error in app.exception]}"
