from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("NYAYAFLOW_DB_PATH", ROOT / "db" / "nyayaflow.db")).expanduser()
SCHEMA_PATH = ROOT / "db" / "schema.sql"
RESP_TABLE = ROOT / "data" / "responsibility_table.csv"
KEYWORDS = ROOT / "data" / "keywords.csv"
COMPLAINTS = ROOT / "data" / "complaints.csv"
TEST_MANIFEST = ROOT / "data" / "test_split_manifest.json"
THRESHOLD_FILE = ROOT / "data" / "threshold.json"
SAFETY_TEST_CASES = ROOT / "data" / "safety_test_cases.csv"
GOV_ALLOWLIST = ROOT / "data" / "gov_allowlist.csv"

REASON_CODES = ["wrong_category", "missing_info", "overlapping_ownership", "duplicate_report", "other"]
REVIEW_ACTIONS = ["accept", "edit", "clarify", "escalate", "transfer"]
REASON_REQUIRED = {"edit", "escalate", "transfer", "duplicate_linked", "duplicate_unlinked"}

# Team sets this on a validation split (see scripts/evaluate.py). Placeholder only.
CONFIDENCE_THRESHOLD = 0.40

SIM_LABEL = "SIMULATED / SYNTHETIC DATA - not real municipal data"
