-- NagrikSetu schema. All demo data is SYNTHETIC.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS complaints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,              -- shared by parent + sub-issues
    parent_id       INTEGER REFERENCES complaints(id),  -- NULL for the original complaint
    original_text   TEXT NOT NULL,              -- NEVER modified
    language        TEXT NOT NULL,              -- english | hindi | hinglish | uncertain
    normalized_text TEXT,                       -- separate field, Hinglish normalisation
    channel         TEXT DEFAULT 'portal',      -- portal | phone | social | in-person
    location        TEXT DEFAULT 'unknown',     -- never invented
    issue           TEXT,
    requested_action TEXT,
    missing_fields  TEXT,                       -- comma-separated
    is_synthetic    INTEGER NOT NULL DEFAULT 1,
    is_active       INTEGER NOT NULL DEFAULT 1,
    submitted_by    INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suggestions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id),
    method        TEXT NOT NULL,                -- baseline | tfidf_lr
    top3          TEXT NOT NULL,                -- JSON: [{dept, score}]
    evidence      TEXT,                         -- JSON: matched words / rules
    confidence    REAL,
    abstained     INTEGER NOT NULL DEFAULT 0,   -- 1 = manual queue
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only decision ledger (see triggers below)
CREATE TABLE IF NOT EXISTS ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id    INTEGER NOT NULL REFERENCES complaints(id),
    event_type      TEXT NOT NULL,   -- suggested | accept | edit | clarify | escalate | challenge | challenge_resolved | transfer
    actor           TEXT NOT NULL,   -- system | operator | reviewer | citizen
    suggested_dept  TEXT,
    final_dept      TEXT,
    reason          TEXT,            -- mandatory on edit / escalate / transfer
    reason_code     TEXT,            -- wrong_category | missing_info | overlapping_ownership | duplicate_report | other
    details         TEXT,            -- JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TABLE IF NOT EXISTS challenges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id),
    raised_by     TEXT NOT NULL,             -- staff | citizen
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_by   TEXT,
    resolution    TEXT,
    outcome       TEXT,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    filename     TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    content_type TEXT NOT NULL,
    byte_size    INTEGER NOT NULL,
    is_encrypted INTEGER NOT NULL DEFAULT 1,
    original_name TEXT,
    mime          TEXT,
    size_bytes    INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Candidate decisions and incident memberships are separate so every decision
-- remains auditable while an explicit unlink can deactivate a prior membership.
CREATE TABLE IF NOT EXISTS duplicate_reviews (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id          INTEGER NOT NULL REFERENCES complaints(id),
    candidate_complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    decision              TEXT NOT NULL,
    actor                 TEXT NOT NULL,
    reason                TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS duplicate_reviews_no_update
BEFORE UPDATE ON duplicate_reviews
BEGIN SELECT RAISE(ABORT, 'duplicate review history is append-only'); END;

CREATE TRIGGER IF NOT EXISTS duplicate_reviews_no_delete
BEFORE DELETE ON duplicate_reviews
BEGIN SELECT RAISE(ABORT, 'duplicate review history is append-only'); END;

CREATE TABLE IF NOT EXISTS incident_links (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id          INTEGER NOT NULL REFERENCES complaints(id),
    candidate_complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    incident_id           TEXT NOT NULL,
    active                INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS incident_links_no_update
BEFORE UPDATE ON incident_links
BEGIN SELECT RAISE(ABORT, 'incident-link history is append-only'); END;

CREATE TRIGGER IF NOT EXISTS incident_links_no_delete
BEFORE DELETE ON incident_links
BEGIN SELECT RAISE(ABORT, 'incident-link history is append-only'); END;

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name            TEXT NOT NULL,
    password_hash   TEXT,
    auth_provider   TEXT NOT NULL CHECK(auth_provider IN ('password','google','legacy')),
    role            TEXT NOT NULL CHECK(role IN ('public','government','operator','reviewer','auditor')),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Old username-based records are retained intact here during the account migration.
CREATE TABLE IF NOT EXISTS legacy_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('operator','reviewer','auditor')),
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_attempts (
    email           TEXT PRIMARY KEY COLLATE NOCASE,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT
);

-- Corrections saved as labelled examples (NO automatic retraining)
CREATE TABLE IF NOT EXISTS corrections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    text         TEXT NOT NULL,
    wrong_dept   TEXT,
    correct_dept TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    suggested_dept TEXT,
    reason       TEXT,
    reason_code  TEXT,
    label_source TEXT NOT NULL DEFAULT 'reviewer_correction',
    is_verified  INTEGER NOT NULL DEFAULT 0,
    verified_by  TEXT
);

CREATE TABLE IF NOT EXISTS correction_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id INTEGER NOT NULL REFERENCES corrections(id),
    reviewer      TEXT NOT NULL,
    status        TEXT NOT NULL CHECK(status IN ('verified','rejected')),
    reason        TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS correction_reviews_no_update
BEFORE UPDATE ON correction_reviews
BEGIN SELECT RAISE(ABORT, 'correction review history is append-only'); END;

CREATE TRIGGER IF NOT EXISTS correction_reviews_no_delete
BEFORE DELETE ON correction_reviews
BEGIN SELECT RAISE(ABORT, 'correction review history is append-only'); END;
