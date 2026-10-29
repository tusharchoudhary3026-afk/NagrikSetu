# Authentication implementation notes

## Built

- Extended the existing `core.auth` and `users`/SQLite authentication system. Public accounts keep the existing database role `public` (the citizen-facing role); a new parallel authentication system was not added.
- Public users can register by email and password, or by Indian mobile number and password after a simulated phone OTP. Phone values are normalized to unique `+91XXXXXXXXXX` values. Staff are email-only.
- Staff enrollment looks up an active, unregistered record in `staff_directory`. The display name, role, and department come from that server-side record. A six-digit email code must be verified before the account is created and the directory row is marked registered.
- Public signup rejects every address present in the staff directory. Staff role submissions are ignored; public signup cannot assign a staff role.
- Verification codes are stored as salted HMAC hashes and are single-use, expire after ten minutes, allow at most five guesses per issued code, and are request-limited in SQLite. Resending is limited to one request per 30 seconds and five requests per 15-minute window.
- Password scoring is in `core/password_policy.py`: 10-character minimum; at least three character classes or a 16-character four-word passphrase; 128-character maximum; personal-information, common-password, repeated-character, keyboard-sequence, and number-sequence checks. `data/common_passwords.txt` contains 200 curated common/guessable entries. The UI shows live scores and concrete suggestions. A `secrets`-based generator is available to callers.
- Passwords use bcrypt with a per-password salt when available, and scrypt otherwise (scrypt is also used for inputs that exceed bcrypt's byte limit). Existing PBKDF2 hashes remain verifiable. Passwords, OTPs, and codes are not inserted into persistent storage in plaintext.
- Failed login identifiers are HMAC-keyed before they enter the persistent lockout table. Five failures within 15 minutes lock that identifier for 15 minutes. The login screen uses the same `Invalid credentials` response for bad and unknown identifiers.
- Sessions refresh account identity and role from SQLite, expire after 30 minutes without activity, and are cleared at sign-out. Service/page permission checks reload the stored role. Staff complaint access also checks active staff-directory enrollment and approved geographic scope.
- `auth_events` contains hashed identifiers and append-only triggers. Registration, verification, login, lockout, sign-out, and role-denial outcomes are recorded without storing the submitted password or code.
- Schema changes are additive and idempotent. The checked-in `data/staff_directory.csv` has 24 fictional `@staff.nagriksetu-demo.example` rows, all tagged `SYNTHETIC`; `INSERT OR IGNORE` seeds missing rows without overwriting existing database entries or their registered flags.

## SIMULATED

- The staff directory is a **pseudo staff directory, simulated, not a real government directory**. It grants no real employment or government authority.
- In DEMO MODE (the default for this prototype), email verification codes and SMS OTPs are displayed on screen. The UI explicitly states `SIMULATED: no real email is sent` or `SIMULATED: no real SMS is sent`. No delivery network call is made.
- Geographic options and area workflows remain prototype data. An approved area is still required for staff case access; the directory itself does not grant complaint jurisdiction.
- The default demo HMAC secret is a development-only constant. The app visibly labels DEMO MODE. It must not be reused for deployment.

## ROADMAP / not production-ready

- Implement and configure real email and SMS providers behind `send_email_code()` and `send_sms_otp()`; until then, both registration verification routes fail closed when DEMO MODE is disabled.
- Add multi-factor authentication, password reset by verified email/phone, credential changes, verified government identity, and operational staff-directory administration.
- Configure and independently verify HTTPS, encrypted database storage, production secret handling/rotation, secure backup/retention, and a production identity review. No application-level SQLite encryption or deployment TLS guarantee is claimed.
- The 200-entry blocklist is a curated defensive list, not a ranked or independently sourced top-200 corpus. Password-strength scoring is a prototype heuristic, not a breach-password service.
- SQLite's existing `users.email` column is `NOT NULL`. To preserve that table and all existing foreign-key relationships without rebuilding it, phone-only accounts receive an internal deterministic `@phone.nagriksetu.invalid` placeholder email. This placeholder is not shown as a contact address and cannot be used as a staff identity. Making email nullable is a separately governed table rebuild.
- Existing users and legacy username rows are not rewritten. Existing staff-role rows that do not match an active, registered directory entry remain preserved but cannot authenticate into the current staff interface. The old stored role name `public` is retained as the citizen role because current pages and APIs already depend on it.
- The previous prototype's optional Google sign-in remains limited to public accounts originally registered with that provider. Staff must authenticate with email and password.

## Database backup and migration

The valid immediate pre-migration SQLite online backup is `db/nyayaflow-pre-auth-hardening-20261029.db`. It and the migrated live database pass `PRAGMA integrity_check`; row counts for users, complaints, ledger, challenges, and corrections match across both snapshots. The current database backup is `db/backups/nyayaflow-auth-hardening-post-migration-20261029.db`. A zero-byte duplicate backup file under `db/backups/` was not used. The directory seed uses insert-only behavior.

## Local commands

Run from the repository root in the VS Code PowerShell terminal (Python 3.12):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Run the unit, integration, and Streamlit AppTest suite:

```powershell
python -m pytest -q
```

Run the acceptance scenarios separately:

```powershell
python -m scripts.run_acceptance
```

For a non-demo configuration, set `NAGRIKSETU_DEMO_MODE=0` and provide `NAGRIKSETU_AUTH_SECRET` using the hosting environment's secret manager. Do not commit that secret. Real code delivery is still ROADMAP and will be unavailable until a provider is implemented.
