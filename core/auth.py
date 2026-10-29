"""Existing Streamlit/SQLite authentication, verified staff enrollment, and RBAC."""
import csv
import hashlib
import hmac
import json
import os
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
from .password_policy import generate_strong_password, score_password
assess_password = score_password

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
STAFF_ROLES = {"government", "operator", "reviewer", "auditor"}
_EMAIL = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
_PBKDF2_ITERATIONS = 310_000
_LOCK_ATTEMPTS = 5
_LOCK_MINUTES = 15
_LOCK_WINDOW_MINUTES = 15
_OTP_MAX_ATTEMPTS = 5
_OTP_TTL_MINUTES = 10
_OTP_COOLDOWN_SECONDS = 30
_OLD_ROLES = {"operator", "reviewer", "auditor"}


class LoginLockedError(ValueError):
    """Raised when an email address is temporarily locked after failed logins."""


def normalize_email(email: str) -> str:
    if not isinstance(email, str) or any(ord(char) < 32 or ord(char) == 127 for char in email):
        return ""
    return email.strip().casefold()


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
    digest = hashlib.scrypt(raw, salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not isinstance(password, str) or not encoded:
        return False
    try:
        if encoded.startswith("bcrypt$") and bcrypt is not None:
            return bcrypt.checkpw(password.encode("utf-8"), encoded[7:].encode("ascii"))
        if encoded.startswith("scrypt$"):
            algorithm, n, r, p, salt_hex, expected = encoded.split("$")
            if algorithm != "scrypt" or int(n) != 16384 or int(r) != 8 or int(p) != 1:
                return False
            digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                    n=int(n), r=int(r), p=int(p), dklen=32)
            return hmac.compare_digest(digest.hex(), expected)
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
    active = refresh_session(st.session_state)
    if not active:
        st.info("Sign in to open this page.")
        st.page_link("pages/0_Home.py", label="Go to sign in", icon="🔐")
        st.stop()
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
        user = authorize_user_action(user["id"], action)
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
                  invite_code: str = "", auth_provider: str = "password", phone: str | None = None) -> dict:
    auth_secret()
    email = validate_email(email)
    name = _clean_text(name, max_length=120, label="name")
    if not name or len(name) > 120:
        raise ValueError("Enter your name (up to 120 characters).")
    if requested_role != "public":
        raise ValueError("Public accounts are always citizen accounts. Staff must use staff-directory registration.")
    if auth_provider not in {"password", "google"}:
        raise ValueError("Unsupported sign-in provider.")
    if _staff_record(email):
        _auth_event("registration", email, "reserved_staff_address")
        raise ValueError("This address is reserved for staff registration")
    if phone:
        phone = normalize_indian_phone(phone)
        raise ValueError("Mobile registration requires phone verification. Use the phone verification flow.")
    if auth_provider == "password":
        if password != password_confirm:
            raise ValueError("Passwords do not match.")
        validate_password(password or "", email=email, name=name, phone=phone)
        encoded_password = hash_password(password or "")
    else:
        if password is not None:
            raise ValueError("Google accounts do not store a local password.")
        encoded_password = None

    conn = get_conn()
    try:
        conn.execute("INSERT INTO users (email,name,password_hash,auth_provider,role) VALUES (?,?,?,?,?)",
                     (email, name, encoded_password, auth_provider, "public"))
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        _auth_event("registration", email, "success", "public")
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError("An account with this email already exists. Sign in instead.") from exc
    finally:
        conn.close()
    return {"id": user_id, "email": email, "name": name, "role": "public",
            "auth_provider": auth_provider, "phone": None}


def get_user_by_email(email: str) -> dict | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    rows = fetch_all("SELECT id,email,name,auth_provider,role FROM users "
                     "WHERE email=? AND auth_provider<>'legacy'", (normalized,))
    return rows[0] if rows else None


def authenticate_email(email: str, password: str) -> dict | None:
    return authenticate(email, password)


def _clean_text(value: str | None, *, max_length: int, label: str) -> str:
    if not isinstance(value, str) or any(ord(char) < 32 and char not in "\t" for char in value):
        raise ValueError(f"Enter a valid {label}.")
    result = " ".join(value.strip().split())
    if len(result) > max_length:
        raise ValueError(f"{label.capitalize()} must be {max_length} characters or fewer.")
    return result


