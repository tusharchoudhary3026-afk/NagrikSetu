# Test and evaluation report

Run date: 2026-10-28. All model/evaluation datasets are synthetic. Commands ran with Python 3.12 from the repository virtual environment and temporary pytest databases. The configured SQLite database was backed up before both additive migrations.

## Automated verification

The complete unit/integration and headless Streamlit page suite passed: **79 passed** (including every Streamlit page booted with an allowed session). The workflow acceptance scenarios AT-01 through AT-06 are run by `python -m scripts.run_acceptance` and saved to `docs/acceptance_results.json` with actual status/details.

Database invariants tested: ledger UPDATE/DELETE triggers reject mutation; automatic close/reject/deprioritize/merge attempts fail without state change; duplicate decisions require structured reason codes; the older duplicate-review schema migrates idempotently; role-based denials and photo access controls are exercised using temporary databases.

Geographic tests also verified cascading sample options, unknown/partial location handling, pending requests having no complaint visibility, approval by a configured active geography administrator, area-scoped case lists, denial of cross-area review and attachments, denial of forged/inactive staff identities, resident challenge ownership, and append-only geographic access history.

### Authentication hardening verification (2026-10-29)

After adding the authentication changes, a direct `python -m pytest -q` run completed with **130 passed**. The separate `python -m scripts.run_acceptance` command completed its suite with **127 passed** and all six synthetic acceptance scenarios AT-01 through AT-06 passing. The suites cover headless page startup checks for an unauthenticated visitor and each staff role, staff registration from the synthetic directory, email/mobile OTP flows, password-policy checks, lockouts, role reload/session expiry, append-only auth events, and scoped service access. A focused run of the auth and affected workflow/page suites passed **61 tests**. `python -m compileall -q app.py core pages scripts tests` and `git diff --check` also succeeded.

The AT-04 reviewer-override acceptance path now signs in a synthetic reviewer and passes that authenticated account into the scoped review service. Delivery codes remain simulated in demo mode; these tests do not verify a real email or SMS provider.

### Government staff dashboard verification (2026-10-29)

The final direct `python -m pytest -q` run after the dashboard changes completed with **142 passed**. The separate `python -m scripts.run_acceptance` run completed with **139 passed**, and AT-01 through AT-06 all passed. New dashboard coverage verifies department and geography isolation, stale/forged department rejection, operator/reviewer/auditor/public access, the post-login staff landing page, reasoned dispatch/clarification/resolution/transfer events, append-only history, transfer bounce warnings, SLA calculations, scoped hotspot summaries, ownership warnings, department-filtered duplicate candidates, and case timelines. `python -m compileall -q app.py core pages scripts tests` and `git diff --check` succeeded.

No schema migration was needed for dashboard actions: status transitions and handoffs are derived from the existing append-only ledger and challenge rows. The default seven-day SLA is configurable with `NAGRIKSETU_DEMO_SLA_DAYS` and is labeled as a demo assumption.

## Frozen complaint-routing evaluation

Command: `python -m scripts.evaluate` and `python -m scripts.evaluate_full`.

| Method | Single-owner correct / n | Answered | Correct among answered | Abstained | Notes |
|---|---:|---:|---:|---:|---|
| Keyword baseline | 6/21 | 10 | 6/10 | 11/21 | 95% Wilson CI for overall correctness: 0.14–0.50 |
| TF-IDF | 0/21 | 0 | n/a (0/0) | 21/21 | Validation did not meet minimum coverage; threshold is null and all test rows abstain |

Per-language baseline correctness: English 2/7, Hindi 2/7, Hinglish 2/7. TF-IDF: 0/7 for each language, all abstained. The test contains 27 total rows; 3/3 unclear cases abstained, 3/3 compound cases were flagged, and false splits were 0/21. Ownership overlap flags were 1/6; all 8/8 responsibility rules remain unverified assumptions. The test labels were AI-written and AI-checked, not independently human-labelled.

## Duplicate-pair evaluation

Command: `python -m scripts.evaluate_duplicates --tune` (dev split only), then `python -m scripts.evaluate_duplicates` (frozen test split). There are 40 labelled pairs: 20 dev and 20 test, 40 unique groups, zero group leakage. The test manifest hash is verified before scoring. Pair labels are synthetic and AI-authored/AI-reviewed, not independent human ground truth.

The dev-only selected threshold is **0.8375**. On dev it yielded precision **1/1**, recall **1/10**, and 0 false positives among 10 negative pairs. On the frozen test set the threshold predicted no positive pairs: precision is undefined (0 predictions), recall **0/10**, false positives **0/10**, and accuracy **10/20**. The zero-recall result is weak and should not be interpreted as useful duplicate detection. The test set was not used to change the threshold.

## Safety rubric sanity check

Command: `core.safety.evaluate_safety_rubric()` on the checked-in 12 synthetic rows. Recall was **10/10 positive cases**, false positives **0/2 negative cases**. Language positives: English 4/4, Hindi 4/4, Hinglish 2/2. These examples were written to exercise the rubric; this is not real-world safety recall.

## Environment and limits

- `python -m scripts.security_status` reports photo encryption disabled unless a key is configured, TLS unverified unless certificate/key settings exist, and SQLite at-rest encryption not configured by the application.
- The SQLite backup created before the duplicate reason-code migration is `db/backups/nyayaflow-pre-duplicate-reason-code-20261028.db`.
- Before adding geographic complaint columns and access events, an SQLite online backup was created at `db/backups/nyayaflow-pre-geographic-scope-20261028.db`. The migration was run twice; it added six nullable complaint location columns and the access-history table while preserving all pre-migration table row counts. Existing records were not auto-assigned to areas.
- A headless AppTest initially exercised the app outside the fixture's Python-module patch. The fixture now passes a temporary path through `NYAYAFLOW_DB_PATH`; the final full run passed with isolation in place. Read-only row-count comparisons against backups confirmed that complaint, ledger, user, challenge, and correction data were preserved.
- Browser speech recognition quality, real staff/citizen usability, municipal ownership rules, real-world model performance, deployment TLS, encrypted SQLite, a cryptographic ledger, and verified-correction retraining were not established by these tests.
- Geographic choices are sample prototype options from `data/geo_coverage.json`; municipal area boundaries are not authoritative. Administrator emails must be configured securely before staff area requests can be approved.
- No commits were created: the execution environment exposes `.git` as read-only. The working-tree edits and this report remain in the project folder for review.
- The valid immediate pre-auth SQLite online backup is `db/nyayaflow-pre-auth-hardening-20261029.db`; an empty duplicate file under `db/backups/` was not used. Both the pre-auth snapshot and migrated database pass `PRAGMA integrity_check`. Their existing `users`, `complaints`, `ledger`, `challenges`, and `corrections` row counts match (5, 7, 22, 2, and 2). The migrated database adds four tables. A post-migration online backup is also available at `db/backups/nyayaflow-auth-hardening-post-migration-20261029.db` and matches those core counts.
