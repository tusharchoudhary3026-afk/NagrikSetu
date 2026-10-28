# NagrikSetu

NagrikSetu is a human-reviewed civic grievance routing prototype. Its demo records are synthetic and its department ownership rules are assumptions. It does not automatically reject, close, deprioritize, assign, or merge complaints.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:NYAYAFLOW_DB_PATH = "data/nyayaflow.db"
# Required for encrypted photo uploads; keep this stable and private.
$env:NYAYAFLOW_ATTACHMENT_KEY = "<stable-64-character-key-from-your-secrets-manager>"
python -m scripts.init_db
python -m streamlit run app.py
```

## Authentication and roles

The app supports email/password accounts and optional Google sign-in through Streamlit's native OIDC. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and replace the OAuth placeholders with a Google OAuth client. In Google Cloud Console, add `http://localhost:8501/oauth2callback` as an authorized redirect URI. Keep the real secrets file out of version control. Google sign-in stays hidden when the configuration is incomplete.

Start the server with `python -m streamlit run app.py`, then create a Public user account from the registration tab. Government registration is granted only to an address listed in `data/gov_allowlist.csv` or when the user supplies the matching invite code. The secrets value `GOV_INVITE_CODE` must contain a scrypt hash, not the invite phrase; generate one with `python -m scripts.hash_government_invite`, then copy the output into the secrets file. The allowlist contains two fictional `.invalid` addresses for demonstration. Add approved addresses as a CSV row under the `email` column. Existing username-based accounts are preserved as legacy records and must re-register with an email to use the new interface.

Passwords are salted hashes. Government and public pages are guarded server-side and the public complaint queries are scoped to the signed-in account. The UI shows a simulated-data banner and labels photos as stored only; the app does not analyze images.

Known limits: no email verification, password reset, or MFA; SQLite complaint and decision data is not encrypted at rest by the application; roles and authentication are prototype-level and have not received a security audit. Configure HTTPS at a trusted hosting layer before exposing the app beyond local development.

## Test

```powershell
python -m pytest tests -q
python scripts/run_acceptance.py
python scripts/evaluate.py
python scripts/retrain_offline.py
```

The frozen test split is grouped by complaint family. Evaluation fits TF-IDF on train, tunes its abstention threshold on validation, and reports both systems on the held-out test rows. The dataset is small, synthetic, and AI-labelled; scores are preliminary and do not establish real-world performance or fairness.

## Current workflow

- Multilingual typed intake preserves original text and stores normalized text separately. Unknown location or issue information prompts clarification.
- Rule-based routing returns evidence and abstains when it has no matching evidence. The TF-IDF router is an evaluation comparison, not a live replacement.
- Compound cases can be split only after a reviewer confirms the proposed sub-issues. Merge-back hides child views but preserves records and history.
- Reviewers accept, edit, clarify, escalate, transfer, raise or resolve challenges, and record structured reasons in an append-only event ledger.
- Duplicate candidates show text, location, time, missing-field, and conflict evidence. A reviewer must choose an outcome; linking and unlinking append history and preserve every original complaint.
- JPEG, PNG, and WEBP attachments are size/type-checked, metadata-stripped, encrypted at rest with AES-256-GCM, and available to government staff only. Set `NYAYAFLOW_ATTACHMENT_KEY` to 64 hex characters (32 bytes) before enabling photo uploads. Keep it in a secrets manager and retain a protected backup; losing it makes stored photos unreadable. No image analysis occurs.
- Before enabling uploads on a database with older photo attachments, back up the database and `data/attachments`, set the same stable key, then run `python scripts/migrate_attachment_encryption.py`. Legacy photos remain blocked from the UI until migrated.
- Speech-to-text is an optional browser trial on intake. Users must disclose and consent to browser speech recognition, review and edit the returned text, and explicitly confirm it before processing. Audio is not stored by NagrikSetu; browser providers may process it. Hindi-English mixed speech quality is unvalidated.
- A configurable safety rubric creates attention flags for human review; it is team-proposed and does not assign risk or priority.
- Its 12-case English/Hindi/Hinglish check set reports an explicit numerator and denominator, and is labelled a synthetic rubric sanity check rather than field recall.
- Reassignment and hotspot reports show time windows, observed counts, baselines, denominators, and synthetic-data labels. These counts do not establish fault.
- Reviewer corrections are saved with provenance. Only explicitly verified corrections are exposed to a future offline training experiment; nothing retrains or deploys automatically.
- A reviewer can run a guarded offline experiment once at least 10 verified corrections span at least two departments. It reuses the frozen test set, excludes near-matches to held-out text, and saves or deploys no model.

## Scope limits

Speech-to-text remains a trial feature; actual microphone and language-quality validation is still required. Existing photo files created before the encryption migration are marked legacy plaintext and cannot be viewed through the app; re-upload them using the secure intake flow. The SQLite complaint/decision database has no application-level encryption, and HTTPS, backups, retention, and production-grade identity infrastructure must be verified and configured for the deployment. No labelled duplicate-pair benchmark is included, so duplicate precision/recall are not reported. Do not put real or sensitive case data into this prototype.

See [data/DATASET_CARD.md](data/DATASET_CARD.md) for dataset provenance and limitations.
