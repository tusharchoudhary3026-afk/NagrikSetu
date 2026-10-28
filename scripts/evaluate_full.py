"""Engine 5: baseline vs TF-IDF on the SAME split, language gap with Wilson CIs, splitter and
ownership checks, coverage-vs-accuracy. Run:  python -m scripts.evaluate_full
Writes data/threshold.json (threshold chosen on the validation split only)."""
import json, math
import pandas as pd
from core import router_baseline, splitter, router_ml, ownership
from core.config import COMPLAINTS, THRESHOLD_FILE


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 2), round(c + h, 2))


def _row(method, df, fn):
    s = router_ml.single_owner_rows(df)
    res = [(fn(t), y, l) for t, y, l in zip(s["text"], s["owner_label"], s["language"])]
    out = {"method": method, "n_single": len(s)}
    ans = [(r, y, l) for r, y, l in res if not r["abstained"]]
    out["answered"] = len(ans)
    out["correct_answered"] = sum(r["top3"][0]["dept"] == y for r, y, _ in ans)
    out["correct_overall"] = out["correct_answered"]
    out["ci_overall"] = wilson(out["correct_overall"], len(s))
    out["by_language"] = {}
    for lang in ["english", "hinglish", "hindi"]:
        sub = [(r, y) for r, y, l in res if l == lang]
        a = [(r, y) for r, y in sub if not r["abstained"]]
        k = sum(r["top3"][0]["dept"] == y for r, y in a)
        out["by_language"][lang] = {"correct": k, "n": len(sub), "abstained": len(sub) - len(a),
                                    "ci": wilson(k, len(sub))}
    v = df[df["owner_label"] == "UNCLEAR"]
    out["unclear_abstained"] = (sum(fn(t)["abstained"] for t in v["text"]), len(v))
    return out


def evaluate(split="test"):
    df = pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    tr, va, te = df[df.split == "train"], df[df.split == "val"], df[df.split == split]
    kw = router_baseline.load_keywords()
    ml = router_ml.fit_default(tr)
    th, curve = router_ml.choose_threshold(ml, va)
    threshold_met = any(row["coverage"] >= 0.25 and row["answered"] for row in curve)
    res = {"split": split, "n_rows": len(te), "tfidf_threshold": th,
           "threshold_met_target": threshold_met, "threshold_source": "validation" if threshold_met else None,
           "curve": curve,
           "baseline": _row("baseline", te, lambda t: router_baseline.route(t, kw)),
           "tfidf": _row("tfidf", te, lambda t: ml.route(t, th))}
    # Splitter (Engine 2): missed and false splits
    multi = te[te.owner_label == "MULTI"]
    single = router_ml.single_owner_rows(te)
    res["splitter"] = {"flagged_compound": (sum(splitter.propose_split(t)["is_compound"] for t in multi.text), len(multi)),
                       "false_splits": (sum(splitter.propose_split(t)["is_compound"] for t in single.text), len(single))}
    # Ownership checker (Engine 6): overlap rows flagged when the suggested dept has a documented overlap
    ov = single[single.has_overlap == 1]
    flagged = 0
    for t in ov.text:
        r = kw and router_baseline.route(t, kw)
        if r["top3"] and ownership.check_suggestions([x["dept"] for x in r["top3"]], t):
            flagged += 1
    res["ownership_overlap_flagged"] = (flagged, len(ov))
    res["assumption_rules"] = (len(ownership.unverified_rows()), len(ownership.load_table()))
    return res


def report(r):
    L = [f"Split: {r['split']} (rows={r['n_rows']})  SIMULATED / SYNTHETIC, small n, preliminary"]
    for m in ("baseline", "tfidf"):
        x = r[m]
        L.append(f"{m}: correct {x['correct_overall']}/{x['n_single']} (95% CI {x['ci_overall']}); "
                 f"answered {x['answered']}; correct when answered {x['correct_answered']}/{x['answered']}; "
                 f"unclear abstained {x['unclear_abstained'][0]}/{x['unclear_abstained'][1]}")
        for lang, v in x["by_language"].items():
            L.append(f"   {lang}: {v['correct']}/{v['n']} correct, {v['abstained']} abstained, CI {v['ci']}")
    s = r["splitter"]
    L.append(f"splitter: compound flagged {s['flagged_compound'][0]}/{s['flagged_compound'][1]}; "
             f"false splits {s['false_splits'][0]}/{s['false_splits'][1]}")
    L.append(f"ownership: overlap cases flagged {r['ownership_overlap_flagged'][0]}/{r['ownership_overlap_flagged'][1]}; "
             f"rules still ASSUMPTION {r['assumption_rules'][0]}/{r['assumption_rules'][1]}")
    if r["tfidf_threshold"] is None:
        L.append("tfidf threshold not selected: validation did not meet minimum coverage; all test predictions abstain")
    else:
        L.append(f"tfidf threshold {r['tfidf_threshold']} (chosen on validation; target met: {r['threshold_met_target']})")
    L.append("Labels are AI-written and AI-checked: not independent human labelling.")
    return "\n".join(L)


if __name__ == "__main__":
    r = evaluate("test")
    THRESHOLD_FILE.write_text(json.dumps({"tfidf": r["tfidf_threshold"], "source": r["threshold_source"],
                                          "validation_target_met": r["threshold_met_target"]}, indent=2) + "\n")
    print(report(r))
