import json
import uuid

import streamlit as st

from core.attachment import save_attachments, validate_attachments
from core.auth import require_role
from core import intake, router_baseline
from core.config import SIM_LABEL
from core.db import init_db, insert_complaint, insert_suggestion
from core.ledger import log_event
from core.portal import list_own_complaints
from core.privacy import mask_text
from core.security import attachment_encryption_status
from core.suggestions import selected_department
from core.ui import apply_demo_style, render_hero
from core.geo import partial_geography_names
from core.geo_ui import render_geography_picker

init_db()
user = require_role("public")
apply_demo_style()
render_hero("Resident portal", "Submit a civic concern", "Describe what happened and where. A person makes every final routing decision.")
st.warning(SIM_LABEL)

tab_submit, tab_track = st.tabs(["Submit a complaint", "My complaints"])
with tab_submit:
    st.caption("Share only details needed to understand the issue. Do not include passwords, financial information, or highly sensitive personal data.")
    state_code, city_code, area_code = render_geography_picker("resident-complaint", allow_unknown=True)
    st.caption("Location options are prototype coverage and may not include every ward. Choose ‘Not sure’ if unknown.")
    with st.form("public_complaint"):
        text = st.text_area("What is the problem?", height=140, placeholder="For example: A streetlight is not working near the community center.")
        location = st.text_input("Street or nearby landmark (optional)", placeholder="Street, building, or nearby landmark")
        attachments = st.file_uploader("Add up to 3 photos (optional)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
                                       help="Each photo may be up to 5 MB. Photos are securely stored for authorized staff and are never analyzed.")
        encryption = attachment_encryption_status()
        if not encryption["configured"]:
            st.info("Secure photo upload is currently unavailable. You can still submit the complaint without photos.")
        submitted = st.form_submit_button("Review and submit", type="primary", width="stretch")
    if submitted:
        try:
            if not (text or "").strip():
                raise ValueError("Describe the issue before submitting.")
            if attachments and not encryption["configured"]:
                raise ValueError("Photo upload is unavailable until secure storage is configured. Remove the photos and submit the text, or try later.")
            validate_attachments(attachments)
            rec = intake.process(text, "portal", location.strip())
            geo = partial_geography_names(state_code, city_code, area_code)
            rec.update(geo)
            if area_code:
                rec["location"] = location.strip() or geo["area_name"]
            if not area_code:
                rec["missing_fields"] = ",".join(filter(None, [rec.get("missing_fields", ""), "service_area"]))
            route = router_baseline.route(text)
            rec["case_id"] = f"CASE-{uuid.uuid4().hex[:12].upper()}"
            complaint_id = insert_complaint(rec, submitted_by=user["id"])
            try:
                insert_suggestion(complaint_id, "baseline", route["top3"], route["evidence"], route["confidence"], route["abstained"])
                suggestion = selected_department(route)
                log_event(complaint_id, "suggested", "system", suggested_dept=suggestion,
                          details={"abstained": route["abstained"], "confidence": route["confidence"],
                                   "synthetic": True, "extracted_issue_evidence": rec.get("issue_evidence", [])})
                if attachments:
                    save_attachments(complaint_id, attachments, user["role"], actor_user=user)
            except Exception:
                # Complaint rows may already have append-only ledger history, so do
                # not delete them as a rollback strategy. The failure remains visible.
                raise
            st.session_state["last_public_submission"] = {"case_id": rec["case_id"],
                                                           "question": intake.clarification_question(rec),
                                                           "area": rec.get("area_name")}
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error("The complaint could not be saved. Please try again.")

    last = st.session_state.get("last_public_submission")
    if last:
        st.success(f"Your complaint was submitted. Case ID: {last['case_id']}")
        if last.get("area"):
            st.caption(f"Service area: {last['area']}")
        if last["question"]:
            st.info(f"A useful detail to add for staff: {last['question']}")

with tab_track:
    st.subheader("Your submitted complaints")
    st.caption("Only complaints submitted by this account appear here.")
    rows = list_own_complaints(user["id"])
    if not rows:
        st.info("You have not submitted any complaints yet.")
    for row in rows:
        with st.container(border=True):
            st.markdown(f"### {row['case_id']}")
            st.write(mask_text(row["original_text"]))
            status = row.get("last_decision") or "Under review"
            if row.get("open_requests"):
                status = "Review requested"
            st.caption(f"Status: {status}")
            if row.get("location") and row["location"] != "unknown":
                st.caption(f"Location: {row['location']}")
            if row.get("state_name") or row.get("city_name") or row.get("area_name"):
                st.caption("Selected area: " + " · ".join(x for x in
                          (row.get("state_name"), row.get("city_name"), row.get("area_name")) if x))
            if row.get("abstained"):
                st.info("Awaiting human review; the system did not make a supported suggestion.")
            elif row.get("top3"):
                try:
                    top3 = json.loads(row["top3"])
                except (TypeError, json.JSONDecodeError):
                    top3 = []
                if top3:
                    st.caption(f"Suggestion: {top3[0].get('dept', 'Not available')} · final decisions are made by staff")
            if row.get("final_dept"):
                st.write(f"Latest staff decision: **{row['final_dept']}**")
            if row.get("open_requests"):
                st.caption("Your review request is awaiting a staff response.")
            else:
                st.caption("You can request a human review from the My complaints page.")
