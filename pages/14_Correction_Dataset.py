import pandas as pd
import streamlit as st

from core.config import SIM_LABEL, feature_enabled
from core.corrections import list_corrections, review_correction
from core.ui import apply_demo_style, render_hero, require_permission

user = require_permission("can_manage_corrections")
if not feature_enabled("learning"):
    st.info("Correction review and offline learning are disabled by configuration.")
    st.stop()
apply_demo_style()
render_hero("Technical review", "Correction dataset", "Inspect reviewer labels and admit only verified examples to offline experiments.")
st.warning(SIM_LABEL)

status_filter = st.selectbox("Dataset status", ["all", "unreviewed", "verified", "excluded"],
                            format_func=lambda value: {
                                "all": "All corrections", "unreviewed": "Awaiting independent review",
                                "verified": "Verified for experiments", "excluded": "Excluded / disputed",
                            }[value])
try:
    rows = list_corrections(user, status_filter)
except PermissionError as exc:
    st.error(f"You do not have permission to view this dataset: {exc}")
    st.stop()

if not rows:
    st.info("No corrections are available in your authorized service areas for this filter.")
    st.stop()

summary = st.columns(3)
summary[0].metric("Corrections shown", len(rows))
summary[1].metric("Verified", sum(row.get("review_status") == "verified" for row in rows))
summary[2].metric("Excluded / disputed", sum(row.get("review_status") == "rejected" for row in rows))
st.dataframe(pd.DataFrame([{
    "Case": row["case_id"], "Area": row.get("area_name") or row.get("location") or "Unknown",
    "Issue": row.get("issue") or "Unknown", "Suggested": row.get("suggested_dept") or "Unknown",
    "Reviewer label": row["correct_dept"], "Reason": row.get("reason") or "Not recorded",
    "Provenance": row.get("label_source") or "Unknown", "Review status": row.get("review_status") or "Unreviewed",
    "Reviewed by": row.get("reviewed_by") or "—", "Created": row["created_at"],
} for row in rows]), hide_index=True, width="stretch")

st.subheader("Verify or exclude a correction")
options = {f"{row['case_id']} · {row['correct_dept']} · {row.get('label_source') or 'unknown source'}": row
           for row in rows}
with st.form("correction_review_form"):
    selected = st.selectbox("Correction", list(options))
    decision = st.radio("Dataset decision", ["verified", "rejected"], horizontal=True,
                        format_func=lambda value: "Include after verification" if value == "verified"
                        else "Exclude / disputed")
    reason = st.text_area("Review reason (required)")
    submitted = st.form_submit_button("Save review decision")
if submitted:
    correction = options[selected]
    try:
        review_correction(correction["id"], user.get("name") or user["email"], user["role"],
                          decision, reason, actor_email=user["email"], actor_user=user)
        st.success("Correction review and audit event saved.")
        st.rerun()
    except (ValueError, PermissionError) as exc:
        st.error(str(exc))

st.caption("Review decisions are append-only. Only the latest verified decision admits a label to an offline experiment; a disputed label is excluded.")
