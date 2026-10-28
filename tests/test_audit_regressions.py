import pandas as pd

from core.router_ml import fit_default


def test_full_dataframe_fit_uses_training_split_only():
    rows = pd.DataFrame([
        {"text": "road pothole", "owner_label": "Roads Dept", "split": "train"},
        {"text": "blocked drain", "owner_label": "Water Dept", "split": "train"},
        {"text": "held out validation phrase", "owner_label": "Validation Only", "split": "val"},
        {"text": "held out test phrase", "owner_label": "Test Only", "split": "test"},
    ])

    router = fit_default(rows)

    assert set(router.clf.classes_) == {"Roads Dept", "Water Dept"}


def test_duplicate_pair_metrics_are_reported_from_frozen_test_pairs():
    from scripts.evaluate_duplicates import evaluate_duplicate_pairs

    report = evaluate_duplicate_pairs()

    assert report["dataset_pairs"] == 40
    assert report["dev_pairs"] == 20
    assert report["test_pairs"] == 20
    assert report["threshold_source"] == "dev"
    assert report["test"]["precision_denominator"] > 0
    assert report["test"]["recall_denominator"] == 10
    assert 0 <= report["test"]["false_positives"] <= report["test"]["negative_denominator"]


def test_full_evaluation_has_a_configured_threshold_artifact_path():
    from core.config import THRESHOLD_FILE

    assert THRESHOLD_FILE.name == "threshold.json"


def test_full_evaluation_executes_against_the_frozen_test_split():
    from scripts.evaluate_full import evaluate

    report = evaluate("test")

    assert report["split"] == "test"
    assert report["tfidf"]["n_single"] > 0
    assert report["threshold_source"] == "validation"