def validate_password(password: str, *, email=None, name=None, phone=None) -> dict:
    result = score_password(password, email=email, name=name, phone=phone)
    if not result["accepted"]:
        raise ValueError("Password does not meet the strength policy: " + "; ".join(result["suggestions"]))
    return result


def normalize_indian_phone(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Enter a valid Indian mobile number.")
    text = re.sub(r"[ -]", "", value.strip())
    if text.startswith("+91"):
        digits = text[3:]
    elif text.startswith("91") and len(text) == 12:
        digits = text[2:]
    elif text.startswith("0") and len(text) == 11:
        digits = text[1:]
    else:
        digits = text
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("Enter a valid Indian mobile number starting with 6, 7, 8, or 9.")
    return "+91" + digits


def demo_mode() -> bool:
    return os.environ.get("NAGRIKSETU_DEMO_MODE", "1").strip().casefold() not in {"0", "false", "no", "off"}


def auth_secret() -> bytes:
    configured = os.environ.get("NAGRIKSETU_AUTH_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if demo_mode():
        return b"nagriksetu-demo-only-secret-change-before-deployment"
    raise RuntimeError("NAGRIKSETU_AUTH_SECRET is required when DEMO MODE is disabled.")


def identifier_hash(identifier: str) -> str:
    canonical = (identifier or "").strip().casefold()
    return hmac.new(auth_secret(), canonical.encode("utf-8", "replace"), hashlib.sha256).hexdigest()


def mask_identifier(identifier: str) -> str:
    value = (identifier or "").strip()
    if "@" in value:
        local, domain = value.split("@", 1)
        return (local[:1] + "***@" + domain) if local else "***@" + domain
    try:
        phone = normalize_indian_phone(value)
        return f"+91 {phone[3:5]}****{phone[-4:]}"
    except ValueError:
        return "***"


def _auth_event(event_type: str, identifier: str, outcome: str, role: str | None = None):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO auth_events(event_type,identifier_hash,outcome,role) VALUES(?,?,?,?)",
                     (event_type, identifier_hash(identifier), outcome, role))
        conn.commit()
    finally:
        conn.close()


def _staff_record(email: str):
    normalized = normalize_email(email)
    if not normalized:
        return None
    rows = fetch_all("SELECT * FROM staff_directory WHERE staff_email=?", (normalized,))
    return rows[0] if rows else None


def staff_directory_preview(email: str) -> dict | None:
    """Return only an eligible synthetic staff record for the registration screen."""
    try:
        row = _staff_record(email)
    except ValueError:
        return None
    if not row or row["status"] != "active" or row["registered"]:
        return None
    return {key: row[key] for key in ("full_name", "role", "department")}


def send_email_code(email: str, code: str) -> dict:
    """Delivery seam. Demo mode only displays the simulated code; real email is ROADMAP."""
    if demo_mode():
        return {"simulated": True, "message": "SIMULATED: no real email is sent", "code": code}
    raise NotImplementedError("Real email delivery is ROADMAP; no provider is configured.")


def send_sms_otp(phone: str, code: str) -> dict:
    """Delivery seam. Demo mode only displays the simulated OTP; real SMS is ROADMAP."""
    if demo_mode():
        return {"simulated": True, "message": "SIMULATED: no real SMS is sent", "code": code}
    raise NotImplementedError("Real SMS delivery is ROADMAP; no provider is configured.")


def _code_hash(code: str, salt: bytes) -> str:
    return hmac.new(auth_secret(), salt + code.encode("ascii", "ignore"), hashlib.sha256).hexdigest()


def _request_challenge(purpose: str, identifier: str, account_name: str,
                       password_hash: str, *, code: str | None = None) -> dict:
    if not demo_mode():
        auth_secret()
        raise NotImplementedError("Real email/SMS delivery is ROADMAP; simulated codes are disabled outside DEMO MODE.")
    now = datetime.now(timezone.utc)
    normalized = normalize_email(identifier) if purpose == "staff_email" else normalize_indian_phone(identifier)
    key = identifier_hash(normalized)
    rows = fetch_all("SELECT * FROM verification_challenges WHERE purpose=? AND identifier_hash=? "
                     "ORDER BY id DESC LIMIT 1", (purpose, key))
    previous = rows[0] if rows else None
    if previous and previous["last_sent_at"]:
        elapsed = now - (_parse_time(previous["last_sent_at"]) or now)
        if elapsed.total_seconds() < _OTP_COOLDOWN_SECONDS:
            raise ValueError("Please wait 30 seconds before requesting another code.")
    window_start = now - timedelta(minutes=15)
    requests = fetch_all("SELECT COUNT(*) AS count FROM verification_challenges WHERE purpose=? "
                         "AND identifier_hash=? AND window_started_at>=?",
                         (purpose, key, window_start.isoformat()))[0]["count"]
    if requests >= 5:
        raise ValueError("Too many code requests. Try again in 15 minutes.")
    code = code if code is not None else f"{secrets.randbelow(1_000_000):06d}"
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("A verification code must contain exactly six digits.")
    salt = secrets.token_bytes(16)
    conn = get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO verification_challenges(purpose,identifier_hash,code_salt,code_hash,expires_at,"
            "last_sent_at,window_started_at,request_count,account_name,password_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (purpose, key, salt.hex(), _code_hash(code, salt), (now + timedelta(minutes=_OTP_TTL_MINUTES)).isoformat(),
             now.isoformat(), (previous["window_started_at"] if previous and
                               _parse_time(previous["window_started_at"]) and
                               _parse_time(previous["window_started_at"]) >= window_start else now.isoformat()),
             (previous["request_count"] + 1 if previous and
              _parse_time(previous["window_started_at"]) and
              _parse_time(previous["window_started_at"]) >= window_start else 1), account_name, password_hash))
        conn.commit()
        challenge_id = cursor.lastrowid
    finally:
        conn.close()
    delivery = send_email_code(normalized, code) if purpose == "staff_email" else send_sms_otp(normalized, code)
    _auth_event("verification_code_requested", normalized, "simulated" if delivery["simulated"] else "sent")
    return {"challenge_id": challenge_id, **delivery,
            "simulated_code": delivery.get("code") if delivery.get("simulated") else None}


