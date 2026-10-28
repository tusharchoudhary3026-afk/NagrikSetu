from pathlib import Path

from streamlit.testing.v1 import AppTest
from core.auth import authenticate, bootstrap_user


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
    bootstrap_user("reviewer", "long-password-example", "reviewer", "setup-token", "setup-token")
    account = authenticate("reviewer", "long-password-example")
    root = Path(__file__).resolve().parent.parent
    app = AppTest.from_file(root / "app.py", default_timeout=20)
    app.session_state["authenticated_user"] = account
    app.run()
    assert not app.exception
    assert any("NagrikSetu" in item.value for item in app.markdown)
    assert any("reviewer" in item.value for item in app.markdown)
    assert sum(item.value.count("reviewer") for item in app.markdown) == 1
    assert len(app.sidebar.get("caption")) == 0
