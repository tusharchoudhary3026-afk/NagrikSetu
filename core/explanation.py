"""Deterministic explanations grounded in complaint wording and sourced owner rules."""
import re

import pandas as pd

from .config import RESP_TABLE


def load_responsibility_table():
    return pd.read_csv(RESP_TABLE, encoding="utf-8-sig").fillna("")


def generate_grounded_explanation(complaint_text: str, suggested_dept: str) -> dict:
    if not (complaint_text or "").strip() or not (suggested_dept or "").strip():
        raise ValueError("Complaint text and a suggested department are required.")
    table = load_responsibility_table()
    required = {"issue_type", "owner", "source", "verification"}
    if not required.issubset(table.columns):
        raise ValueError("The responsibility table is missing source or owner fields.")
    rules = table[table["owner"].astype(str).str.casefold() == suggested_dept.casefold()]
    text = complaint_text.casefold()
    for _, rule in rules.iterrows():
        phrases = [phrase.strip() for phrase in re.split(r"[/,;]", str(rule["issue_type"])) if phrase.strip()]
        matched = [phrase for phrase in phrases
                   if re.search(r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)", text)]
        if matched:
            source = str(rule["source"]).strip()
            if not source:
                raise ValueError("The matching ownership rule has no traceable source.")
            return {
                "suggested_department": suggested_dept,
                "grounded_keywords": matched,
                "issue_type": str(rule["issue_type"]),
                "rule_source": source,
                "verification": str(rule["verification"] or "UNKNOWN"),
                "trust_status": "GROUNDED_ASSUMPTION" if str(rule["verification"]).upper() == "ASSUMPTION" else "GROUNDED_RULE",
            }
    raise ValueError("No phrase in the responsibility table supports this department from the complaint text.")
