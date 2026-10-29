import streamlit as st

from core.challenges import resolve_challenge
from core.config import REASON_CODES, SIM_LABEL
from core.db import fetch_all, init_db
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero, require_permission
from core.geo import is_geography_admin, require_complaint_area_access, scoped_complaint_ids

init_db()
user = require_permission("can_review")
apply_demo_style()
render_hero("Staff review", "Request review queue", "Resolve resident requests with a reasoned staff decision.")
st.warning(SIM_LABEL)

scope_ids = scoped_complaint_ids(user, include_unassigned=is_geography_admin(user.get("email", "")))
if scope_ids:
    placeholders = ",".join("?" for _ in scope_ids)
    open_challenges = fetch_all(
        "SELECT h.*,c.case_id,c.original_text FROM challenges h "
        "JOIN complaints c ON c.id=h.complaint_id WHERE h.status='open' "
        f"AND h.complaint_id IN ({placeholders}) ORDER BY h.id", scope_ids)
else:
    open_challenges = []
if not open_challenges:
    st.info("There are no open review requests.")
for challenge in open_challenges:
    with st.container(border=True):
        st.markdown(f"**{challenge['case_id']} · requested by {challenge['raised_by']}**")
        st.write(mask_text(challenge["original_text"]))
        st.write(f"Request: {mask_text(challenge['reason'])}")
        resolution = st.text_area("Resolution reason", key=f"resolution-{challenge['id']}")
        outcome = st.selectbox("Outcome", ["accept", "edit", "escalate"], key=f"outcome-{challenge['id']}")
        final_dept = st.text_input("Final department (for edit)", key=f"department-{challenge['id']}")
        reason_code = st.selectbox("Reason code", REASON_CODES, key=f"code-{challenge['id']}")
        if st.button("Resolve request", key=f"resolve-{challenge['id']}", type="primary"):
            try:
                resolve_challenge(challenge["id"], user["role"], resolution, outcome,
                                  final_dept=final_dept, reason_code=reason_code,
                                  actor_email=user.get("email"), actor_user=user)
                st.success("Resolution, outcome, and audit history saved.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))