def begin_staff_registration(email: str, name: str, password: str, password_confirm: str,
                             *, requested_role: str | None = None, code: str | None = None) -> dict:
    auth_secret()
    normalized = validate_email(email)
    staff = _staff_record(normalized)
    if not staff:
        _auth_event("registration", normalized, "staff_not_allowlisted")
        raise ValueError("This address is not listed for staff registration.")
    if staff["status"] != "active":
        _auth_event("registration", normalized, "staff_disabled", staff["role"])
        raise ValueError("This staff registration is disabled.")
    if staff["registered"]:
        _auth_event("registration", normalized, "staff_already_registered", staff["role"])
        raise ValueError("This staff account is already registered.")
    # Display names, like role and department, are sourced from the pseudo directory.
    clean_name = _clean_text(staff["full_name"], max_length=120, label="name")
    if password != password_confirm:
        raise ValueError("Passwords do not match.")
    validate_password(password, email=normalized, name=clean_name)
    return _request_challenge("staff_email", normalized, clean_name, hash_password(password), code=code)


def resend_staff_email_code(email: str, *, code: str | None = None) -> dict:
    normalized = validate_email(email)
    staff = _staff_record(normalized)
    if not staff or staff["status"] != "active" or staff["registered"]:
        raise ValueError("This staff account is not eligible for registration.")
    rows = fetch_all("SELECT account_name,password_hash FROM verification_challenges WHERE purpose='staff_email' "
                     "AND identifier_hash=? ORDER BY id DESC LIMIT 1", (identifier_hash(normalized),))
    if not rows:
        raise ValueError("Start staff registration before requesting a new code.")
    return _request_challenge("staff_email", normalized, rows[0]["account_name"], rows[0]["password_hash"], code=code)


