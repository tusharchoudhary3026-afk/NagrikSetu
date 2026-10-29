"""Engine 8 Components 3, 4, and 5:
- Component 3: Baseline vs TF-IDF comparison on frozen test split
- Component 4: Coverage vs Accuracy curve & abstention tracking
- Component 5: Language-wise error gap with Wilson 95% CIs
"""
import json
import math
import pandas as pd
from core import router_baseline, router_ml, splitter, ownership
from core.config import COMPLAINTS
from core.verify_split import verify_split_leakage, verify_frozen_test_split

def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 2), round(c + h, 2))

def evaluate_component_3_and_5(split="test"):
    """Component 3: Baseline vs TF-IDF comparison & Component 5: Language-wise CIs."""
    if split != "test":
        raise ValueError("Performance reports must use the frozen held-out test split.")
    leakage = verify_split_leakage()
    if not leakage["passed"]:
        raise ValueError(f"Refusing to score a leaking or invalid split: {leakage}")
    frozen = verify_frozen_test_split()
    if not frozen["passed"]:
        raise ValueError(f"Refusing to score a modified held-out test split: {frozen}")
    df = pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    tr, va, te = df[df.split == "train"], df[df.split == "val"], df[df.split == split]
    if tr.empty or va.empty or te.empty:
        raise ValueError("Train, validation, and held-out test splits must all contain rows.")
    kw = router_baseline.load_keywords()
    # Fit only on train; tune abstention only on validation; test is used once for reporting.
    ml = router_ml.fit_default(tr)
    th, curve = router_ml.choose_threshold(ml, va)
    threshold_met = any(row["coverage"] >= 0.25 and row["answered"] for row in curve)

    results = {
        "split": split,
        "n_test_rows": len(te),
        "threshold_used": th,
        "threshold_met_target": threshold_met,
        "threshold_source": "validation" if threshold_met else None,
    }

    # Baseline evaluation (Component 3)
    base_results = _evaluate_router("baseline", te, lambda t: router_baseline.route(t, kw))
    # TF-IDF evaluation (Component 3)
    tfidf_results = _evaluate_router("tfidf", te, lambda t: ml.route(t, th))

    results["baseline"] = base_results
    results["tfidf"] = tfidf_results
    results["component_4_curve"] = curve  # Component 4: Coverage vs Accuracy curve data
    return results

def _evaluate_router(method_name, df, route_fn):
    s = router_ml.single_owner_rows(df)
    predictions = [(route_fn(t), y, l) for t, y, l in zip(s["text"], s["owner_label"], s["language"])]
    
    answered = [(r, y, l) for r, y, l in predictions if not r["abstained"]]
    correct_answered = sum(r["top3"][0]["dept"] == y for r, y, _ in answered)
    
    summary_data = {
        "method": method_name,
        "total_single_owner": len(s),
        "answered_count": len(answered),
        "abstained_count": len(s) - len(answered),
        "correct_overall": correct_answered,
        "ci_overall": wilson(correct_answered, len(s)),
        "by_language": {}
    }

    # Component 5: Language-wise breakdown with Wilson CIs (English, Hindi, Hinglish)
    for lang in ["english", "hindi", "hinglish"]:
        sub = [(r, y) for r, y, l in predictions if l == lang]
        ans_sub = [(r, y) for r, y in sub if not r["abstained"]]
        correct_lang = sum(r["top3"][0]["dept"] == y for r, y in ans_sub)
        summary_data["by_language"][lang] = {
            "n": len(sub),
            "answered": len(ans_sub),
            "correct": correct_lang,
            "abstained": len(sub) - len(ans_sub),
            "ci": wilson(correct_lang, len(sub))
        }
    return summary_data

if __name__ == "__main__":
    print("Running Engine 8 Components 3, 4, and 5 Harness...")
    res = evaluate_component_3_and_5("test")
    print(json.dumps(res, indent=2))
