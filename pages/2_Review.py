import json
import streamlit as st

from core.attachment import get_attachments, read_attachment
from core.config import REASON_CODES, REVIEW_ACTIONS, SIM_LABEL
from core.corrections import review_correction
from core.db import fetch_all, init_db
from core.duplicates import find_candidates, record_decision
from core.explanation import generate_grounded_explanation
from core.ledger import history
from core.ownership import check_suggestions, detect_bounce, repeat_reassignment
from core.privacy import mask_text
from core.reviews import submit_review
from core.splitter import merge_back
from core.ui import require_permission

init_db()
user = require_permission("can_review")
st.title("Human review")
st.warning(SIM_LABEL)

rows = fetch_all("SELECT id,case_id,parent_id,language,original_text FROM complaints ORDER BY id DESC")
if not rows:
    st.info("No complaints yet. Use Intake first.")
    st.stop()
pick = st.selectbox("Complaint", rows,
                    format_func=lambda r: f"{r['case_id']} | {r['language']} | {mask_text(r['original_text'])[:50]}")
st.write("**Original complaint (personal details masked):**", mask_text(pick["original_text"]))

sugs = fetch_all("SELECT * FROM suggestions WHERE complaint_id=? ORDER BY id DESC LIMIT 1", (pick["id"],))
suggested = None
top3 = []
if sugs:
    top3 = json.loads(sugs[0]["top3"])
    suggested = top3[0]["dept"] if top3 else None
    evidence = json.loads(sugs[0]["evidence"] or "{}")
    st.write("**Department suggestions:**", top3)
    st.caption(f"Confidence score: {sugs[0]['confidence']} (uncalibrated) · Manual review: {bool(sugs[0]['abstained'])}")
    for item in top3:
        dept = item.get("dept")
        st.caption(f"Evidence for {dept}: {evidence.get(dept, evidence.get('matched_terms', []))}")
        try:
            explanation = generate_grounded_explanation(pick["original_text"], dept)
            st.info(f"{', '.join(explanation['grounded_keywords'])} matches {explanation['issue_type']}. "
                    f"Rule source: {explanation['rule_source']} ({explanation['verification']}).")
        except ValueError as exc:
            st.warning(f"No grounded explanation available for {dept}: {exc}")

for overlap in check_suggestions([item["dept"] for item in top3], pick["original_text"]):
    st.warning(f"Possible ownership overlap: {overlap['owner']} / {overlap['overlap_owner']} · "
               f"{overlap['issue_type']} · {overlap['verification']} · {overlap['source']}")

children = fetch_all("SELECT id,original_text FROM complaints WHERE parent_id=? AND is_active=1 ORDER BY id", (pick["id"],))
if children:
    st.subheader("Confirmed sub-issues")
    st.dataframe([{"id": child["id"], "text": mask_text(child["original_text"])} for child in children],
                 hide_index=True, width="stretch")
    if st.button("Merge split back into the intact complaint"):
        try:
            count = merge_back(pick["id"], user["role"], actor_email=user.get("email"))
            st.success(f"Merged {count} child views back. All child records and history were retained.")
            st.rerun()
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))

st.subheader("Human decision")
action = st.radio("Action", REVIEW_ACTIONS, horizontal=True)
final = st.text_input("Final department", value=suggested or "")
reason = st.text_area("Reason (required for edit, transfer, and escalation)")
code = st.selectbox("Reason code", REASON_CODES)
if st.button("Record decision", type="primary"):
    try:
        submit_review(pick["id"], user["role"], action, final, reason, code,
                      actor_email=user.get("email"))
        st.success("Decision and any correction example were saved together. Earlier history remains intact.")
    except (ValueError, PermissionError) as exc:
        st.error(str(exc))

st.subheader("Photo attachments")
attachments = get_attachments(pick["id"], user["role"])
for attachment in attachments:
    try:
        st.image(read_attachment(attachment["id"], user["role"]),
                 caption=f"photo attachment: stored only, not analysed · {attachment['original_name']}")
    except ValueError as exc:
        st.warning(str(exc))
if not attachments:
    st.caption("No photos attached.")

st.subheader("Possible duplicate or related incidents")
st.caption("Scores rank candidates; they are not probabilities or duplicate decisions. Similarity never changes status or routing.")
candidates = find_candidates(pick["id"])
if candidates:
    candidate = st.selectbox("Candidate", candidates,
        format_func=lambda c: f"{c['case_id']} · score {c['score']:.2f} · {c['decision']}")
    left, right = st.columns(2)
    left.markdown("**Selected complaint**")
    left.write(mask_text(pick["original_text"]))
    right.markdown(f"**Candidate {candidate['case_id']}**")
    right.write(mask_text(candidate["original_text"]))
    st.write({"shared_terms": candidate["shared_terms"], "location_match": candidate["location_match"],
              "time_difference_days": candidate["time_difference_days"], "missing_or_conflicting": candidate["conflicts"]})
    decision = st.selectbox("Human decision", ["same_incident", "related", "different", "needs_info", "unlink"],
                            format_func=lambda x: {"same_incident": "Confirm same incident", "related": "Related, not duplicate",
                                "different": "Different incident", "needs_info": "Need more information", "unlink": "Unlink / reopen"}[x])
    duplicate_reason = st.text_input("Decision reason")
    if st.button("Save duplicate review"):
        try:
            record_decision(pick["id"], candidate["complaint_id"], decision, user["role"], duplicate_reason,
                            actor_email=user.get("email"))
            st.success("Duplicate review recorded. Original complaints and decisions remain available.")
            st.rerun()
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))
else:
    st.info("No possible candidates found. Missing location or time may limit matching.")

st.subheader("Ledger (append-only)")
h = history(pick["id"])
st.dataframe([{**event, "reason": mask_text(event.get("reason", ""))} for event in h],
             width="stretch", hide_index=True)
bounce, repeats = detect_bounce(h), repeat_reassignment(h)
if bounce:
    st.warning(f"Transfer pattern flagged (no blame): {bounce['pattern']}")
if repeats:
    st.warning(f"Repeat reassignment flag: {repeats['moves']} owner changes ({repeats['path']}); no fault is inferred.")

st.subheader("Correction examples awaiting verification")
st.caption("Reviewer corrections are not used for training unless a reviewer verifies them. Retraining is offline and never automatic.")
pending = fetch_all("SELECT c.id,c.text,c.wrong_dept,c.correct_dept,c.reason,c.reason_code,c.label_source "
                    "FROM corrections c WHERE NOT EXISTS (SELECT 1 FROM correction_reviews r "
                    "WHERE r.correction_id=c.id) ORDER BY c.id")
if not pending:
    st.caption("No unverified corrections.")
for correction in pending:
    with st.expander(f"Correction #{correction['id']} · {correction['wrong_dept']} → {correction['correct_dept']}"):
        st.write(mask_text(correction["text"]))
        st.caption(f"Reason code: {correction['reason_code']} · Provenance: {correction['label_source']}")
        verification_reason = st.text_input("Verification note", key=f"verify-note-{correction['id']}")
        col1, col2 = st.columns(2)
        for column, status, label in ((col1, "verified", "Verify label"), (col2, "rejected", "Reject label")):
            if column.button(label, key=f"{status}-{correction['id']}"):
                try:
                    review_correction(correction["id"], user.get("email", "government"), user["role"], status,
                                      verification_reason, actor_email=user.get("email"))
                    st.success("Verification outcome appended to the audit history.")
                    st.rerun()
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
