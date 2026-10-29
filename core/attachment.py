"""Private photo storage. Images are retained as evidence and are never analyzed."""
import uuid
import os
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .auth import enforce_rbac
from .config import ROOT, feature_enabled
from .db import execute, fetch_all, get_conn
from .security import attachment_encryption_key
from .geo import authorize_staff_complaint
from .geo import STAFF_ROLES
from .auth import authorize_user_action

_ENCRYPTED_HEADER = b"NF01"

ATTACHMENT_DIR = ROOT / "data" / "uploads"
MAX_FILE_SIZE_MB = 5
MAX_ATTACHMENTS_PER_COMPLAINT = 3
_FORMATS = {
    ".jpg": ("image/jpeg", "JPEG", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", "JPEG", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".png": ("image/png", "PNG", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ".webp": ("image/webp", "WEBP", lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP"),
}


def _bytes(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "read"):
        return uploaded_file.read()
    raise ValueError("Choose a JPEG or PNG photo.")


def _prepare(uploaded_file):
    suffix = Path(getattr(uploaded_file, "name", "")).suffix.lower()
    if suffix not in _FORMATS:
        raise ValueError("Photo must be a PNG, JPG, JPEG, or WEBP image.")
    data = _bytes(uploaded_file)
    if not data or len(data) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"Photo must be non-empty and no larger than {MAX_FILE_SIZE_MB} MB.")
    content_type, expected_format, signature_ok = _FORMATS[suffix]
    if not signature_ok(data):
        raise ValueError("File contents do not match the selected image type.")
    try:
        image = Image.open(BytesIO(data))
        image_format = image.format
        image.verify()
        image = Image.open(BytesIO(data))
        if image_format != expected_format:
            raise ValueError("File contents do not match the selected image type.")
        if image.width * image.height > 25_000_000:
            raise ValueError("Photo dimensions are too large.")
        image = ImageOps.exif_transpose(image)
        if suffix in {".jpg", ".jpeg"} and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        if suffix == ".png" and image.mode not in {"RGB", "RGBA", "L", "LA"}:
            image = image.convert("RGBA")
        if suffix == ".webp" and image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        clean = Image.new(image.mode, image.size)
        clean.paste(image)
        output = BytesIO()
        clean.save(output, format=expected_format, optimize=True)
        data = output.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The uploaded file is not a valid PNG, JPG, JPEG, or WEBP image.") from exc
    if len(data) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"Photo must be no larger than {MAX_FILE_SIZE_MB} MB after metadata removal.")
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    internal_name = f"{uuid.uuid4().hex}{suffix}"
    original_name = Path(str(getattr(uploaded_file, "name", "photo")).replace("\\", "/")).name[:255]
    return {"filename": internal_name, "original_name": original_name or "photo" + suffix,
            "content_type": content_type, "data": data}


def validate_attachments(uploaded_files) -> int:
    """Validate a complete upload selection before the complaint is written."""
    files = [uploaded for uploaded in (uploaded_files or []) if uploaded is not None]
    if len(files) > MAX_ATTACHMENTS_PER_COMPLAINT:
        raise ValueError(f"Choose no more than {MAX_ATTACHMENTS_PER_COMPLAINT} photos.")
    for uploaded in files:
        _prepare(uploaded)
    return len(files)


def save_attachments(complaint_id: int, uploaded_files, actor_role: str, actor_user: dict | None = None) -> list[str]:
    """Validate and store up to three private, metadata-stripped photo files atomically."""
    if not feature_enabled("photos"):
        raise PermissionError("Photo evidence is disabled by configuration.")
    enforce_rbac(actor_role, "can_intake")
    files = [uploaded for uploaded in (uploaded_files or []) if uploaded is not None]
    if not files:
        return []
    if len(files) > MAX_ATTACHMENTS_PER_COMPLAINT:
        raise ValueError(f"Choose no more than {MAX_ATTACHMENTS_PER_COMPLAINT} photos.")
    prepared = [_prepare(uploaded) for uploaded in files]
    key = attachment_encryption_key()
    paths = []
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        complaint = conn.execute("SELECT submitted_by FROM complaints WHERE id=?", (complaint_id,)).fetchone()
        if not complaint:
            raise ValueError("Complaint not found.")
        if actor_role in STAFF_ROLES:
            if not actor_user or actor_user.get("role") != actor_role:
                raise PermissionError("Pass the authenticated staff account to attach a photo.")
            authorize_user_action(actor_user.get("id"), "can_intake")
            authorize_staff_complaint(actor_role, complaint_id, actor_user)
        elif actor_role == "public":
            account = conn.execute("SELECT id,role,active FROM users WHERE id=?", ((actor_user or {}).get("id"),)).fetchone()
            if (not account or not account["active"] or account["role"] != "public"
                    or complaint["submitted_by"] != account["id"]):
                raise PermissionError("Residents can attach photos only to their own complaints.")
        existing = conn.execute("SELECT COUNT(*) AS n FROM attachments WHERE complaint_id=?", (complaint_id,)).fetchone()["n"]
        if existing + len(prepared) > MAX_ATTACHMENTS_PER_COMPLAINT:
            raise ValueError(f"A complaint can have no more than {MAX_ATTACHMENTS_PER_COMPLAINT} photos.")
        for item in prepared:
            filename = item["filename"]
            path = ATTACHMENT_DIR / filename
            nonce = os.urandom(12)
            aad = f"{int(complaint_id)}:{filename}".encode("utf-8")
            encrypted = _ENCRYPTED_HEADER + nonce + AESGCM(key).encrypt(nonce, item["data"], aad)
            path.write_bytes(encrypted)
            paths.append(path)
            conn.execute(
                "INSERT INTO attachments (complaint_id,filename,file_path,content_type,byte_size,is_encrypted,original_name,mime,size_bytes) "
                "VALUES (?,?,?,?,?,1,?,?,?)",
                (complaint_id, filename, str(path), item["content_type"], len(item["data"]),
                 item["original_name"], item["content_type"], len(item["data"])))
        conn.commit()
        return [item["filename"] for item in prepared]
    except Exception:
        conn.rollback()
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def save_attachment(complaint_id: int, uploaded_file, actor_role: str, actor_user: dict | None = None) -> str | None:
    if not uploaded_file:
        return None
    saved = save_attachments(complaint_id, [uploaded_file], actor_role, actor_user=actor_user)
    return saved[0] if saved else None