def _consume_challenge(purpose: str, identifier: str, code: str):
    normalized = normalize_email(identifier) if purpose == "staff_email" else normalize_indian_phone(identifier)
    key = identifier_hash(normalized)
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM verification_challenges WHERE purpose=? AND identifier_hash=? "
                           "ORDER BY id DESC LIMIT 1", (purpose, key)).fetchone()
        now = datetime.now(timezone.utc)
        if not row or row["consumed_at"]:
            conn.rollback()
            _auth_event("verification", normalized, "invalid_or_reused")
            raise ValueError("This verification code is invalid or already used.")
        if _parse_time(row["expires_at"]) is None or _parse_time(row["expires_at"]) <= now:
            conn.commit()
            _auth_event("verification", normalized, "expired")
            raise ValueError("This verification code has expired. Request another code.")
        if row["attempts"] >= _OTP_MAX_ATTEMPTS:
            conn.rollback()
            _auth_event("verification", normalized, "attempt_limit")
            raise ValueError("Maximum verification attempts reached. Request a new code later.")
        salt = bytes.fromhex(row["code_salt"])
        candidate = _code_hash(str(code or ""), salt)
        if not re.fullmatch(r"\d{6}", str(code or "")) or not hmac.compare_digest(candidate, row["code_hash"]):
            attempts = row["attempts"] + 1
            conn.execute("UPDATE verification_challenges SET attempts=? WHERE id=?", (attempts, row["id"]))
            conn.commit()
            _auth_event("verification", normalized, "failed_attempt_limit" if attempts >= _OTP_MAX_ATTEMPTS else "invalid_code")
            raise ValueError("Maximum verification attempts reached." if attempts >= _OTP_MAX_ATTEMPTS
                             else "The verification code is incorrect.")
        return conn, row, normalized
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        conn.close()
        raise


