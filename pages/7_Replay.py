import json
import streamlit as st
from core.db import init_db, fetch_all
from core.ledger import history
from core.attachment import get_attachments, read_attachment
from core.analytics import get_case_reassignment_timeline
from core.audit import generate_audit_export
from core import ownership
from core.config import SIM_LABEL
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero
from core.ui import require_permission

init_db()
require_permission("can_audit")
apply_demo_style()
render_hero("Audit", "Case replay", "One case from first suggestion to latest decision, in order.")
st.warning(SIM_LABEL)

rows = fetch_all("SELECT id, case_id, parent_id, original_text,is_active FROM complaints ORDER BY id DESC")
if not rows:
    st.info("No complaints yet.")
    st.stop()
pick = st.selectbox("Case", rows, format_func=lambda r: f"{r['case_id']} | "
                    f"{'merged-back sub-issue' if not r['is_active'] else 'active'} | {mask_text(r['original_text'])[:50]}")
st.write("**Original text:**", mask_text(pick["original_text"]))

st.subheader("Photo evidence")
st.caption("Photo attachments are stored securely and are not analysed automatically.")
for photo in get_attachments(pick["id"], st.session_state["authenticated_user"]["role"]):
    try:
        st.image(read_attachment(photo["id"], st.session_state["authenticated_user"]["role"]),
                 caption=f"photo attachment: stored only, not analysed · {photo['original_name']}")
    except ValueError as exc:
        st.warning(str(exc))

ICON = {"suggested": "🤖", "accept": "✅", "edit": "✏️", "clarify": "❓", "escalate": "⬆️",
        "transfer": "↔️", "challenge": "⚖️", "challenge_resolved": "🔒", "split_confirmed": "✂️",
        "split_merged_back": "🔗", "duplicate_linked": "🔗", "duplicate_unlinked": "↩️",
        "correction_verified": "🏷️"}
h = history(pick["id"])
timeline = get_case_reassignment_timeline(pick["id"])
st.subheader("Timeline (append-only ledger)")
if not timeline:
    st.caption("No ledger events for this case yet.")
for e in timeline:
    stamp = next((str(e[k]) for k in e if any(s in k.lower() for s in ("time", "created", "_at", "ts"))), "")
    with st.container(border=True):
        st.markdown(f"{ICON.get(e['event_type'], '•')} **{e['event_type']}** · {e['actor']} · "
                    f"{e['case_id']} · {stamp}")
        bits = []
        if e.get("suggested_dept"): bits.append(f"suggested: {e['suggested_dept']}")
        if e.get("final_dept"): bits.append(f"final: {e['final_dept']}")
        if e.get("reason_code"): bits.append(f"code: {e['reason_code']}")
        if bits: st.caption(" · ".join(bits))
        if e.get("reason"): st.write(f"Reason: {mask_text(e['reason'])}")
        if e.get("details"):
            try: st.caption(json.dumps(json.loads(e["details"])))
            except Exception: st.caption(str(e["details"]))

st.subheader("Pattern flags (no blame)")
b, r = ownership.detect_bounce(h), ownership.repeat_reassignment(h)
if b: st.warning(f"A → B → A pattern: {b['pattern']}")
if r: st.warning(f"Repeat reassignment: {r['moves']} owner changes ({r['path']})")
if not (b or r): st.caption("No transfer pattern detected for this case.")

ch = fetch_all("SELECT * FROM challenges WHERE complaint_id IN "
               "(SELECT id FROM complaints WHERE case_id=?) ORDER BY id", (pick["case_id"],))
if ch:
    st.subheader("Challenges")
    for c in ch:
        st.write(f"#{c['id']} · {c['raised_by']} · {c['status']}: {mask_text(c['reason'])}")

st.download_button("Download masked ledger audit report", generate_audit_export(
    st.session_state["authenticated_user"]["role"]), file_name="nagriksetu-audit.json",
    mime="application/json")
