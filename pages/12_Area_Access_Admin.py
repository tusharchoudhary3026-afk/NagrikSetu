import streamlit as st

from core.config import SIM_LABEL
from core.geo import (active_area_assignments, approve_area_request, area_options, is_geography_admin,
                      pending_area_requests, reject_area_request, revoke_area_assignment, scoped_complaints)
from core.ui import apply_demo_style, render_hero, require_permission
from core.privacy import mask_text

user = require_permission("can_review")
if user.get("role") not in {"government", "reviewer"} or not is_geography_admin(user.get("email", "")):
    st.error("This page is restricted to configured geography administrators.")
    st.stop()

apply_demo_style()
render_hero("Area access administration", "Verify staff service areas",
            "Approve only assignments verified by your authorized government process.")
st.warning(SIM_LABEL)
st.caption("Selections are requests, not proof of authority. Every approval or rejection adds an append-only event.")

options = area_options()
labels = {(state_code, city_code, area_code):
          f"{state['name']} · {city['name']} · {area_name}"
          for state_code, state in options.items()
          for city_code, city in state["cities"].items()
          for area_code, area_name in city["areas"].items()}

requests = pending_area_requests(user["email"])
if not requests:
    st.info("There are no pending service-area requests.")
for request in requests:
    key = (request["state_code"], request["city_code"], request["area_code"])
    with st.container(border=True):
        st.subheader(f"{request['name']} · {labels.get(key, 'Unknown configured area')}")
        st.caption(f"{request['email']} · requested {request['created_at']}")
        st.write(f"Staff note: {mask_text(request['reason'])}")
        verification = st.text_input("Verification evidence / reason", key=f"geo-reason-{request['id']}")
        approve_col, reject_col = st.columns(2)
        if approve_col.button("Approve assignment", key=f"geo-approve-{request['id']}"):
            try:
                approve_area_request(request["id"], user["email"], verification)
                st.success("Area access approved and added to history.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))
        if reject_col.button("Reject request", key=f"geo-reject-{request['id']}"):
            try:
                reject_area_request(request["id"], user["email"], verification)
                st.info("Area request rejected and added to history.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))

st.divider()
st.subheader("Active staff area assignments")
for grant in active_area_assignments(user["email"]):
    key = (grant["state_code"], grant["city_code"], grant["area_code"])
    with st.container(border=True):
        st.write(f"{grant['name']} · {grant['email']} · {labels.get(key, 'Unknown configured area')}")
        revoke_reason = st.text_input("Reason to revoke or end this assignment", key=f"geo-revoke-reason-{grant['id']}")
        if st.button("Revoke area access", key=f"geo-revoke-{grant['id']}"):
            try:
                revoke_area_assignment(grant["id"], user["email"], revoke_reason)
                st.success("Area access revoked and recorded in history.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))

st.divider()
st.subheader("Unassigned complaints · restricted queue")
unassigned = [row for row in scoped_complaints(user, include_unassigned=True)
              if not row.get("state_code") or not row.get("city_code") or not row.get("area_code")]
if not unassigned:
    st.caption("No unassigned complaints are awaiting geographic triage.")
else:
    st.dataframe([{"Case ID": row["case_id"], "Location text": row["location"],
                   "Original complaint": mask_text(row["original_text"]), "Created": row["created_at"]}
                  for row in unassigned], hide_index=True, width="stretch")
    st.caption("This queue is visible only to geography administrators; staff cannot claim unassigned cases by selecting an area.")
