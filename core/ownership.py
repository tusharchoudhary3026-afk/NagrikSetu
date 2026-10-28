"""Engine 6: ownership-conflict checker. Flags overlap; never decides."""
import pandas as pd
import re
from .config import RESP_TABLE


def load_table():
    return pd.read_csv(RESP_TABLE, encoding='utf-8-sig')


def check(dept: str, table=None):
    t = table if table is not None else load_table()
    out = []
    for _, r in t[t["owner"] == dept].iterrows():
        if isinstance(r["overlap_owner"], str) and r["overlap_owner"].strip():
            out.append({"issue_type": r["issue_type"], "owner": r["owner"],
                        "overlap_owner": r["overlap_owner"], "source": r["source"],
                        "verification": r["verification"]})
    return out


def check_suggestions(departments: list[str], complaint_text: str, table=None):
    """Return only sourced overlap rules whose issue wording occurs in the complaint."""
    t = table if table is not None else load_table()
    chosen = {str(dept).strip().casefold() for dept in departments}
    text = (complaint_text or "").casefold()
    out = []
    for _, row in t.iterrows():
        owner = str(row.get("owner", "")).strip()
        other = str(row.get("overlap_owner", "")).strip()
        if not owner or not other or owner.casefold() not in chosen or other.casefold() not in chosen:
            continue
        phrases = [p.strip() for p in re.split(r"[/,;]", str(row.get("issue_type", ""))) if p.strip()]
        matched = []
        for phrase in phrases:
            terms = [word for word in re.findall(r"[\w\u0900-\u097f]+", phrase.casefold())
                     if len(word) > 2 and word not in {"the", "on", "and", "for", "with"}]
            if terms and all(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text) for word in terms):
                matched.append(phrase)
        if matched:
            out.append({"owner": owner, "overlap_owner": other, "issue_type": str(row["issue_type"]),
                        "source": str(row.get("source", "")),
                        "verification": str(row.get("verification", "UNKNOWN")),
                        "matched_phrases": matched})
    return out


def detect_bounce(history: list[dict]):
    """Pattern flag only (A -> B -> A), no blame."""
    seq = []
    for h in history:
        if not seq and h.get("suggested_dept"):
            seq.append(h["suggested_dept"])            # starting owner
        if h.get("final_dept") and (not seq or seq[-1] != h["final_dept"]):
            seq.append(h["final_dept"])
    for i in range(len(seq) - 2):
        if seq[i] == seq[i + 2] and seq[i] != seq[i + 1]:
            return {"pattern": f"{seq[i]} -> {seq[i+1]} -> {seq[i+2]}"}
    return None


def repeat_reassignment(history: list[dict]):
    """Flag two or more owner changes in the ledger without assigning fault."""
    seq = []
    for row in history:
        for key in ("suggested_dept", "final_dept"):
            dept = row.get(key)
            if dept and (not seq or seq[-1] != dept):
                seq.append(dept)
    moves = max(0, len(seq) - 1)
    if moves < 2:
        return None
    return {"moves": moves, "path": " -> ".join(seq)}
