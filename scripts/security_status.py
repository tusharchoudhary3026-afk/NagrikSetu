"""Print configured prototype security controls without inferring deployment guarantees."""
import json

from core.security import attachment_encryption_status, tls_status


def security_report():
    photo = attachment_encryption_status()
    tls = tls_status()
    return {
        "photo_attachment_encryption": photo["label"],
        "tls": tls["label"],
        "sqlite_at_rest_encryption": "NOT CONFIGURED by this application",
        "authentication_and_service_rbac": "Implemented in prototype; production identity review not done",
        "geography_admin_configuration": "NYAYAFLOW_GEO_ADMIN_EMAILS or protected data/geo_admin_allowlist.csv",
    }


if __name__ == "__main__":
    print(json.dumps(security_report(), indent=2))
