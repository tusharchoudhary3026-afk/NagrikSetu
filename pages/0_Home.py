import streamlit as st

from core.auth import require_login
from core.db import fetch_all, init_db
from core.portal import list_own_complaints
from core.ui import apply_demo_style, render_hero

init_db()
user = require_login()
apply_demo_style()

if user["role"] == "public":
    render_hero(
        "Civic grievance support",
        "NagrikSetu",
        "Report a civic problem in Hindi, English or Hinglish, add a photo if you have one, and follow your complaint with a case ID. A staff member reviews every suggested department before anything is final.",
    )
    mine = list_own_complaints(user["id"])
    report_col, track_col = st.columns(2, gap="large")
    with report_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">Start here</div>', unsafe_allow_html=True)
            st.subheader("Report a problem")
            st.write("Tell us what happened and where. Add a photo if it helps explain the issue.")
            st.page_link("pages/10_Public_Portal.py", label="Report a problem", icon="📝", width="stretch")
    with track_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">Your cases</div>', unsafe_allow_html=True)
            st.subheader("Track my complaints")
            st.metric("Your complaints", len(mine))
            st.page_link("pages/8_Request_Review.py", label="Track my complaints", icon="📬", width="stretch")

    st.write("")
    how_col, expect_col = st.columns([1.35, 1], gap="large")
    with how_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">A simple path</div>', unsafe_allow_html=True)
            st.subheader("How it works")
            steps = [
                ("01", "Describe", "Tell us what happened and where, in Hindi, English or Hinglish. Add a photo if you can."),
                ("02", "We suggest", "The system suggests which department may handle it. If it is unsure, it says so and may ask you one question."),
                ("03", "A person reviews", "Staff check the suggestion and make the final decision. Nothing is closed automatically."),
                ("04", "Track and ask again", "Follow your case ID under My complaints. If something looks wrong, you can request a review."),
            ]
            for number, title, detail in steps:
                number_col, detail_col = st.columns([.16, 1], vertical_alignment="top")
                number_col.markdown(f"<div class='nf-score'>{number}</div>", unsafe_allow_html=True)
                detail_col.markdown(f"**{title}**  {detail}")
                st.write("")
    with expect_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">Clear expectations</div>', unsafe_allow_html=True)
            st.subheader("What to expect")
            st.markdown(
                """
                - Suggestions are not final assignments.
                - If the system is unsure, your complaint waits for a person to decide.
                - You can ask for a review of any of your complaints.
                - Photos are stored with your complaint and are not analysed automatically.
                """
            )
            st.caption("NagrikSetu is a prototype using synthetic demo data. Department rules are assumptions, not an official charter.")
else:
    render_hero(
        "Government workspace",
        "NagrikSetu",
        "Review civic reports, record reasoned decisions, and follow each case's history.",
    )
    counts = fetch_all(
        "SELECT COUNT(*) AS cases, SUM(CASE WHEN parent_id IS NOT NULL THEN 1 ELSE 0 END) AS sub_issues "
        "FROM complaints"
    )[0]
    languages = fetch_all("SELECT COUNT(DISTINCT language) AS n FROM complaints")[0]["n"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Saved complaints", counts["cases"] or 0)
    c2.metric("Linked sub-issues", counts["sub_issues"] or 0)
    c3.metric("Input languages seen", languages or 0)

    how_col, expect_col = st.columns([1.35, 1], gap="large")
    with how_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">Staff workflow</div>', unsafe_allow_html=True)
            st.subheader("Follow a complaint through the review process")
            steps = [
                ("01", "Capture", "Preserve the original report and the fields the intake rules can identify."),
                ("02", "Inspect", "Review the suggestion, evidence, uncertainty, and ownership assumptions."),
                ("03", "Consider a split", "Check proposed sub-issues and confirm only when they make sense."),
                ("04", "Resolve", "Record a reasoned decision or challenge outcome."),
            ]
            for number, title, detail in steps:
                number_col, detail_col = st.columns([.16, 1], vertical_alignment="top")
                number_col.markdown(f"<div class='nf-score'>{number}</div>", unsafe_allow_html=True)
                detail_col.markdown(f"**{title}**  {detail}")
                st.write("")
    with expect_col:
        with st.container(border=True):
            st.markdown('<div class="nf-section-kicker">Review principles</div>', unsafe_allow_html=True)
            st.subheader("Human judgement stays central")
            st.markdown(
                """
                - Suggestions are prompts for review, not final assignments.
                - Uncertain routes remain visible for a person to assess.
                - A proposed split is not saved until someone confirms it.
                """
            )
            st.caption("NagrikSetu uses synthetic demo data; department rules are assumptions.")

    st.markdown('<div class="nf-section-kicker">Quick links</div>', unsafe_allow_html=True)
    links = [
        ("pages/6_Inbox.py", "Inbox", "📥"),
        ("pages/2_Review.py", "Review", "🔎"),
        ("pages/3_Challenge.py", "Challenge", "⚖️"),
        ("pages/7_Replay.py", "Case replay", "🎞️"),
        ("pages/4_Evaluation.py", "Evaluation", "📊"),
    ]
    quick_cols = st.columns(len(links))
    for column, (path, label, icon) in zip(quick_cols, links):
        column.page_link(path, label=label, icon=icon, width="stretch")

st.divider()
st.caption("NagrikSetu · Synthetic prototype · Prototype authentication, not production-grade.")