def get_attachments(complaint_id: int, actor_role: str, actor_user: dict | None = None):
    if not feature_enabled("photos"):
        raise PermissionError("Photo evidence is disabled by configuration.")
    enforce_rbac(actor_role, "can_view_attachments")
    if actor_role in STAFF_ROLES:
        if not actor_user or actor_user.get("role") != actor_role:
            raise PermissionError("Pass the authenticated staff account to view photos.")
        authorize_user_action(actor_user.get("id"), "can_view_attachments")
    authorize_staff_complaint(actor_role, complaint_id, actor_user)
    return fetch_all("SELECT id, complaint_id, filename, file_path, content_type, byte_size, is_encrypted, "
                     "COALESCE(original_name,filename) AS original_name,COALESCE(mime,content_type) AS mime, "
                     "COALESCE(size_bytes,byte_size) AS size_bytes,created_at "
                     "FROM attachments WHERE complaint_id=? ORDER BY id", (complaint_id,))


def read_attachment(attachment_id: int, actor_role: str, actor_user: dict | None = None) -> bytes:
    """Return decrypted photo bytes to an authorized reviewer; legacy plaintext is denied."""
    if not feature_enabled("photos"):
        raise PermissionError("Photo evidence is disabled by configuration.")
    enforce_rbac(actor_role, "can_view_attachments")
    rows = fetch_all("SELECT complaint_id, filename, file_path, is_encrypted FROM attachments WHERE id=?",
                     (attachment_id,))
    if not rows:
        raise ValueError("Photo attachment not found.")
    row = rows[0]
    if actor_role in STAFF_ROLES:
        if not actor_user or actor_user.get("role") != actor_role:
            raise PermissionError("Pass the authenticated staff account to read photos.")
        authorize_user_action(actor_user.get("id"), "can_view_attachments")
    authorize_staff_complaint(actor_role, row["complaint_id"], actor_user)
    if not row["is_encrypted"]:
        raise ValueError("This legacy photo is not encrypted. Re-upload it through the secure intake flow.")
    try:
        stored = Path(row["file_path"]).read_bytes()
        if not stored.startswith(_ENCRYPTED_HEADER) or len(stored) < len(_ENCRYPTED_HEADER) + 12 + 16:
            raise ValueError("Encrypted photo data is invalid.")
        nonce_start = len(_ENCRYPTED_HEADER)
        nonce = stored[nonce_start:nonce_start + 12]
        aad = f"{int(row['complaint_id'])}:{row['filename']}".encode("utf-8")
        return AESGCM(attachment_encryption_key()).decrypt(nonce, stored[nonce_start + 12:], aad)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Photo decryption failed. Check that the configured key matches the upload key.") from exc


def migrate_legacy_attachments() -> int:
    """Encrypt plaintext legacy photos in place and return the number migrated.

    The encrypted file is written first; its database reference is committed next;
    the plaintext source is removed only after the reference update succeeds.
    """
    key = attachment_encryption_key()
    rows = fetch_all("SELECT id, complaint_id, filename, file_path FROM attachments "
                     "WHERE is_encrypted=0 ORDER BY id")
    migrated = 0
    for row in rows:
        source = Path(row["file_path"])
        if not source.is_file():
            raise ValueError(f"Legacy photo file is missing for attachment {row['id']}: {source}")
        data = source.read_bytes()
        nonce = os.urandom(12)
        aad = f"{int(row['complaint_id'])}:{row['filename']}".encode("utf-8")
        encrypted = _ENCRYPTED_HEADER + nonce + AESGCM(key).encrypt(nonce, data, aad)
        target = source.with_name(f"{source.name}.nfenc")
        if target.exists():
            raise ValueError(f"Migration target already exists for attachment {row['id']}: {target}")
        target.write_bytes(encrypted)
        try:
            execute("UPDATE attachments SET file_path=?, is_encrypted=1 WHERE id=? AND is_encrypted=0",
                    (str(target), row["id"]))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        source.unlink(missing_ok=True)
        migrated += 1
    return migrated
