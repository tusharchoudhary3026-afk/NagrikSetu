"""Configurable high-consequence keyword flags; flags only request human attention."""
import json
import re
import csv

from .config import ROOT, SAFETY_TEST_CASES, SIM_LABEL

RUBRIC_PATH = ROOT / "data" / "safety_rules.json"


def load_rubric():
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    if not isinstance(rubric.get("rules"), list):
        raise ValueError("Safety rubric must define a list of rules.")
    return rubric


def flag_safety(text: str):
    normalized = (text or "").casefold()
    flags = []
    for rule in load_rubric()["rules"]:
        matched = []
        for term in rule.get("terms", []):
            for occurrence in re.finditer(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", normalized):
                prefix = normalized[max(0, occurrence.start() - 40):occurrence.start()]
                if re.search(r"(?:\bno\b|\bnot\b|\bwithout\b|\bnahi\b|\bnahin\b|नहीं)(?:\s+\w+){0,2}\s*$", prefix):
                    continue
                matched.append(term)
                break
        if matched:
            flags.append({"rule_id": rule["id"], "label": rule["label"],
                          "matched_text": matched, "status": "HUMAN_REVIEW_REQUIRED"})
    return {"flagged": bool(flags), "flags": flags,
            "rubric_status": load_rubric().get("status", "TEAM-PROPOSED"),
            "message": "Safety flag is a request for human attention, not a risk or priority decision."}


def evaluate_safety_rubric():
    """Measure only the included synthetic rubric checks; this is not field performance."""
    with SAFETY_TEST_CASES.open("r", encoding="utf-8-sig", newline="") as stream:
        cases = list(csv.DictReader(stream))
    if not cases:
        raise ValueError("Safety test set is empty.")
    tp = fp = tn = fn = 0
    by_language = {}
    for case in cases:
        expected = case["expected_flag"] == "1"
        predicted = flag_safety(case["text"])["flagged"]
        tp += int(expected and predicted)
        fn += int(expected and not predicted)
        fp += int(not expected and predicted)
        tn += int(not expected and not predicted)
        row = by_language.setdefault(case["language"], {"n": 0, "expected_positive": 0, "true_positive": 0})
        row["n"] += 1
        row["expected_positive"] += int(expected)
        row["true_positive"] += int(expected and predicted)
    positive = tp + fn
    return {"status_label": "SYNTHETIC RUBRIC SANITY CHECK",
            "total": len(cases), "true_positive": tp, "positive_denominator": positive,
            "recall": tp / positive if positive else None,
            "false_positive": fp, "negative_denominator": fp + tn,
            "true_negative": tn, "by_language": by_language,
            "limitation": "Cases are synthetic and term-aligned to the team-proposed rubric; this is not real-world safety recall."}
