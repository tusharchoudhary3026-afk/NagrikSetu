import pandas as pd
import streamlit as st
from core.db import init_db, fetch_all
from core.config import SIM_LABEL
from core.privacy import mask_text
from core.ui import apply_demo_style, render_hero
from core.ui import require_permission

init_db()
require_permission("can_audit")
apply_demo_style()
render_hero("Dashboard", "Complaint inbox", "All saved complaints with channel, language and review status.")
st.warning(SIM_LABEL)

rows = fetch_all("""
SELECT c.id, c.case_id, c.parent_id, c.channel, c.language, c.location, c.issue, c.original_text,
 (SELECT abstained FROM suggestions s WHERE s.complaint_id=c.id ORDER BY s.id LIMIT 1) AS abstained,
 (SELECT COUNT(*) FROM challenges h WHERE h.complaint_id=c.id AND h.status='open') AS open_challenges,
 (SELECT event_type FROM ledger l WHERE l.complaint_id=c.id
    AND l.event_type IN ('accept','edit','clarify','escalate','transfer') ORDER BY l.id DESC LIMIT 1) AS last_decision
FROM complaints c WHERE c.is_active=1 ORDER BY c.id DESC""")
if not rows:
    st.info("No complaints yet. Use 'Complain here' first.")
    st.stop()

df = pd.DataFrame(rows)
df["status"] = df.apply(
    lambda row: "review requested" if row["open_challenges"] else
        (row["last_decision"] if pd.notna(row["last_decision"]) else "needs review"),
    axis=1,
)
df["kind"] = df["parent_id"].apply(lambda p: "sub-issue" if pd.notna(p) else "case")
df["uncertain"] = df["abstained"].apply(lambda a: "yes" if a == 1 else "no")
df["text"] = df["original_text"].apply(lambda t: mask_text(t)[:90])

c1, c2, c3 = st.columns(3)
lang = c1.multiselect("Language", sorted(df["language"].unique()))
chan = c2.multiselect("Channel", sorted(df["channel"].dropna().unique()))
stat = c3.multiselect("Status", sorted(df["status"].unique()))
view = df
if lang: view = view[view["language"].isin(lang)]
if chan: view = view[view["channel"].isin(chan)]
if stat: view = view[view["status"].isin(stat)]

m1, m2, m3 = st.columns(3)
m1.metric("Shown", f"{len(view)} of {len(df)}")
m2.metric("Needs review", int((view["status"] == "needs review").sum()))
m3.metric("Open challenges", int(view["open_challenges"].sum()))

st.dataframe(view[["case_id", "kind", "channel", "language", "location", "issue",
                   "uncertain", "status", "open_challenges", "text"]],
             width="stretch", hide_index=True)
st.caption("Phone numbers and emails are masked in this view. Nothing here is auto-closed or auto-assigned.")
