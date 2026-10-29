import streamlit as st

from core.challenges import claim_challenge, resolve_challenge
from core.config import REASON_CODES, SIM_LABEL
from core.db import fetch_all, init_db
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero, require_permission
from core.geo import is_geography_admin, require_complaint_area_access, scoped_complaint_ids
from core.splitter import propose_split
from core.staff_dashboard import get_staff_case_detail

init_db()
user = require_permission("can_review")
apply_demo_style()
render_hero("Staff review", "Request review queue", "Resolve resident requests with a reasoned staff decision.")
st.warning(SIM_LABEL)
if user.get("role") != "reviewer":
    st.info("Only reviewer accounts can resolve citizen routing review requests.")
    st.stop()

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
        st.caption(f"Reason: {challenge.get('reason_category', 'other').replace('_', ' ').title()} · "
                   f"Submitted: {challenge['created_at']} · "
                   f"Assigned reviewer: {challenge.get('assigned_reviewer') or 'Unassigned'}")
        st.write(mask_text(challenge["original_text"]))
        st.write(f"Request: {mask_text(challenge['reason'])}")
        detail = get_staff_case_detail(user, challenge["complaint_id"])
        st.write(f"Current department: {detail['current_department'] or 'Not assigned'} · "
                 f"Suggested department: {detail['suggested_department'] or 'No supported suggestion'}")
        if detail["routing_history"]:
            with st.expander("Routing evidence and prior decisions"):
                for event in detail["routing_history"]:
                    st.caption(f"{event['method']} · {event['created_at']} · "
                               f"{'Manual review required' if event['abstained'] else 'Recommendation only'}")
                    st.json({"suggestions": event["top3"], "evidence": event["evidence"]})
                st.markdown("**Case timeline**")
                st.dataframe(detail["timeline"], hide_index=True, width="stretch")
        assigned = challenge.get("assigned_reviewer")
        if assigned and assigned.casefold() != (user.get("email") or "").casefold():
            st.info("This request is assigned to another reviewer.")
            continue
        if not assigned and user.get("role") == "reviewer":
            if st.button("Claim request", key=f"claim-{challenge['id']}"):
                try:
                    claim_challenge(challenge["id"], user)
                    st.success("Review request assigned to you.")
                    st.rerun()
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
            continue
        resolution = st.text_area("Resolution reason", key=f"resolution-{challenge['id']}")
        outcome = st.selectbox("Outcome", ["accept", "edit", "split", "escalate"],
                               format_func=lambda value: {
                                   "accept": "Keep current routing",
                                   "edit": "Change department",
                                   "split": "Split and reroute issues",
                                   "escalate": "Escalate for coordination",
                               }[value], key=f"outcome-{challenge['id']}")
        final_dept = st.text_input("Final department (for edit)", key=f"department-{challenge['id']}")
        reason_code = st.selectbox("Reason code", REASON_CODES, key=f"code-{challenge['id']}")
        split_parts = None
        if outcome == "split":
            proposal = propose_split(challenge["original_text"])
            st.caption("Review and edit each sub-issue. The original complaint remains unchanged.")
            proposed_texts = [part["text"] for part in proposal["parts"]] if proposal["is_compound"] else ["", ""]
            count = max(2, len(proposed_texts))
            split_parts = [{"text": st.text_input(f"Sub-issue {index + 1}",
                                                   value=proposed_texts[index] if index < len(proposed_texts) else "",
                                                   key=f"split-{challenge['id']}-{index}")}
                           for index in range(count)]
        if st.button("Resolve request", key=f"resolve-{challenge['id']}", type="primary"):
            try:
                resolve_challenge(challenge["id"], user["role"], resolution, outcome,
                                  final_dept=final_dept, reason_code=reason_code,
                                  actor_email=user.get("email"), actor_user=user,
                                  split_parts=split_parts)
                st.success("Resolution, outcome, and audit history saved.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))
