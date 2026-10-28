"""Shared NagrikSetu branding, user bar, and responsive Streamlit styles."""
import streamlit as st

from .auth import enforce_rbac


def apply_demo_style():
    if st.session_state.get("_nagriksetu_style_rendered"):
        return
    st.markdown(
        """
        <style>
        :root {
            --ink: #10253B;
            --muted: #5B6E82;
            --navy: #0F2F52;
            --blue: #1D5C96;
            --teal: #14958F;
            --mint: #E4F6F2;
            --sky: #EAF3FB;
            --saffron: #F2A33A;
            --line: #DCE6EF;
            --paper: #FFFFFF;
            --font-ui: Inter, "Noto Sans Devanagari", "Segoe UI", system-ui, sans-serif;
            --hero-gradient: linear-gradient(120deg, var(--navy) 0%, var(--blue) 58%, #0B716D 100%);
        }
        html, body { font-family: var(--font-ui); }
        html { font-size: 16px; }
        .stApp {
            background: radial-gradient(circle at 7% 0%, rgba(20,149,143,.10), transparent 31rem),
                        linear-gradient(145deg, #F3F8FC 0%, #EEF7F6 100%);
            color: var(--ink);
        }
        header[data-testid="stHeader"] { background: transparent; }
        .block-container { max-width: 1220px; padding: 1.25rem 1.5rem 3rem; }
        h1, h2, h3, h4 { color: var(--ink); letter-spacing: -.025em; }
        h1 { font-size: clamp(1.9rem, 4vw, 3rem); line-height: 1.12; }
        h2 { font-size: clamp(1.45rem, 3vw, 2rem); }
        p, li { color: var(--ink); line-height: 1.65; }
        [data-testid="stCaptionContainer"] p { color: var(--muted); }
        [data-testid="stMetric"] {
            background: var(--paper); border: 1px solid var(--line); border-radius: 16px;
            padding: 14px 18px; box-shadow: 0 5px 18px rgba(16,37,59,.05);
        }
        [data-testid="stMetricLabel"] { color: var(--muted); }
        [data-testid="stMetricValue"] { color: var(--ink); }
        [data-testid="stVerticalBlockBorderWrapper"] > div {
            background: var(--paper); border: 1px solid var(--line) !important;
            border-radius: 18px !important; box-shadow: 0 7px 22px rgba(16,37,59,.055);
            transition: transform .18s ease, box-shadow .18s ease;
        }
        [data-testid="stVerticalBlockBorderWrapper"] > div:hover {
            transform: translateY(-2px); box-shadow: 0 12px 26px rgba(16,37,59,.09);
        }
        .stButton > button, .stPageLink > a, [data-testid="stFormSubmitButton"] button {
            min-height: 44px; padding: .55rem 1rem; border-radius: 12px !important;
            border: 1px solid var(--line) !important; font-weight: 650;
            background: var(--paper) !important; color: var(--navy) !important;
            font-family: var(--font-ui) !important;
            transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
        }
        .stButton > button:hover, .stPageLink > a:hover,
        [data-testid="stFormSubmitButton"] button:hover {
            transform: translateY(-1px); border-color: var(--teal) !important;
            box-shadow: 0 6px 16px rgba(15,47,82,.12);
        }
        .stButton > button[kind="primary"],
        button[kind*="primary"],
        [data-testid="stBaseButton-primary"],
        [data-testid="stFormSubmitButton"],
        [data-testid="stFormSubmitButton"] button[kind="primary"],
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"],
        [data-testid="stFormSubmitButton"] button,
        button[data-testid="stFormSubmitButton"],
        .stFormSubmitButton button,
        form button[type="submit"],
        [data-testid="stFormSubmitButton"] button:not(:disabled),
        [data-testid="stBaseButton-primary"] {
            background: linear-gradient(120deg, #0F2F52 0%, #1D5C96 58%, #0B716D 100%) !important;
            background-color: #1D5C96 !important; border: 0 !important; color: #fff !important;
            -webkit-text-fill-color: #fff !important;
        }
        .stButton > button[kind="primary"] *,
        button[kind*="primary"] *,
        [data-testid="stBaseButton-primary"] *,
        [data-testid="stFormSubmitButton"] *,
        [data-testid="stFormSubmitButton"] button[kind="primary"] *,
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"] * { color: #fff !important; }
        button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible,
        [role="combobox"]:focus-visible {
            outline: 3px solid #0B716D !important; outline-offset: 3px !important;
            box-shadow: 0 0 0 2px #fff !important;
        }
        [data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
        [data-testid="stSelectbox"] div:has(> [role="combobox"]) {
            background: var(--paper) !important; border: 1px solid #B9C9D7 !important;
            border-radius: 12px !important;
        }
        input, textarea, [role="combobox"] { color: var(--ink) !important; font-family: var(--font-ui); }
        input::placeholder, textarea::placeholder { color: #52677C !important; opacity: 1; }
        [data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {
            font-family: "Material Symbols Rounded", "Material Icons" !important;
            font-feature-settings: "liga" !important;
        }
        button[aria-label="Show password"], button[aria-label="Hide password"],
        [data-testid="stPasswordInput"] button {
            min-width: 2.75rem !important; overflow: hidden; color: transparent !important;
            -webkit-text-fill-color: transparent !important; font-size: 0 !important;
        }
        button[aria-label="Show password"]::after,
        button[aria-label="Hide password"]::after,
        [data-testid="stPasswordInput"] button::after {
            content: "◉"; color: var(--navy); -webkit-text-fill-color: var(--navy);
            font-size: 1rem; line-height: 1;
        }
        [data-testid="stFormSubmitButton"] button *,
        button[data-testid="stFormSubmitButton"] *,
        .stFormSubmitButton button *, form button[type="submit"] * {
            color: #fff !important; -webkit-text-fill-color: #fff !important;
        }
        [data-testid="stTextInputRootElement"]:has(input[type="password"]) [data-testid="stIconMaterial"] {
            font-size: 0 !important; line-height: 1 !important;
        }
        [data-testid="stTextInputRootElement"]:has(input[type="password"]) [data-testid="stIconMaterial"]::after {
            content: "◉"; font: 1.05rem/1 var(--font-ui); color: var(--navy);
        }
        [data-testid="stAlert"] { border-radius: 14px; }
        [data-testid="stTabs"] button { min-height: 44px; font-weight: 650; color: var(--navy); }
        .nf-userbar {
            display: flex; align-items: center; gap: .55rem; color: var(--ink);
            font-size: .94rem; font-weight: 650; white-space: nowrap;
        }
        .nf-wordmark { color: var(--navy); font-size: 1.15rem; font-weight: 800; letter-spacing: -.03em; }
        .nf-role-pill {
            display: inline-flex; align-items: center; min-height: 28px; padding: 2px 11px;
            border-radius: 999px; background: var(--mint); color: #075A56; font-size: .78rem;
            font-weight: 750; border: 1px solid #B6E2DB;
        }
        .nf-hero {
            position: relative; overflow: hidden; border-radius: 22px; padding: clamp(24px, 4vw, 42px);
            color: #fff; background: var(--hero-gradient); box-shadow: 0 16px 36px rgba(15,47,82,.16);
            margin: 4px 0 24px;
        }
        .nf-hero:after {
            content: ''; position: absolute; width: 220px; height: 220px; right: -70px; top: -120px;
            border: 1px solid rgba(255,255,255,.2); border-radius: 50%;
            box-shadow: 0 0 0 28px rgba(255,255,255,.045), 0 0 0 58px rgba(255,255,255,.03);
        }
        .nf-hero h1 { color: #fff !important; font-size: clamp(2rem, 5vw, 3.2rem); margin: 0 0 12px; }
        .nf-hero p { color: #fff !important; max-width: 850px; margin: 0; font-size: 1.04rem; }
        .nf-eyebrow { color: #D8F4F0; text-transform: uppercase; letter-spacing: .14em;
            font-size: .75rem; font-weight: 800; margin-bottom: 12px; }
        .nf-section-kicker { color: var(--blue); text-transform: uppercase; letter-spacing: .13em;
            font-size: .72rem; font-weight: 800; margin-bottom: 6px; }
        .nf-score { font-size: 1.65rem; font-weight: 800; color: var(--blue); line-height: 1.1; }
        .nf-muted { color: var(--muted); }
        [data-testid="stPageNav"] { background: transparent; }
        [data-testid="stPageNav"] a { min-height: 44px; border-radius: 11px; font-weight: 650; }
        [data-testid="stPageNav"] a[aria-current="page"] { background: var(--mint); color: var(--navy); }
        @media (max-width: 700px) {
            .block-container { padding: .75rem .85rem 2rem; }
            [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .8rem; }
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                min-width: min(100%, 20rem) !important; flex: 1 1 100% !important;
            }
            [data-testid="stPageNav"] { max-width: 100%; overflow-x: visible; flex-wrap: wrap; }
            .nf-hero { border-radius: 18px; }
            .nf-userbar { white-space: normal; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_nagriksetu_style_rendered"] = True


def render_userbar(user: dict | None = None):
    """Render one responsive signed-in bar per Streamlit rerun."""
    if st.session_state.get("_nagriksetu_userbar_rendered"):
        return
    user = user or st.session_state.get("authenticated_user")
    if not user:
        return
    apply_demo_style()
    left, right, signout = st.columns([5, 3.3, 1.2], vertical_alignment="center")
    with left:
        st.markdown('<div class="nf-userbar nf-wordmark">🧭 NagrikSetu</div>', unsafe_allow_html=True)
    with right:
        role = "Government" if user.get("role") == "government" else "Public"
        st.markdown(
            f'<div class="nf-userbar">{user.get("name", "User")} '
            f'<span class="nf-role-pill">{role}</span></div>', unsafe_allow_html=True)
    with signout:
        if st.button("Sign out", key="nagriksetu_signout", width="stretch"):
            st.session_state.pop("authenticated_user", None)
            st.session_state.pop("google_pending_profile", None)
            try:
                if getattr(st.user, "is_logged_in", False):
                    st.logout()
            except Exception:
                pass
            st.rerun()
    st.divider()
    st.session_state["_nagriksetu_userbar_rendered"] = True


def render_hero(eyebrow: str, title: str, description: str):
    st.markdown(
        f"""
        <section class="nf-hero">
          <div class="nf-eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def require_permission(action: str):
    """Stop a page when no signed-in account has the required permission."""
    user = st.session_state.get("authenticated_user")
    if not user:
        apply_demo_style()
        render_hero("Staff access", "Sign in to continue",
                    "This section is for authorized staff. Sign in from the NagrikSetu overview to continue.")
        st.info("This staff page requires a signed-in account. Return to NagrikSetu to sign in or create an account.")
        st.page_link("pages/0_Home.py", label="Go to NagrikSetu sign in", icon="🔐")
        st.stop()
    try:
        enforce_rbac(user.get("role"), action)
    except PermissionError:
        apply_demo_style()
        render_hero("Staff access", "This page isn't available to your account",
                    f"Your {user.get('role', 'current')} role does not include this action.")
        st.page_link("pages/0_Home.py", label="Return to NagrikSetu", icon="🏠")
        st.stop()
    render_userbar(user)
    return user
