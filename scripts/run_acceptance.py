import sys, pathlib, datetime, json, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent


class Collect:
    def __init__(self): self.rows = []
    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.skipped):
            self.rows.append((report.nodeid.split("::")[-1], report.outcome.upper()))


c = Collect()
suite_code = pytest.main([str(ROOT / "tests"), "-q", "-p", "no:cacheprovider"], plugins=[c])
lines = [f"# Acceptance test run {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
         "| Test | Outcome |", "|---|---|"] + [f"| {n} | {o} |" for n, o in c.rows]
(ROOT / "tests" / "results.md").write_text("\n".join(lines), encoding="utf-8")
from core.evaluator import run_all_acceptance_tests

acceptance = run_all_acceptance_tests()
for row in acceptance:
    row["status"] = "PASS" if row["status"] == "PASS" else "FAIL"
(ROOT / "docs" / "acceptance_results.json").write_text(
    json.dumps({"run_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "label": "SIMULATED / SYNTHETIC acceptance scenarios", "results": acceptance},
               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
acceptance_lines = ["", "## AT-01 to AT-06 (SIMULATED / SYNTHETIC)", ""] + [
    f"- [{row['status']}] {row['id']}: {row['scenario']} — {row['details']}" for row in acceptance]
print("\n".join(lines + acceptance_lines))
if suite_code != pytest.ExitCode.OK or any(row["status"] != "PASS" for row in acceptance):
    raise SystemExit(1)
