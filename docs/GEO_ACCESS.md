# Geographic complaint access

## How access is granted

1. A resident or staff member authenticates using the existing email/government invite flow.
2. Government applicants select a State → City/district → Area in account setup. This selection creates or chooses a location request; it does not itself grant complaint access.
3. A staff identity on `data/gov_allowlist.csv` receives only the exact area grants listed for that email. Other verified government users receive no complaint access while a request is pending.
4. A geography administrator approves or rejects requests in **Area access requests**. The administrator must be an active Government account and the email must appear in the protected `data/geo_admin_allowlist.csv` or the `NYAYAFLOW_GEO_ADMIN_EMAILS` deployment variable. The administrator cannot approve the same staff member’s request.
5. A staff member can request additional areas from the overview page. An authorized administrator can revoke a grant; each request, approval, rejection, and revocation appends a row to `government_area_events`.

Set `NYAYAFLOW_GEO_ADMIN_EMAILS` to a comma-separated list of approved administrator emails in the trusted deployment environment. Do not commit real staff emails to the repository. `data/geo_admin_allowlist.csv` is a local prototype option and must be protected in deployments.

## Complaint handling

The resident portal offers cascading geography selectors. Residents may leave a lower level unknown; the system preserves only the known levels and marks the service area missing. Such cases appear only in the restricted geography-admin queue until triaged through a future governed assignment workflow.

Only a fully specified state/city/area is visible to ordinary staff with the matching server-side grant. Inbox, review, challenges, duplicate matching/decisions, attachments, replay, analytics, and audit exports enforce or query this scope. A URL, widget value, or session edit cannot grant a new area. Residents continue to query complaints by their authenticated account ID.

Area options live in `data/geo_coverage.json`. They are sample prototype geography covering Madhya Pradesh, Uttar Pradesh, Maharashtra, and Punjab, including Gwalior areas Morar and Gole Ka Mandir. They are not an authoritative ward-boundary or municipal jurisdiction dataset; verify and replace them with approved city data before operational deployment.

## Legacy records and limits

The schema migration adds structured location columns but does not infer geography for existing complaints. Those records remain unassigned and are hidden from ordinary staff until reviewed by an authorized geography administrator. Existing user role data is preserved. Authentication and access checks are prototype-grade; protect deployment secrets, use a production identity provider, and review the data protection model before real resident data is stored.
