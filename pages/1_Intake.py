import uuid
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

from core import intake, ownership, router_baseline, splitter
from core.attachment import save_attachment
from core.config import SIM_LABEL
from core.db import init_db, insert_complaint, insert_suggestion
from core.ledger import log_event
from core.safety import flag_safety
from core.security import attachment_encryption_status
from core.speech import validate_transcript_submission
from core.ui import apply_demo_style, render_hero, require_permission

init_db()
user = require_permission("can_intake")
apply_demo_style()
render_hero("Complaint intake", "Complain here", "Capture the original report, inspect suggestions, and save it for a person to review.")
st.warning(SIM_LABEL)

speech_enabled = st.checkbox("I understand browser speech recognition may send audio to its provider; NagrikSetu does not store audio.")
speech_component = components.declare_component(
    "nyayaflow_speech_input", path=str(Path(__file__).resolve().parents[1] / "components" / "speech_input"))
speech = speech_component(enabled=speech_enabled, key="nyayaflow_speech", default=None)
if speech and speech.get("id") != st.session_state.get("last_speech_id"):
    st.session_state["intake_text"] = speech.get("transcript", "")
    st.session_state["last_speech_id"] = speech["id"]
    st.session_state["speech_transcript_pending"] = bool(speech.get("transcript"))
    st.session_state["confirm_speech_transcript"] = False
    st.session_state["speech_language"] = speech.get("language", "en-IN")
text = st.text_area("Complaint (Hindi / English / Hinglish) · edit the transcript before processing", height=120,
                    key="intake_text")
speech_used = bool(st.session_state.get("speech_transcript_pending"))
transcript_confirmed = st.checkbox("I reviewed and confirm this transcript", key="confirm_speech_transcript") if speech_used else False
if speech_used:
    st.caption(f"Speech trial transcript · browser language {st.session_state.get('speech_language', 'unknown')} · "
               "Hindi-English mixed speech quality is unvalidated.")
channel = st.selectbox("Channel", ["portal", "phone", "social", "in-person"])
loc_hint = st.text_input("Location (optional, staff-assisted)")
if st.button("Process complaint", type="primary"):
    try:
        text = validate_transcript_submission(text, speech_used, transcript_confirmed)
        rec = intake.process(text, channel, loc_hint)
        st.session_state["rec"] = rec
        st.session_state["split"] = splitter.propose_split(text)
        st.session_state["route"] = router_baseline.route(text)
        st.session_state["safety"] = flag_safety(text)
        st.session_state["speech_transcript_pending"] = False
    except ValueError as exc:
        st.error(str(exc))

if "rec" in st.session_state:
    rec, sp, rt = st.session_state["rec"], st.session_state["split"], st.session_state["route"]
    st.subheader("Extracted fields")
    st.write({"language": rec["language"], "location": rec["location"], "issue": rec["issue"],
              "requested action": rec["requested_action"], "channel": rec["channel"]})
    st.caption("The original complaint is preserved separately and never replaced by normalized text.")
    question = intake.clarification_question(rec)
    if question:
        st.info(f"Clarification question: {question}")

    safety = st.session_state.get("safety", {"flagged": False})
    if safety["flagged"]:
        st.error(f"Human attention flag · {safety['rubric_status']}: " + "; ".join(x["label"] for x in safety["flags"]))
        st.caption(safety["message"])

    st.subheader("Routing suggestions (keyword baseline)")
    if rt["abstained"]:
        st.warning("No supported route found. This complaint remains in manual review.")
    for suggestion in rt["top3"]:
        st.write(f"{suggestion['dept']} · score {suggestion['score']} · evidence: {rt['evidence'].get(suggestion['dept'], [])}")
    for overlap in ownership.check_suggestions([x["dept"] for x in rt["top3"]], text):
        st.warning(f"Possible ownership overlap: {overlap['owner']} / {overlap['overlap_owner']} · "
                   f"{overlap['verification']} · {overlap['source']}")

    st.subheader("Possible sub-issues")
    st.write(sp["note"])
    if sp["is_compound"]:
        for part in sp["parts"]:
            st.write(f"- {part['text']} → {[x['dept'] for x in part['suggestion']['top3'][:1]]}")
    confirm_split = False
    if sp["is_compound"] and user["role"] == "government":
        confirm_split = st.checkbox("I reviewed and confirm these proposed sub-issues")
    elif sp["is_compound"]:
        st.caption("A reviewer must confirm the proposed split. The complaint will be saved intact for now.")
    photo_status = attachment_encryption_status()
    if photo_status["configured"]:
        st.caption("Photo evidence storage: AES-256-GCM encryption at rest. Images are not analyzed.")
    else:
        st.warning("Secure photo upload is disabled until NYAYAFLOW_ATTACHMENT_KEY is configured.")
    photo = st.file_uploader("Optional photo evidence (JPEG/PNG, max 5 MB; no image analysis)",
                             type=["jpg", "jpeg", "png"], disabled=not photo_status["configured"])

    if st.button("Save to review queue"):
        if photo is not None and not photo_status["configured"]:
            st.error("Photo not saved: configure NYAYAFLOW_ATTACHMENT_KEY first.")
            st.stop()
        rec["case_id"] = f"CASE-{uuid.uuid4().hex.upper()}"
        try:
            cid = insert_complaint(rec)
            insert_suggestion(cid, "baseline", rt["top3"], rt["evidence"], rt["confidence"], rt["abstained"])
            top = rt["top3"][0]["dept"] if rt["top3"] else None
            log_event(cid, "suggested", "system", suggested_dept=top,
                      details={"abstained": rt["abstained"], "confidence": rt["confidence"],
                               "safety_flags": safety.get("flags", [])})
            if photo is not None:
                save_attachment(cid, photo, user["role"])
            if confirm_split:
                child_ids = splitter.confirm_split(cid, rec["case_id"], sp["parts"], user["role"],
                                                   actor_email=user.get("email"))
                st.info(f"Human-confirmed split saved as {len(child_ids)} linked sub-issues.")
            st.success(f"Saved as {rec['case_id']}")
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))
