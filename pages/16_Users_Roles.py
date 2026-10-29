import pandas as pd
import streamlit as st

from core.auth import ROLES
from core.config import SIM_LABEL
from core.db import fetch_all
from core.ui import apply_demo_style, render_hero, require_permission

user = require_permission("can_audit")
apply_demo_style()
render_hero("Technical review", "Users & roles", "Read-only view of the permission matrix and synthetic account totals.")
st.warning(SIM_LABEL)
st.caption("Role enforcement is checked in server-side services. This page does not expose personal account details or allow role changes.")

actions = sorted({action for permissions in ROLES.values() for action in permissions})
matrix = [{"Role": role, **{action.replace("can_", "").replace("_", " ").title(): bool(policy.get(action, False))
                            for action in actions}
          } for role, policy in sorted(ROLES.items())]
st.dataframe(pd.DataFrame(matrix), hide_index=True, width="stretch")
counts = fetch_all("SELECT role,COUNT(*) AS accounts,SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active "
                   "FROM users GROUP BY role ORDER BY role")
st.subheader("Registered accounts")
if counts:
    st.dataframe(pd.DataFrame(counts), hide_index=True, width="stretch")
else:
    st.info("No registered accounts are available.")
st.caption("Staff roles are assigned by the trusted synthetic directory during enrollment. Public users cannot select a government role.")
