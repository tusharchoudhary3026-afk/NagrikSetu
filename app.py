"""NagrikSetu sign-in shell and role-aware top navigation."""
import streamlit as st

from core.auth import (LoginLockedError, authenticate_email, get_active_user,
                       get_user_by_email, oidc_available, register_user)
from core.db import init_db
from core.ui import apply_demo_style, render_hero, render_userbar

st.set_page_config(page_title="NagrikSetu | Civic grievance support", page_icon="🧭",
                   layout="wide", initial_sidebar_state="collapsed")
st.session_state["_nagriksetu_userbar_rendered"] = False
st.session_state["_nagriksetu_style_rendered"] = False
init_db()


def _sync_oidc_account():
    try:
        oidc_user = st.user
        if not getattr(oidc_user, "is_logged_in", False):
            return
        profile = oidc_user.to_dict()
        email = profile.get("email", "")
        account = get_user_by_email(email)
        if account is None:
            st.session_state["google_pending_profile"] = {
                "email": email, "name": profile.get("name") or email.split("@")[0]
            }
            return
        st.session_state["authenticated_user"] = get_active_user(account["id"])
    except Exception:
        # OIDC is optional in local development; configuration is shown below.
        return


_sync_oidc_account()
cached = st.session_state.get("authenticated_user")
active = get_active_user(cached.get("id")) if isinstance(cached, dict) and cached.get("id") else None
if active and active.get("role") in {"public", "government", "operator", "reviewer", "auditor"}:
    st.session_state["authenticated_user"] = active
else:
    st.session_state.pop("authenticated_user", None)

user = st.session_state.get("authenticated_user")


def _page(path, title, icon, *, default=False, visibility="visible"):
    return st.Page(path, title=title, icon=icon, default=default, visibility=visibility)


if user and user.get("role") == "public":
    nav_pages = [
        _page("pages/0_Home.py", "Overview", "🏠", default=True),
        _page("pages/10_Public_Portal.py", "Submit & track", "📝"),
        _page("pages/8_Request_Review.py", "My complaints", "🙋"),
        _page("pages/1_Intake.py", "Complain here", "📝", visibility="hidden"),
        _page("pages/6_Inbox.py", "Inbox", "📥", visibility="hidden"),
        _page("pages/2_Review.py", "Review", "🔎", visibility="hidden"),
        _page("pages/3_Challenge.py", "Challenge / request queue", "⚖️", visibility="hidden"),
        _page("pages/11_Request_Review_Queue.py", "Request review queue", "📨", visibility="hidden"),
        _page("pages/7_Replay.py", "Case replay", "🎞️", visibility="hidden"),
        _page("pages/4_Evaluation.py", "Evaluation", "📊", visibility="hidden"),
        _page("pages/5_Relabel.py", "Relabel", "🏷️", visibility="hidden"),
        _page("pages/9_Security.py", "Security status", "🔐", visibility="hidden"),
    ]
    router = st.navigation(nav_pages, position="top")
elif user:
    router = st.navigation({
        "Complaints": [
            _page("pages/0_Home.py", "Overview", "🏠", default=True),
            _page("pages/1_Intake.py", "Complain here", "📝"),
            _page("pages/6_Inbox.py", "Inbox", "📥"),
            _page("pages/10_Public_Portal.py", "Submit & track", "📝", visibility="hidden"),
            _page("pages/8_Request_Review.py", "My complaints", "🙋", visibility="hidden"),
        ],
        "Review": [
            _page("pages/2_Review.py", "Review", "🔎"),
            _page("pages/3_Challenge.py", "Challenge", "⚖️"),
            _page("pages/11_Request_Review_Queue.py", "Request review queue", "📨"),
            _page("pages/7_Replay.py", "Case replay", "🎞️"),
        ],
        "Insights": [
            _page("pages/4_Evaluation.py", "Evaluation", "📊"),
            _page("pages/5_Relabel.py", "Relabel", "🏷️"),
            _page("pages/9_Security.py", "Security status", "🔐"),
        ],
    }, position="top")
