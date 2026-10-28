"""Offline-only model experiment using verified correction examples; never deploys a model."""
import pandas as pd

from core.config import COMPLAINTS
from core.corrections import load_verified_corrections
from core.db import init_db
from core.engine8_harness import _evaluate_router
from core.router_baseline import load_keywords, route as baseline_route
from core.router_ml import TfidfRouter, choose_threshold, single_owner_rows
from core.verify_split import verify_frozen_test_split, verify_split_leakage


def _tokens(text):
    return {token for token in str(text).casefold().split() if len(token) > 2}


def run_offline_retraining_experiment(min_verified: int = 10):
    """Return a comparison only when enough reviewed examples exist; persist no model or metrics."""
    if min_verified < 1:
        raise ValueError("At least one verified example is required.")
    init_db()
    leakage, frozen = verify_split_leakage(), verify_frozen_test_split()
    if not leakage["passed"] or not frozen["passed"]:
        raise ValueError(f"Experiment stopped: grouped/frozen test guard failed. {leakage}; {frozen}")
    data = pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    train = single_owner_rows(data[data["split"] == "train"])
    validation = single_owner_rows(data[data["split"] == "val"])
    test = single_owner_rows(data[data["split"] == "test"])
    verified = pd.DataFrame(load_verified_corrections())
    if verified.empty:
        verified = pd.DataFrame(columns=["text", "correct_dept"])
    verified = verified.dropna(subset=["text", "correct_dept"])

    test_sets = [_tokens(text) for text in test["text"]]
    clean_rows = []
    conflicts = set()
    labels_by_text = {}
    for row in verified.to_dict("records"):
        key = " ".join(str(row["text"]).casefold().split())
        label = str(row["correct_dept"]).strip()
        if key in labels_by_text and labels_by_text[key] != label:
            conflicts.add(key)
        labels_by_text[key] = label
        words = _tokens(row["text"])
        if words and any(len(words & candidate) / max(1, len(words | candidate)) >= 0.8 for candidate in test_sets):
            continue
        clean_rows.append({"text": row["text"], "owner_label": label})
    clean_rows = [row for row in clean_rows
                  if " ".join(str(row["text"]).casefold().split()) not in conflicts]
    verified_clean = pd.DataFrame(clean_rows, columns=["text", "owner_label"])
    departments = set(verified_clean["owner_label"]) if not verified_clean.empty else set()
    if len(verified_clean) < min_verified or len(departments) < 2:
        return {"status": "insufficient_verified_examples", "verified_examples": len(verified_clean),
                "minimum_required": min_verified, "departments": sorted(departments),
                "excluded_conflicting_labels": len(conflicts), "model_saved": False, "deployed": False}

    augmented = pd.concat([train[["text", "owner_label"]], verified_clean], ignore_index=True)
    candidate = TfidfRouter().fit(augmented["text"], augmented["owner_label"])
    threshold, curve = choose_threshold(candidate, validation)
    keywords = load_keywords()
    baseline = _evaluate_router("baseline", test, lambda text: baseline_route(text, keywords))
    proposed = _evaluate_router("verified-correction-tfidf", test,
                                lambda text: candidate.route(text, threshold))
    return {"status": "experiment_completed", "verified_examples": len(verified_clean),
            "departments": sorted(departments), "excluded_conflicting_labels": len(conflicts),
            "threshold": threshold, "validation_curve": curve,
            "baseline": baseline, "candidate": proposed,
            "test_manifest": frozen["sha256"], "model_saved": False, "deployed": False}
