import json
import sqlite3
from .config import DB_PATH, SCHEMA_PATH


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    try:
        # Preserve pre-email accounts intact. They must re-register by email to use
        # the new interfaces; old staff roles are never silently promoted.
        tables = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "users" in tables:
            user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            if "email" not in user_columns:
                if "legacy_users" in tables:
                    raise RuntimeError("Both legacy and old users tables exist; refusing ambiguous migration.")
                conn.execute("ALTER TABLE users RENAME TO legacy_users")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "active" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        complaint_columns = {row["name"] for row in conn.execute("PRAGMA table_info(complaints)")}
        if "is_active" not in complaint_columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "submitted_by" not in complaint_columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN submitted_by INTEGER REFERENCES users(id)")
        attachment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(attachments)")}
        if "is_encrypted" not in attachment_columns:
            # Existing attachment rows are plaintext and must not be mistaken for encrypted files.
            conn.execute("ALTER TABLE attachments ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0")
        for name, declaration in {"original_name": "TEXT", "mime": "TEXT", "size_bytes": "INTEGER"}.items():
            if name not in attachment_columns:
                conn.execute(f"ALTER TABLE attachments ADD COLUMN {name} {declaration}")
        conn.execute("UPDATE attachments SET original_name=filename WHERE original_name IS NULL")
        conn.execute("UPDATE attachments SET mime=content_type WHERE mime IS NULL")
        conn.execute("UPDATE attachments SET size_bytes=byte_size WHERE size_bytes IS NULL")
        # Additive migration for databases created by earlier prototype versions.
        challenge_columns = {row["name"] for row in conn.execute("PRAGMA table_info(challenges)")}
        for name, declaration in {
            "resolved_by": "TEXT", "resolution": "TEXT", "outcome": "TEXT", "resolved_at": "TEXT"
        }.items():
            if name not in challenge_columns:
                conn.execute(f"ALTER TABLE challenges ADD COLUMN {name} {declaration}")
        correction_columns = {row["name"] for row in conn.execute("PRAGMA table_info(corrections)")}
        for name, declaration in {
            "suggested_dept": "TEXT", "reason": "TEXT", "reason_code": "TEXT",
            "label_source": "TEXT NOT NULL DEFAULT 'reviewer_correction'",
            "is_verified": "INTEGER NOT NULL DEFAULT 0", "verified_by": "TEXT"
        }.items():
            if name not in correction_columns:
                conn.execute(f"ALTER TABLE corrections ADD COLUMN {name} {declaration}")
        conn.commit()
    finally:
        conn.close()


def insert_complaint(rec: dict, submitted_by: int | None = None) -> int:
    cols = ["case_id", "parent_id", "original_text", "language", "normalized_text",
            "channel", "location", "issue", "requested_action", "missing_fields", "is_synthetic", "submitted_by"]
    vals = [rec.get(k) for k in cols]
    vals[-1] = submitted_by if submitted_by is not None else rec.get("submitted_by")
    conn = get_conn()
    try:
        cur = conn.execute(
            f"INSERT INTO complaints ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_suggestion(complaint_id, method, top3, evidence, confidence, abstained):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO suggestions (complaint_id, method, top3, evidence, confidence, abstained) "
            "VALUES (?,?,?,?,?,?)",
            (complaint_id, method, json.dumps(top3), json.dumps(evidence), confidence, int(abstained)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql, params=()):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
