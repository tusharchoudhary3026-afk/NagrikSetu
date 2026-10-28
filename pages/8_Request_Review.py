import json

import streamlit as st

from core.auth import require_role
from core.db import init_db
from core.explanation import generate_grounded_explanation
from core.portal import list_own_complaints, request_own_review
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero

init_db()
user = require_role("public")
apply_demo_style()
render_hero("Resident portal", "My complaints", "Track your cases and ask an authorized reviewer to look again at a suggestion.")

rows = list_own_complaints(user["id"])
if not rows:
    st.info("You have not submitted any complaints yet.")
    st.page_link("pages/10_Public_Portal.py", label="Submit a complaint", icon="📝")
else:
    for row in rows:
        with st.container(border=True):
            st.subheader(row["case_id"])
            st.write(mask_text(row["original_text"]))
            st.caption(f"Submitted {row['created_at']} · location: {row['location'] or 'not provided'}")
            status = row.get("last_decision") or "Under review"
            if row.get("open_requests"):
                status = "Review requested"
            st.caption(f"Status: {status}")
            suggestion = None
            if row.get("top3"):
                try:
                    top3 = json.loads(row["top3"])
                except (TypeError, json.JSONDecodeError):
                    top3 = []
                suggestion = top3[0].get("dept") if top3 else None
            if suggestion and not row.get("abstained"):
                st.write(f"Preliminary suggestion: **{suggestion}**")
                try:
                    explanation = generate_grounded_explanation(row["original_text"], suggestion)
                    st.caption(f"Why this suggestion: {', '.join(explanation['grounded_keywords'])} matched {explanation['issue_type']}. This is an explanation of the suggestion, not a final decision.")
                except (ValueError, TypeError):
                    st.caption("A supported explanation is not available for this suggestion.")
            elif row.get("abstained"):
                st.info("No supported suggestion was available. The case remains for staff review.")
            if row.get("final_dept"):
                st.write(f"Latest staff decision: **{row['final_dept']}**")
            if row.get("open_requests"):
                st.info("A review request is already open for this complaint.")
                continue
            with st.form(f"review_request_{row['id']}"):
                reason = st.text_area("What should staff review?", key=f"review_reason_{row['id']}")
                submitted = st.form_submit_button("Request human review")
            if submitted:
                try:
                    request_own_review(user["id"], row["id"], reason, user["email"])
                    st.success("Your request has been sent to authorized staff. It does not change the routing decision.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
