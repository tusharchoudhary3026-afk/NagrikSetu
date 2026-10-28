"""Baseline evaluation on the frozen test split.
Single-owner rows: accuracy on answered + abstentions.  UNCLEAR rows: correct = abstain.
MULTI rows: correct = splitter flags compound.  Always report numerator/denominator."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pandas as pd
from core.config import COMPLAINTS, ROOT
from core import router_baseline, splitter
from core.verify_split import verify_split_leakage, verify_frozen_test_split


def run(split="test", save_failures=False):
    if split == "test":
        leakage = verify_split_leakage()
        frozen = verify_frozen_test_split()
        if not leakage["passed"] or not frozen["passed"]:
            raise ValueError(f"Evaluation stopped: invalid grouped/frozen test set. {leakage}; {frozen}")
    df = pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    df = df[df["split"] == split]
    kw = router_baseline.load_keywords()
    rows = []
    for _, r in df.iterrows():
        res = router_baseline.route(r["text"], kw)
        pred = None if res["abstained"] else res["top3"][0]["dept"]
        flagged = splitter.propose_split(r["text"])["is_compound"]
        label = r["owner_label"]
        kind = "compound" if label == "MULTI" else "unclear" if label == "UNCLEAR" else "single"
        if kind == "single":
            outcome = "abstained" if pred is None else ("correct" if pred == label else "wrong")
        elif kind == "unclear":
            outcome = "correct" if pred is None else "wrong"          # should abstain
        else:
            outcome = "correct" if flagged else "wrong"               # should flag compound
        rows.append({"id": r["id"], "text": r["text"], "language": r["language"], "kind": kind,
                     "label": label, "pred": pred, "split_flagged": flagged,
                     "overlap": r.get("has_overlap", 0), "outcome": outcome})
    out = pd.DataFrame(rows)
    if save_failures:
        fails = out[out.outcome != "correct"]
        fails.to_csv(ROOT / "docs" / "baseline_failures.csv", index=False, encoding="utf-8-sig")
    return out


def summary(out):
    lines = [f"Rows: {len(out)}"]
    s = out[out.kind == "single"]
    ans = s[s.outcome != "abstained"]
    lines.append(f"Single-owner: {(s.outcome=='correct').sum()}/{len(s)} correct overall, "
                 f"{(ans.outcome=='correct').sum()}/{len(ans)} correct when answered, "
                 f"{(s.outcome=='abstained').sum()}/{len(s)} abstained")
    u = out[out.kind == "unclear"]
    lines.append(f"Unclear: {(u.outcome=='correct').sum()}/{len(u)} correctly abstained")
    c = out[out.kind == "compound"]
    lines.append(f"Compound: {(c.outcome=='correct').sum()}/{len(c)} flagged as multi-issue")
    fs = s[s.split_flagged]
    lines.append(f"False splits on single-issue rows: {len(fs)}/{len(s)}")
    lines.append("By language (single-owner, correct/n):")
    for lang, g in s.groupby("language"):
        lines.append(f"  {lang}: {(g.outcome=='correct').sum()}/{len(g)} "
                     f"(wrong {(g.outcome=='wrong').sum()}, abstained {(g.outcome=='abstained').sum()})")
    lines.append("SIMULATED / SYNTHETIC data. Small n: preliminary only.")
    return "\n".join(lines)


if __name__ == "__main__":
    o = run("test", save_failures=True)
    print(summary(o))
    print("\nFailures saved to docs/baseline_failures.csv")
