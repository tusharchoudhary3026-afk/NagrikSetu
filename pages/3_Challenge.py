import streamlit as st

from core.challenges import create_challenge
from core.config import SIM_LABEL
from core.db import fetch_all, init_db
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero, require_permission
from core.geo import is_geography_admin, scoped_complaints

init_db()
user = require_permission("can_review")
apply_demo_style()
render_hero("Staff review", "Challenge", "Flag a complaint for an authorized reviewer to look at again.")
st.warning(SIM_LABEL)

rows = [{key: row[key] for key in ("id", "case_id", "original_text")}
        for row in scoped_complaints(user, include_unassigned=is_geography_admin(user.get("email", "")))]
if rows:
    st.subheader("Staff challenge")
    pick = st.selectbox("Case", rows, format_func=lambda r: f"{r['case_id']} | {mask_text(r['original_text'])[:50]}")
    why = st.text_area("Why should this route be reviewed?", key="staff_challenge_reason")
    if st.button("Send staff challenge"):
        try:
            create_challenge(pick["id"], "staff", why, actor_email=user.get("email"), actor_user=user)
            st.success("Added to the reviewer queue and case history.")
        except ValueError as exc:
            st.error(str(exc))
