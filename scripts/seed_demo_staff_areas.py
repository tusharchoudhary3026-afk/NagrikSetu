"""Explicitly seed audited city-wide assignments for the three demo staff users."""
from core.db import init_db
from core.geo import seed_demo_staff_assignments


def main() -> int:
    init_db()
    count = seed_demo_staff_assignments()
    print(f"Appended {count} demo staff area approval(s).")
    return count


if __name__ == "__main__":
    main()