def verify_staff_registration(email: str, code: str) -> dict:
    normalized = validate_email(email)
    conn, challenge, normalized = _consume_challenge("staff_email", normalized, code)
    try:
        staff = conn.execute("SELECT * FROM staff_directory WHERE staff_email=?", (normalized,)).fetchone()
        if not staff or staff["status"] != "active" or staff["registered"]:
            conn.rollback()
            raise ValueError("This staff record is no longer eligible for registration.")
        try:
            cursor = conn.execute("INSERT INTO users(email,name,password_hash,auth_provider,role,department) "
                                  "VALUES(?,?,?,'password',?,?)",
                                  (normalized, challenge["account_name"], challenge["password_hash"],
                                   staff["role"], staff["department"]))
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError("This staff account is already registered.") from exc
        conn.execute("UPDATE staff_directory SET registered=1 WHERE id=? AND registered=0", (staff["id"],))
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            conn.rollback()
            raise ValueError("This staff account is already registered.")
        conn.execute("UPDATE verification_challenges SET consumed_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), challenge["id"]))
        conn.commit()
        user_id = cursor.lastrowid
        account = get_active_user(user_id)
        _auth_event("registration", normalized, "success", staff["role"])
        _auth_event("verification", normalized, "success", staff["role"])
        return account
    finally:
        conn.close()


def begin_public_phone_registration(phone: str, name: str, password: str, password_confirm: str,
                                    *, code: str | None = None) -> dict:
    auth_secret()
    normalized = normalize_indian_phone(phone)
    clean_name = _clean_text(name, max_length=120, label="name")
    if not clean_name:
        raise ValueError("Enter your name.")
    if password != password_confirm:
        raise ValueError("Passwords do not match.")
    validate_password(password, name=clean_name, phone=normalized)
    if fetch_all("SELECT 1 FROM users WHERE phone=?", (normalized,)):
        raise ValueError("An account with this mobile number already exists.")
    return _request_challenge("public_phone", normalized, clean_name, hash_password(password), code=code)


def resend_public_phone_otp(phone: str, *, code: str | None = None) -> dict:
    normalized = normalize_indian_phone(phone)
    if fetch_all("SELECT 1 FROM users WHERE phone=?", (normalized,)):
        raise ValueError("This mobile number already has a registered account.")
    rows = fetch_all("SELECT account_name,password_hash FROM verification_challenges WHERE purpose='public_phone' "
                     "AND identifier_hash=? ORDER BY id DESC LIMIT 1", (identifier_hash(normalized),))
    if not rows:
        raise ValueError("Start mobile registration before requesting an OTP.")
    return _request_challenge("public_phone", normalized, rows[0]["account_name"], rows[0]["password_hash"], code=code)


def verify_public_phone_registration(phone: str, code: str) -> dict:
    normalized = normalize_indian_phone(phone)
    conn, challenge, normalized = _consume_challenge("public_phone", normalized, code)
    try:
        # The current users schema requires a unique email. This reserved .invalid
        # identifier is internal only; no message is sent and the account signs in by phone.
        placeholder_email = "phone-" + normalized[1:] + "@phone.nagriksetu.invalid"
        try:
            cursor = conn.execute("INSERT INTO users(email,name,password_hash,auth_provider,role,phone,phone_verified) "
                                  "VALUES(?,?,?,'password','public',?,1)",
                                  (placeholder_email, challenge["account_name"], challenge["password_hash"], normalized))
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError("An account with this mobile number already exists.") from exc
        conn.execute("UPDATE verification_challenges SET consumed_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), challenge["id"]))
        conn.commit()
        account = get_active_user(cursor.lastrowid)
        _auth_event("registration", normalized, "success", "public")
        _auth_event("verification", normalized, "success", "public")
        return account
    finally:
        conn.close()


def authenticate_identifier(identifier: str, password: str) -> dict | None:
    """Authenticate citizens by email or E.164 phone; staff are email-only."""
    auth_secret()
    raw = identifier if isinstance(identifier, str) else ""
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        _auth_event("login_failure", raw, "invalid_identifier")
        return None
    try:
        if "@" in raw:
            normalized = validate_email(raw)
            identifier_kind = "email"
        else:
            normalized = normalize_indian_phone(raw)
            identifier_kind = "phone"
    except ValueError:
        _auth_event("login_failure", raw, "invalid_identifier")
        return None
    key = identifier_hash(normalized)
    now = datetime.now(timezone.utc)
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        attempt = conn.execute("SELECT * FROM auth_login_attempts WHERE identifier_hash=?", (key,)).fetchone()
        started = _parse_time(attempt["window_started_at"]) if attempt else None
        locked_until = _parse_time(attempt["locked_until"]) if attempt and attempt["locked_until"] else None
        if locked_until and locked_until > now:
            conn.rollback()
            _auth_event("lockout", normalized, "locked")
            raise LoginLockedError("Invalid credentials")
        if not started or now - started > timedelta(minutes=_LOCK_WINDOW_MINUTES):
            conn.execute("DELETE FROM auth_login_attempts WHERE identifier_hash=?", (key,))
            attempt = None
            started = now
        if identifier_kind == "email":
            account = conn.execute("SELECT id,email,name,password_hash,auth_provider,role,phone,phone_verified,department,active "
                                   "FROM users WHERE email=? AND auth_provider='password'", (normalized,)).fetchone()
        else:
            account = conn.execute("SELECT id,email,name,password_hash,auth_provider,role,phone,phone_verified,department,active "
                                   "FROM users WHERE phone=? AND role='public' AND phone_verified=1 "
                                   "AND auth_provider='password'", (normalized,)).fetchone()
        valid = bool(account and account["active"] and verify_password(password or "", account["password_hash"]))
        if account and account["role"] in STAFF_ROLES:
            directory = conn.execute("SELECT status,registered,role FROM staff_directory WHERE staff_email=?",
                                     (account["email"],)).fetchone()
            valid = bool(valid and directory and directory["status"] == "active"
                         and directory["registered"] and directory["role"] == account["role"])
        if not valid:
            if account is None:
                # Constant-ish work for unknown identifiers without retaining any submitted password.
                hashlib.scrypt((password or "").encode(), salt=b"nagriksetu-login-dummy-salt",
                               n=2**14, r=8, p=1, dklen=32)
            failures = (attempt["failed_attempts"] if attempt else 0) + 1
            lock_time = (now + timedelta(minutes=_LOCK_MINUTES)).isoformat() if failures >= _LOCK_ATTEMPTS else None
            conn.execute("INSERT INTO auth_login_attempts(identifier_hash,window_started_at,failed_attempts,locked_until) "
                         "VALUES(?,?,?,?) ON CONFLICT(identifier_hash) DO UPDATE SET "
                         "window_started_at=excluded.window_started_at,failed_attempts=excluded.failed_attempts,"
                         "locked_until=excluded.locked_until", (key, (started or now).isoformat(), failures, lock_time))
            conn.commit()
            _auth_event("login_failure", normalized, "invalid_credentials")
            if failures >= _LOCK_ATTEMPTS:
                _auth_event("lockout", normalized, "locked")
            return None
        conn.execute("DELETE FROM auth_login_attempts WHERE identifier_hash=?", (key,))
        conn.execute("UPDATE users SET failed_attempts=0,locked_until=NULL WHERE id=?", (account["id"],))
        conn.commit()
        result = {key: account[key] for key in ("id", "email", "name", "role", "auth_provider",
                                                "phone", "phone_verified", "department")}
        _auth_event("login_success", normalized, "success", account["role"])
        return result
    except LoginLockedError:
        raise
    finally:
        conn.close()


def authorize_user_action(user_id: int, action: str) -> dict:
    """Service-layer role check that reloads active identity and role from SQLite."""
    account = get_active_user(int(user_id))
    if not account or account.get("auth_provider") == "legacy":
        _auth_event("role_denied", str(user_id), "inactive_or_missing")
        raise PermissionError("This account is not active.")
    try:
        enforce_rbac(account["role"], action)
    except PermissionError:
        _auth_event("role_denied", account.get("email", str(user_id)), action, account["role"])
        raise
    return account


def start_session(session_state, account: dict):
    """Store only an account id, a display role snapshot, and inactivity timestamps."""
    fresh = get_active_user(account.get("id"))
    if not fresh:
        raise PermissionError("This account is not active.")
    now = datetime.now(timezone.utc).isoformat()
    session_state["authenticated_user"] = fresh
    session_state["authenticated_user_id"] = fresh["id"]
    session_state["authenticated_role"] = fresh["role"]
    session_state["auth_last_activity"] = now
    session_state["auth_session_started"] = now


def refresh_session(session_state) -> dict | None:
    user_id = session_state.get("authenticated_user_id")
    if not user_id:
        cached = session_state.get("authenticated_user")
        # Compatibility for test-created Streamlit sessions: treat this first read
        # as activity, then enforce the regular expiry rule on subsequent requests.
        if isinstance(cached, dict) and cached.get("id"):
            user_id = cached["id"]
            now = datetime.now(timezone.utc).isoformat()
            session_state["authenticated_user_id"] = user_id
            session_state["auth_session_started"] = now
            session_state["auth_last_activity"] = now
        else:
            return None
    last_activity = _parse_time(session_state.get("auth_last_activity"))
    now = datetime.now(timezone.utc)
    if not last_activity or now - last_activity > timedelta(minutes=30):
        old = session_state.get("authenticated_user") or {}
        _auth_event("logout", old.get("email") or old.get("phone") or str(user_id), "session_expired",
                    old.get("role"))
        clear_session(session_state)
        return None
    account = get_active_user(user_id)
    if not account or account.get("auth_provider") == "legacy":
        clear_session(session_state)
        return None
    session_state["authenticated_user"] = account
    session_state["authenticated_user_id"] = account["id"]
    session_state["authenticated_role"] = account["role"]
    session_state["auth_last_activity"] = now.isoformat()
    return account


def clear_session(session_state):
    try:
        session_state.clear()
    except AttributeError:
        for key in list(session_state):
            session_state.pop(key, None)


def logout_session(session_state):
    user = session_state.get("authenticated_user") or {}
    identifier = user.get("email") or user.get("phone") or "unknown"
    if user:
        _auth_event("logout", identifier, "success", user.get("role"))
    clear_session(session_state)


def _parse_time(value: str | None):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def get_active_user(user_id: int) -> dict | None:
    rows = fetch_all("SELECT id,email,name,auth_provider,role,phone,phone_verified,department "
                     "FROM users WHERE id=? AND active=1", (user_id,))
    if rows and rows[0]["auth_provider"] != "legacy":
        if rows[0]["role"] in STAFF_ROLES:
            directory = _staff_record(rows[0]["email"])
            if (not directory or directory["status"] != "active" or not directory["registered"]
                    or directory["role"] != rows[0]["role"]
                    or directory["department"] != rows[0]["department"]):
                return None
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


def _authenticate_legacy(username: str, password: str) -> dict | None:
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


def authenticate(identifier: str, password: str) -> dict | None:
    """Compatibility facade; the Streamlit UI uses authenticate_identifier only."""
    value = (identifier or "").strip()
    if "@" in value or re.search(r"\d", value) or value.startswith("+"):
        return authenticate_identifier(identifier, password)
    return _authenticate_legacy(identifier, password)


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
