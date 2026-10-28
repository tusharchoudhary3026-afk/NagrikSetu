# import pandas as pd
# import streamlit as st
# from core.config import ROOT, SIM_LABEL

# SHEET = ROOT / "data" / "relabel_sheet.csv"
# OPTIONS = ["Roads", "Drainage", "Sanitation", "Electricity", "Water",
#            "MULTI (needs 2 departments)", "UNCLEAR (cannot tell)"]

# st.title("5. Independent relabelling")
# st.warning(SIM_LABEL)
# st.caption("For a team member who did NOT write the complaints. Do not open complaints.csv or the dataset card "
#            "while labelling. Choose the department you think should handle each complaint, using your own judgement.")

# who = st.text_input("Your name (recorded with your labels)")
# sheet = pd.read_csv(SHEET, encoding="utf-8-sig", dtype=str).fillna("")
# if "labeller" not in sheet.columns:
#     sheet["labeller"] = ""
# done = int((sheet["your_label"] != "").sum())
# st.progress(done / len(sheet), text=f"{done} of {len(sheet)} labelled")

# pending = sheet[sheet["your_label"] == ""]
# if pending.empty:
#     st.success("All labelled. Now run: python -m scripts.score_relabel")
#     st.stop()

# row = pending.iloc[0]
# n = row["row_no"]
# st.subheader(f"Complaint {n}")
# st.write(row["text"])
# choice = st.radio("Which department should handle this?", OPTIONS, index=None, key=f"c{n}")
# note = st.text_input("Note (optional; for MULTI write both departments)", key=f"n{n}")

# if st.button("Save and next"):
#     if not who.strip():
#         st.error("Enter your name first.")
#     elif choice is None:
#         st.error("Pick one option.")
#     else:
#         i = sheet.index[sheet["row_no"] == n][0]
#         sheet.loc[i, ["your_label", "notes", "labeller"]] = [choice.split(" ")[0], note, who.strip()]
#         sheet.to_csv(SHEET, index=False, encoding="utf-8-sig")
#         st.rerun()



import pandas as pd
import streamlit as st
from core.config import ROOT, SIM_LABEL
from core.ui import apply_demo_style, render_hero
from core.ui import require_permission

SHEET = ROOT / "data" / "relabel_sheet.csv"
require_permission("can_review")
OPTIONS = {"Roads": "Roads", "Drainage": "Drainage", "Sanitation": "Sanitation",
           "Electricity": "Electricity", "Water supply": "Water",
           "The complaint clearly names TWO different problems (write both in the note)": "MULTI",
           "Too vague to tell": "UNCLEAR"}

apply_demo_style()
render_hero("Dataset quality", "Independent relabelling", "Review synthetic complaint labels independently to help assess the dataset.")
st.warning(SIM_LABEL)
st.caption("For ONE or TWO named team members who did NOT write the complaints. Do not open complaints.csv or the "
           "dataset card. Read each complaint and pick the department that should handle it. Most complaints "
           "have exactly one department; pick the 'TWO problems' option only when the text itself names two.")

who = st.text_input("Your full name (recorded with your labels)")
sheet = pd.read_csv(SHEET, encoding="utf-8-sig", dtype=str).fillna("")
if sheet.empty:
    st.info("The relabelling sheet has no complaints yet.")
    st.stop()
if "labeller" not in sheet.columns:
    sheet["labeller"] = ""
done = int((sheet["your_label"] != "").sum())
st.progress(done / len(sheet), text=f"{done} of {len(sheet)} labelled")

pending = sheet[sheet["your_label"] == ""]
if pending.empty:
    st.success("All labelled. Now run: python -m scripts.score_relabel")
    st.stop()

row = pending.iloc[0]
n = row["row_no"]
st.subheader(f"Complaint {n}")
st.write(row["text"])
choice = st.radio("Which department should handle this?", list(OPTIONS), index=None, key=f"c{n}")
note = st.text_input("Note (optional)", key=f"n{n}")

if st.button("Save and next"):
    if not who.strip():
        st.error("Enter your name first.")
    elif choice is None:
        st.error("Pick one option.")
    else:
        i = sheet.index[sheet["row_no"] == n][0]
        sheet.loc[i, ["your_label", "notes", "labeller"]] = [OPTIONS[choice], note, who.strip()]
        sheet.to_csv(SHEET, index=False, encoding="utf-8-sig")
        st.rerun()
