# Staff location self-selection update (2026-10-29)

The staff overview no longer requires a geography administrator to approve an area before its complaints can be viewed. After signing in, staff choose State, City/district and Area, then select **Show complaints for this area**. The app records the selection and reloads the staff view with matching complaints.

This is an intentional access-policy change: any active, registered staff account can self-select any area in the configured geography list. Selection is audited as an append-only `approved` geography event whose actor is the staff member. A geography administrator can still revoke the grant. Staff authentication and role checks remain required; operators are still limited to their department, reviewers can take permitted review actions, and auditors remain read-only. The geography list is sample data, not authoritative boundaries.

An older pending area request does not block self-selection. Complaints without structured state/city/area remain in the restricted geography-triage path because the app must not guess where they belong.

The prior [staff area access report](DEMO_STAFF_AREA_ACCESS_FIX_2026-10-29.md) documented a demo-only city assignment and the former approval gate. That gate is superseded for the staff overview by this update; its synthetic demo seeding details remain relevant only to the explicitly enabled demo accounts.

## Regression coverage

`tests/test_app_shell.py::test_staff_can_select_area_and_see_complaints_without_admin_approval` logs in as an ordinary reviewer, submits a known-area streetlight case, self-selects Gole Ka Mandir, and verifies that the selected scope is active and the staff query returns the complaint with its original text and location. The event is checked for the staff actor and append-only insert semantics.

Run with `python -m pytest -q` and `python -m scripts.run_acceptance` from the project root.
