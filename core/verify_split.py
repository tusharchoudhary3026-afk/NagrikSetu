"""Leakage and frozen test-set guards for grouped evaluation splits."""
import hashlib
import json
import pandas as pd

from core.config import COMPLAINTS, TEST_MANIFEST


def verify_split_leakage(df=None):
    data = df if df is not None else pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    missing = sorted({"family", "split"} - set(data.columns))
    if missing:
        return {"passed": False, "reason": f"Dataset missing required columns: {', '.join(missing)}",
                "rows": len(data), "families": 0, "leaked_families": []}
    split_counts = data.groupby("family", dropna=False)["split"].nunique()
    leaked = sorted(str(family) for family in split_counts[split_counts > 1].index)
    allowed = {"train", "val", "test"}
    unknown_splits = sorted(str(item) for item in set(data["split"].dropna()) - allowed)
    missing_values = bool(data["family"].isna().any() or data["split"].isna().any())
    passed = not leaked and not unknown_splits and not missing_values
    return {"passed": passed, "reason": "ok" if passed else "Grouped split integrity check failed",
            "rows": len(data), "families": int(data["family"].nunique()),
            "leaked_families": leaked, "unknown_splits": unknown_splits,
            "missing_group_or_split": missing_values}


def verify_frozen_test_split(df=None):
    data = df if df is not None else pd.read_csv(COMPLAINTS, encoding="utf-8-sig", dtype=str)
    data = data.fillna("")
    if not {"id", "split", "family"}.issubset(data.columns):
        return {"passed": False, "reason": "Dataset is missing frozen-test columns."}
    manifest = json.loads(TEST_MANIFEST.read_text(encoding="utf-8"))
    test_rows = data[data["split"] == "test"].sort_values("id")
    payload = json.dumps(test_rows.to_dict("records"), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    families = sorted(test_rows["family"].unique().tolist())
    passed = (len(test_rows) == manifest["rows"] and digest == manifest["sha256"]
              and families == manifest["families"])
    return {"passed": passed, "reason": "ok" if passed else "Frozen test set differs from its manifest.",
            "rows": len(test_rows), "sha256": digest, "families": families,
            "frozen_on": manifest["frozen_on"]}


if __name__ == "__main__":
    result = verify_split_leakage()
    print(result)
    if not result["passed"]:
        raise SystemExit(1)