else:
    # Keep the sign-in view clean: no application pages are exposed before login.
    guest_pages = [
        st.Page(lambda: None, title="Sign in", icon="🔐", url_path="sign-in",
                default=True, visibility="hidden"),
        _page("pages/0_Home.py", "Overview", "🏠", visibility="hidden"),
        _page("pages/10_Public_Portal.py", "Submit & track", "📝", visibility="hidden"),
        _page("pages/8_Request_Review.py", "My complaints", "🙋", visibility="hidden"),
        _page("pages/1_Intake.py", "Complain here", "📝", visibility="hidden"),
        _page("pages/6_Inbox.py", "Inbox", "📥", visibility="hidden"),
        _page("pages/2_Review.py", "Review", "🔎", visibility="hidden"),
        _page("pages/3_Challenge.py", "Challenge / request queue", "⚖️", visibility="hidden"),
        _page("pages/11_Request_Review_Queue.py", "Request review queue", "📨", visibility="hidden"),
        _page("pages/7_Replay.py", "Case replay", "🎞️", visibility="hidden"),
        _page("pages/4_Evaluation.py", "Evaluation", "📊", visibility="hidden"),
        _page("pages/5_Relabel.py", "Relabel", "🏷️", visibility="hidden"),
        _page("pages/9_Security.py", "Security status", "🔐", visibility="hidden"),
    ]
    router = st.navigation(guest_pages,
                           position="hidden")


if user:
    apply_demo_style()
    render_userbar(user)
else:
    apply_demo_style()
    render_hero("Civic grievance support", "NagrikSetu",
                "Report a civic problem, follow your case, and request a human review when needed.")
    info_col, form_col = st.columns([1.05, 1], gap="large")
    with info_col:
        st.subheader("A person reviews every suggestion")
        st.write("NagrikSetu helps residents share civic problems. Staff review department suggestions; nothing is closed automatically.")
        st.markdown("- Report in Hindi, English, or Hinglish.\n- Add an optional photo.\n- Track your complaint with its case ID.")
        st.caption("Legacy username accounts are preserved as records. Create a new email account to use this interface.")
        try:
            if oidc_available(st.secrets):
                st.button("Continue with Google", on_click=st.login, args=("google",), width="stretch")
            else:
                st.caption("Google sign-in is optional. Configure [auth] in .streamlit/secrets.toml to enable it.")
        except Exception:
            st.caption("Google sign-in is optional. Configure [auth] in .streamlit/secrets.toml to enable it.")
    with form_col:
        google_pending = st.session_state.get("google_pending_profile")
        if google_pending:
            st.subheader("Finish creating your account")
            st.caption(f"Google account: {google_pending['email']}")
            with st.form("google_profile"):
                google_name = st.text_input("Your display name", value=google_pending["name"])
                google_role = st.selectbox("Account type", ["public", "government"],
                                           format_func=lambda value: "Resident / public user" if value == "public" else "Government staff")
                google_invite = st.text_input("Government invite code (if required)", type="password") if google_role == "government" else ""
                google_submitted = st.form_submit_button("Continue", type="primary", width="stretch")
            if google_submitted:
                try:
                    account = register_user(google_pending["email"], google_name, None,
                                            requested_role=google_role, invite_code=google_invite,
                                            auth_provider="google")
                    st.session_state.pop("google_pending_profile", None)
                    st.session_state["authenticated_user"] = account
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            login_tab, register_tab = st.tabs(["Sign in", "Create account"])
            with login_tab:
                with st.form("email_login"):
                    email = st.text_input("Email address", autocomplete="email")
                    password = st.text_input("Password", type="password", autocomplete="current-password")
                    submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
                if submitted:
                    try:
                        account = authenticate_email(email, password)
                        if account:
                            st.session_state["authenticated_user"] = account
                            st.rerun()
                        st.error("Email or password is incorrect.")
                    except LoginLockedError as exc:
                        st.error(str(exc))
                    except ValueError as exc:
                        st.error(str(exc))
            with register_tab:
                with st.form("email_registration"):
                    name = st.text_input("Your name")
                    new_email = st.text_input("Email address", key="register_email", autocomplete="email")
                    requested_role = st.selectbox("Account type", ["public", "government"],
                                                  format_func=lambda value: "Resident / public user" if value == "public" else "Government staff")
                    invite_code = st.text_input("Government invite code (if required)", type="password") if requested_role == "government" else ""
                    new_password = st.text_input("Password (at least 8 characters)", type="password", key="register_password")
                    confirm = st.text_input("Confirm password", type="password")
                    submitted = st.form_submit_button("Create account", type="primary", width="stretch")
                if submitted:
                    try:
                        account = register_user(new_email, name, new_password, password_confirm=confirm,
                                                requested_role=requested_role, invite_code=invite_code)
                        if requested_role == "government" and account["role"] != "government":
                            st.warning("Government access could not be verified. Your account was created with public access; contact your administrator.")
                        else:
                            st.success("Account created. You are now signed in.")
                        st.session_state["authenticated_user"] = account
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    st.divider()
    st.caption("Prototype authentication, not production-grade.")

router.run()
