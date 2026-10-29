import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import streamlit as st
import pandas as pd
from scripts.evaluate import run, summary
from core.config import SIM_LABEL, feature_enabled
from core.engine8_harness import evaluate_component_3_and_5
from core.analytics import detect_emerging_hotspots, get_ownership_gap_report, get_reassignment_breakdown
from core.ui import require_permission
from core.safety import evaluate_safety_rubric

user = require_permission("can_audit")
st.title("4. Evaluation")
st.error(SIM_LABEL)
st.caption("Baseline on the frozen test split. Numerator/denominator reported; small n means preliminary.")
st.subheader("Safety rubric sanity checks")
safety = evaluate_safety_rubric()
st.write({"label": safety["status_label"], "total": safety["total"],
          "recall": f"{safety['true_positive']}/{safety['positive_denominator']}",
          "false positives": f"{safety['false_positive']}/{safety['negative_denominator']}",
          "by language": safety["by_language"]})
st.caption(safety["limitation"])

st.caption("The held-out test split is used once. Model fitting uses train; threshold selection uses validation.")
if st.button("Run frozen test evaluation"):
    out = run("test")
    st.code(summary(out))
    st.subheader("Failures and abstentions")
    st.dataframe(out[out.outcome != "correct"])
    comparison = evaluate_component_3_and_5("test")
    st.subheader("Baseline vs TF-IDF (same frozen test rows)")
    st.dataframe([{key: value for key, value in summary.items() if key != "by_language"}
                  for summary in (comparison["baseline"], comparison["tfidf"])], width="stretch")
    for model in ("baseline", "tfidf"):
        st.markdown(f"**{model.upper()} results by language (correct / sample size)**")
        st.dataframe([{"language": language, **metrics}
                      for language, metrics in comparison[model]["by_language"].items()],
                     width="stretch", hide_index=True)
    curve = pd.DataFrame(comparison["component_4_curve"]).set_index("threshold")
    st.markdown("**Validation-only coverage / accuracy threshold curve**")
    st.line_chart(curve[["accuracy", "coverage"]])
    if comparison["threshold_used"] is None:
        st.warning("Validation did not meet the minimum coverage target. TF-IDF is not cleared to answer; its cases remain for human review.")
    else:
        st.caption(f"Validation-selected TF-IDF threshold: {comparison['threshold_used']}. "
                   "Results are preliminary on a small synthetic dataset; no fairness or real-world performance claim is made.")
    st.subheader("Reassignment reasons")
    st.write(get_reassignment_breakdown(user))
    st.caption("Counts describe recorded transfers; they do not establish avoidability or fault.")
    st.subheader("Ownership gap report")
    st.dataframe(get_ownership_gap_report(user), width="stretch")
    st.subheader("Potential concentration for staff review")
    st.dataframe(detect_emerging_hotspots(actor_user=user), width="stretch")

if feature_enabled("learning") and user.get("role") in {"reviewer", "auditor", "government"}:
    st.divider()
    st.page_link("pages/15_Model_Evaluation.py", label="Open offline model evaluation")
