"""Email/OIDC authentication, server-side roles, and legacy-account preservation."""
import csv
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import bcrypt
except ImportError:  # PBKDF2 fallback keeps local setup usable before optional bcrypt install.
    bcrypt = None

from .config import GOV_ALLOWLIST
from .db import fetch_all, get_conn, init_db

ROLES = {
    "public": {"can_intake": True, "can_view_attachments": False, "can_view_security": False},
    "government": {"can_intake": True, "can_review": True, "can_audit": True,
                   "can_view_attachments": True, "can_manage_users": True, "can_view_security": True},
    # Retained only for compatibility utilities and archived accounts. These roles
    # cannot access the new interfaces through require_role().
    "operator": {"can_intake": True, "can_review": False, "can_audit": False,
                 "can_view_attachments": False, "can_manage_users": False},
    "reviewer": {"can_intake": True, "can_review": True, "can_audit": True,
                 "can_view_attachments": True, "can_manage_users": True},
    "auditor": {"can_intake": False, "can_review": False, "can_audit": True,
                "can_view_attachments": False, "can_manage_users": False},
}
_EMAIL = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
_PBKDF2_ITERATIONS = 310_000
_LOCK_ATTEMPTS = 5
_LOCK_MINUTES = 5
_OLD_ROLES = {"operator", "reviewer", "auditor"}


class LoginLockedError(ValueError):
    """Raised when an email address is temporarily locked after failed logins."""


def normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if len(normalized) > 254 or not _EMAIL.fullmatch(normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    raw = password.encode("utf-8")
    if bcrypt is not None and len(raw) <= 72:
        return "bcrypt$" + bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw, salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not isinstance(password, str) or not encoded:
        return False
    try:
        if encoded.startswith("bcrypt$") and bcrypt is not None:
            return bcrypt.checkpw(password.encode("utf-8"), encoded[7:].encode("ascii"))
        algorithm, iterations, salt_hex, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


# Compatibility names retained for the existing service tests and archived scripts.
def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        return hash_password(password)
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    return verify_password(password, encoded)


def verify_permission(role: str, action: str) -> bool:
    role_perms = ROLES.get((role or "").lower())
    return bool(role_perms and role_perms.get(action, False))


def enforce_rbac(role: str, action: str):
    if not verify_permission(role, action):
        raise PermissionError(f"Access denied: role '{role}' is not authorized for '{action}'.")


def role_allowed(user: dict | None, required_role: str) -> bool:
    return bool(user and user.get("role") == required_role)


def require_login() -> dict:
    """Guard direct page URLs and refresh the authenticated account from storage."""
    import streamlit as st

    init_db()
    cached = st.session_state.get("authenticated_user")
    active = get_active_user(cached.get("id")) if isinstance(cached, dict) and cached.get("id") else None
    if not active:
        st.session_state.pop("authenticated_user", None)
        st.info("Sign in to open this page.")
        st.page_link("pages/0_Home.py", label="Go to sign in", icon="🔐")
        st.stop()
    st.session_state["authenticated_user"] = active
    from .ui import render_userbar
    render_userbar(active)
    return active


def require_role(required_role: str) -> dict:
    import streamlit as st

    user = require_login()
    if not role_allowed(user, required_role):
        st.warning(f"This page is for {required_role} users. Your account is {user['role']}.")
        st.page_link("pages/0_Home.py", label="Return to your interface", icon="🏠")
        st.stop()
    return user


def require_permission(action: str) -> dict:
    """Compatibility guard: permissions are always derived from the stored role."""
    user = require_login()
    try:
        enforce_rbac(user.get("role"), action)
    except PermissionError as exc:
        import streamlit as st
        st.error(str(exc))
        st.stop()
    return user


def government_allowlisted(email: str) -> bool:
    normalized = normalize_email(email)
    try:
        with Path(GOV_ALLOWLIST).open("r", encoding="utf-8-sig", newline="") as stream:
            return any(normalize_email(row.get("email", "")) == normalized for row in csv.DictReader(stream))
    except FileNotFoundError:
        return False


def hash_government_invite(code: str, salt: bytes | None = None) -> str:
    if not (code or "").strip():
        raise ValueError("Invite code cannot be empty.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(code.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_government_invite(code: str, encoded: str | None) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected = (encoded or "").split("$")
        if algorithm != "scrypt" or int(n) != 16384 or int(r) != 8 or int(p) != 1:
            return False
        digest = hashlib.scrypt((code or "").encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest.hex(), expected)
    except (TypeError, ValueError, OverflowError):
        return False


def register_user(email: str, name: str, password: str | None, *,
                  password_confirm: str | None = None, requested_role: str = "public",
                  invite_code: str = "", auth_provider: str = "password") -> dict:
    email = validate_email(email)
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Enter your name (up to 120 characters).")
    if requested_role not in {"public", "government"}:
        raise ValueError("Choose Public user or Government user.")
    if auth_provider not in {"password", "google"}:
        raise ValueError("Unsupported sign-in provider.")
    if auth_provider == "password":
        if password != password_confirm:
            raise ValueError("Passwords do not match.")
        encoded_password = hash_password(password or "")
    else:
        if password is not None:
            raise ValueError("Google accounts do not store a local password.")
        encoded_password = None

    role = "public"
    access_verified = False
    if requested_role == "government":
        try:
            import streamlit as st
            configured_hash = st.secrets.get("GOV_INVITE_CODE", "")
        except Exception:
            configured_hash = ""
        access_verified = government_allowlisted(email) or verify_government_invite(invite_code, configured_hash)
        if access_verified:
            role = "government"

    conn = get_conn()
    try:
        conn.execute("INSERT INTO users (email,name,password_hash,auth_provider,role) VALUES (?,?,?,?,?)",
                     (email, name, encoded_password, auth_provider, role))
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("An account with this email already exists. Sign in instead.") from exc
    finally:
        conn.close()
    return {"id": user_id, "email": email, "name": name, "role": role,
            "auth_provider": auth_provider, "government_access_verified": access_verified}


def get_user_by_email(email: str) -> dict | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    rows = fetch_all("SELECT id,email,name,auth_provider,role FROM users "
                     "WHERE email=? AND auth_provider<>'legacy'", (normalized,))
    return rows[0] if rows else None


def authenticate_email(email: str, password: str) -> dict | None:
    email = validate_email(email)
    now = datetime.now(timezone.utc)
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        attempt = conn.execute("SELECT failed_attempts,locked_until FROM login_attempts WHERE email=?",
                               (email,)).fetchone()
        locked_until = _parse_time(attempt["locked_until"]) if attempt and attempt["locked_until"] else None
        if locked_until and locked_until > now:
            raise LoginLockedError("Too many failed attempts. Try again in a few minutes.")
        if locked_until and locked_until <= now:
            conn.execute("DELETE FROM login_attempts WHERE email=?", (email,))

        account = conn.execute("SELECT id,email,name,password_hash,auth_provider,role FROM users "
                               "WHERE email=? AND auth_provider='password'", (email,)).fetchone()
        valid = verify_password(password or "", account["password_hash"] if account else None)
        if not account or not valid:
            # Do comparable work for unknown accounts without recording a password.
            if account is None:
                hashlib.pbkdf2_hmac("sha256", (password or "").encode(), b"nagriksetu-login-dummy", _PBKDF2_ITERATIONS)
            prior = conn.execute("SELECT failed_attempts FROM login_attempts WHERE email=?", (email,)).fetchone()
            failures = (prior["failed_attempts"] if prior else 0) + 1
            lock_time = (now + timedelta(minutes=_LOCK_MINUTES)).isoformat() if failures >= _LOCK_ATTEMPTS else None
            conn.execute("INSERT INTO login_attempts(email,failed_attempts,locked_until) VALUES(?,?,?) "
                         "ON CONFLICT(email) DO UPDATE SET failed_attempts=excluded.failed_attempts,locked_until=excluded.locked_until",
                         (email, failures, lock_time))
            if account:
                conn.execute("UPDATE users SET failed_attempts=?,locked_until=? WHERE id=?",
                             (failures, lock_time, account["id"]))
            conn.commit()
            return None
        conn.execute("DELETE FROM login_attempts WHERE email=?", (email,))
        conn.execute("UPDATE users SET failed_attempts=0,locked_until=NULL WHERE id=?", (account["id"],))
        conn.commit()
        return {key: account[key] for key in ("id", "email", "name", "role", "auth_provider")}
    except LoginLockedError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_time(value: str | None):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def get_active_user(user_id: int) -> dict | None:
    rows = fetch_all("SELECT id,email,name,auth_provider,role FROM users WHERE id=? AND active=1", (user_id,))
    if rows and rows[0]["auth_provider"] != "legacy":
        return rows[0]
    # Compatibility for old unit tests/programmatic utilities only. The web login
    # never authenticates these synthetic @legacy.invalid identities.
    if rows:
        return rows[0]
    legacy = fetch_all("SELECT id,username,password_hash,role,active FROM legacy_users WHERE id=? AND active=1",
                       (user_id,))
    if legacy:
        return {"id": legacy[0]["id"], "email": "", "name": legacy[0]["username"],
                "auth_provider": "legacy", "role": legacy[0]["role"]}
    return None


def oidc_available(secrets_obj) -> bool:
    try:
        auth = secrets_obj.get("auth", {})
        return all(auth.get(key) for key in ("redirect_uri", "cookie_secret", "client_id",
                                             "client_secret", "server_metadata_url"))
    except Exception:
        return False


# Compatibility with the pre-email tests and old administrative scripts. Archived
# records are kept in legacy_users during migration and cannot sign into the new UI.
def bootstrap_user(username: str, password: str, role: str, setup_token: str,
                   expected_token: str | None) -> None:
    if not expected_token or not setup_token or not hmac.compare_digest(setup_token, expected_token):
        raise PermissionError("Account setup is disabled or the setup token is invalid.")
    if role not in _OLD_ROLES or not (username or "").strip():
        raise ValueError("A username and valid legacy role are required.")
    encoded = hash_password(password)
    email = normalize_email(username) + "@legacy.invalid"
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE auth_provider='legacy' LIMIT 1").fetchone():
            raise ValueError("Initial account setup is already complete or the username is in use.")
        conn.execute("INSERT INTO users(email,name,password_hash,auth_provider,role) VALUES(?,?,?,'legacy',?)",
                     (email, username.strip(), encoded, role))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("Initial account setup is already complete or the username is in use.") from exc
    finally:
        conn.close()


def authenticate(username: str, password: str) -> dict | None:
    """Legacy-only login retained for old service tests; the UI uses authenticate_email."""
    normalized = normalize_email(username) + "@legacy.invalid"
    rows = fetch_all("SELECT id,email,name,password_hash,auth_provider,role FROM users "
                     "WHERE email=? AND auth_provider='legacy'", (normalized,))
    if rows and verify_password(password or "", rows[0]["password_hash"]):
        return {key: rows[0][key] for key in ("id", "email", "name", "role", "auth_provider")}
    legacy = fetch_all("SELECT id,username,password_hash,role FROM legacy_users WHERE username=? AND active=1",
                       ((username or "").strip(),))
    if legacy and verify_password(password or "", legacy[0]["password_hash"]):
        return {"id": legacy[0]["id"], "username": legacy[0]["username"], "role": legacy[0]["role"]}
    return None


def create_user(username: str, password: str, role: str, actor_role: str) -> None:
    """Legacy account helper; new government users must use allowlist/invite registration."""
    enforce_rbac(actor_role, "can_manage_users")
    if role not in _OLD_ROLES or not (username or "").strip():
        raise ValueError("A username and valid legacy role are required.")
    try:
        conn = get_conn()
        conn.execute("INSERT INTO legacy_users(username,password_hash,role) VALUES(?,?,?)",
                     (username.strip(), hash_password(password), role))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("Username is already in use.") from exc
    finally:
        if "conn" in locals():
            conn.close()
