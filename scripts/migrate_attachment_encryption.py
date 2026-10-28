"""Encrypt legacy plaintext photo attachments using NYAYAFLOW_ATTACHMENT_KEY."""
from core.attachment import migrate_legacy_attachments
from core.db import init_db

if __name__ == "__main__":
    init_db()
    count = migrate_legacy_attachments()
    print(f"Encrypted {count} legacy photo attachment(s).")
