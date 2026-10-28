"""Report the app's configured security posture without inferring infrastructure controls."""
import os
from pathlib import Path


def attachment_encryption_key() -> bytes:
    value = os.environ.get("NYAYAFLOW_ATTACHMENT_KEY", "").strip()
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Set NYAYAFLOW_ATTACHMENT_KEY to 64 hexadecimal characters (32 bytes).") from exc
    if len(key) != 32:
        raise ValueError("Set NYAYAFLOW_ATTACHMENT_KEY to 64 hexadecimal characters (32 bytes).")
    return key


def attachment_encryption_status() -> dict:
    try:
        attachment_encryption_key()
        return {"configured": True, "label": "Configured · AES-256-GCM"}
    except ValueError:
        return {"configured": False, "label": "Not configured · photo uploads disabled"}


def tls_status(cert_path=None, key_path=None) -> dict:
    cert_path = cert_path if cert_path is not None else os.environ.get("NYAYAFLOW_TLS_CERT", "")
    key_path = key_path if key_path is not None else os.environ.get("NYAYAFLOW_TLS_KEY", "")
    configured = bool(cert_path and key_path and Path(cert_path).is_file() and Path(key_path).is_file())
    return {"configured": configured, "label": "Certificate and key present" if configured else "Unverified · configure TLS at the trusted hosting layer"}
