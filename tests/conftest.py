import sys, pathlib, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture
def db(tmp_path, monkeypatch):
    from core import db as dbm
    test_db_path = tmp_path / "test.db"
    # AppTest boots a separate Streamlit script context, so set the environment
    # variable as well as patching this pytest process's imported module.
    monkeypatch.setenv("NYAYAFLOW_DB_PATH", str(test_db_path))
    monkeypatch.setenv("NAGRIKSETU_DEMO_MODE", "1")
    monkeypatch.setattr(dbm, "DB_PATH", test_db_path)
    dbm.init_db()
    return dbm


@pytest.fixture
def staff_user(db, monkeypatch):
    """Create an authenticated synthetic staff account and grant only test admin scope."""
    from core.auth import begin_staff_registration, verify_staff_registration
    from core.db import execute
    counter = 0

    def create(role="reviewer", department="Grievance Cell"):
        nonlocal counter
        counter += 1
        email = f"test{counter}.{role}@staff.nagriksetu-demo.example"
        name = f"Synthetic Unit {counter}"
        execute("INSERT INTO staff_directory(staff_email,full_name,role,department,status,registered,tag) "
                "VALUES(?,?,?,?,'active',0,'SYNTHETIC')", (email, name, role, department))
        password = "Verify!Example42"
        flow = begin_staff_registration(email, "ignored form name", password, password, code="314159")
        user = verify_staff_registration(email, flow["simulated_code"])
        admins = {item.strip() for item in __import__("os").environ.get("NYAYAFLOW_GEO_ADMIN_EMAILS", "").split(",")
                  if item.strip()}
        admins.add(email)
        monkeypatch.setenv("NYAYAFLOW_GEO_ADMIN_EMAILS", ",".join(sorted(admins)))
        return user

    return create
