"""NagrikSetu setup: run once from the project root (the folder that contains data/).
    python setup_nyayaflow.py
Writes all code files to the right places and removes misnamed / misplaced files.
Does NOT touch anything inside data/."""
import os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
FILES = {}
FILES['app.py'] = r'''import streamlit as st
from core.db import init_db, fetch_all
from core.config import SIM_LABEL

st.set_page_config(page_title="NagrikSetu", layout="wide")
init_db()

st.title("NagrikSetu")
st.caption("Explainable grievance routing and accountability assistant")
st.warning(SIM_LABEL)

n = fetch_all("SELECT COUNT(*) AS n FROM complaints")[0]["n"]
open_ch = fetch_all("SELECT COUNT(*) AS n FROM challenges WHERE status='open'")[0]["n"]
c1, c2 = st.columns(2)
c1.metric("Complaints (synthetic)", n)
c2.metric("Open challenges", open_ch)

st.markdown("""
**Pages (left sidebar)**
1. **Intake** - enter a complaint, extract fields, propose a split, get suggestions
2. **Review** - accept / edit / clarify / escalate, with the append-only ledger
3. **Challenge** - staff challenge and citizen request-review
4. **Evaluation** - baseline results with sample sizes

**Ground rules:** nothing is auto-closed, auto-rejected or auto-merged. A human decides.
""")
'''
FILES['requirements.txt'] = r'''streamlit>=1.35
pandas>=2.0
scikit-learn>=1.4
'''
FILES['README.md'] = r'''# NagrikSetu
Explainable grievance routing with abstention, human review and an append-only ledger.
All data is SYNTHETIC. Nothing is auto-closed, auto-rejected or auto-merged.

## Run
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python scripts/init_db.py
    python scripts/evaluate.py        # baseline on the test split
    streamlit run app.py

## Structure
- core/    engines (intake, splitter, routers, ownership, ledger, db)
- pages/   Streamlit screens (Intake, Review, Challenge, Evaluation)
- db/      schema.sql (ledger is append-only via triggers)
- data/    responsibility table, keywords, complaints, dataset card (replace samples with your data)
- docs/    AI log, decision index

## First TODOs
1. Replace data/responsibility_table.csv with rules from ONE city's citizen charter (add URL + date).
2. Write 80-100 complaints in data/complaints.csv; a teammate labels them; freeze the test split.
3. Run scripts/evaluate.py and save the failure list.
4. Then wire in core/router_ml.py and choose the confidence threshold on the validation split.
'''
FILES['.gitignore'] = r'''__pycache__/
*.pyc
db/nyayaflow.db
.venv/
'''
FILES['core/__init__.py'] = ''
FILES['core/config.py'] = r'''from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "nyayaflow.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
RESP_TABLE = ROOT / "data" / "responsibility_table.csv"
KEYWORDS = ROOT / "data" / "keywords.csv"
COMPLAINTS = ROOT / "data" / "complaints.csv"

REASON_CODES = ["wrong_category", "missing_info", "overlapping_ownership", "duplicate_report", "other"]
REVIEW_ACTIONS = ["accept", "edit", "clarify", "escalate"]
REASON_REQUIRED = {"edit", "escalate"}

# Team sets this on a validation split (see scripts/evaluate.py). Placeholder only.
CONFIDENCE_THRESHOLD = 0.40

SIM_LABEL = "SIMULATED / SYNTHETIC DATA - not real municipal data"
'''
FILES['core/db.py'] = r'''import json
import sqlite3
from .config import DB_PATH, SCHEMA_PATH


def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


def insert_complaint(rec: dict) -> int:
    cols = ["case_id", "parent_id", "original_text", "language", "normalized_text",
            "channel", "location", "issue", "requested_action", "missing_fields", "is_synthetic"]
    vals = [rec.get(k) for k in cols]
    conn = get_conn()
    cur = conn.execute(
        f"INSERT INTO complaints ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def insert_suggestion(complaint_id, method, top3, evidence, confidence, abstained):
    conn = get_conn()
    conn.execute(
        "INSERT INTO suggestions (complaint_id, method, top3, evidence, confidence, abstained) "
        "VALUES (?,?,?,?,?,?)",
        (complaint_id, method, json.dumps(top3), json.dumps(evidence), confidence, int(abstained)))
    conn.commit()
    conn.close()


def execute(sql, params=()):
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql, params=()):
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows
'''
FILES['core/intake.py'] = r'''"""Engine 1: intake + extraction. Rule-based. Never invents missing facts."""
import re

HINGLISH_WORDS = {"nahi", "hai", "hain", "pe", "par", "mein", "me", "ka", "ki", "ke", "aur", "bhi",
                  "paani", "pani", "sadak", "kachra", "bijli", "nali", "gali", "kab", "kyun"}
NORMALIZE = {"pani": "paani", "sadak": "road", "kachra": "garbage", "bijli": "electricity",
             "nali": "drain", "gali": "lane"}
LOCATION_PATTERNS = [
    r"ward\s*(?:no\.?|number)?\s*\d+",
    r"(?:near|nearby|paas)\s+[A-Za-z\u0900-\u097F ]{3,30}",
    r"[A-Za-z\u0900-\u097F]+(?: [A-Za-z\u0900-\u097F]+)?\s+(?:road|marg|chowk|colony|nagar|lane)",
]
REQUIRED_FIELDS = ["location", "issue"]


def detect_language(text: str) -> str:
    has_dev = bool(re.search(r"[\u0900-\u097F]", text))
    words = set(re.findall(r"[a-z]+", text.lower()))
    hing = len(words & HINGLISH_WORDS)
    if has_dev and words:
        return "uncertain"          # mixed script: a human decides
    if has_dev:
        return "hindi"
    if hing >= 2:
        return "hinglish"
    if words and hing == 0:
        return "english"
    return "uncertain"


def normalize(text: str) -> str:
    """Stored in a SEPARATE field. The original text is never touched."""
    words = re.findall(r"\S+", text.lower())
    return " ".join(NORMALIZE.get(w.strip(".,!?"), w) for w in words)


VAGUE = re.compile(r"\b(my|our|the|this|that|your|mere|meri|mere ghar)\b|\b(house|home|ghar)\b", re.I)


def extract_location(text: str) -> str:
    for p in LOCATION_PATTERNS:
        m = re.search(p, text, flags=re.I)
        if m and not VAGUE.search(m.group(0)):   # "near my house" is not a usable location
            return m.group(0).strip()
    return "unknown"                # never invent


def extract_issue(text: str) -> str:
    return text.strip().split(".")[0][:120]   # TODO: replace with keyword-based issue label


def process(text: str, channel: str = "portal", location_hint: str | None = None) -> dict:
    loc = location_hint.strip() if location_hint and location_hint.strip() else extract_location(text)
    rec = {
        "original_text": text,
        "language": detect_language(text),
        "normalized_text": normalize(text),
        "channel": channel,
        "location": loc,
        "issue": extract_issue(text),
        "requested_action": None,        # TODO: extract (e.g. 'repair', 'clean', 'inspect')
        "is_synthetic": 1,
    }
    missing = [f for f in REQUIRED_FIELDS if not rec.get(f) or rec[f] == "unknown"]
    rec["missing_fields"] = ",".join(missing)
    return rec


def clarification_question(rec: dict) -> str | None:
    """One targeted question only."""
    if "location" in (rec.get("missing_fields") or ""):
        return "Which ward, street or nearby landmark is this about?"
    if "issue" in (rec.get("missing_fields") or ""):
        return "Can you describe the problem in one sentence?"
    return None
'''
FILES['core/ledger.py'] = r'''"""Append-only decision ledger. Corrections ADD rows; old rows are never changed."""
import json
from .config import REASON_REQUIRED
from .db import execute, fetch_all


def log_event(complaint_id, event_type, actor, suggested_dept=None, final_dept=None,
              reason=None, reason_code=None, details=None):
    if event_type in REASON_REQUIRED and not (reason or "").strip():
        raise ValueError(f"A reason is mandatory for '{event_type}'.")
    execute(
        "INSERT INTO ledger (complaint_id, event_type, actor, suggested_dept, final_dept, "
        "reason, reason_code, details) VALUES (?,?,?,?,?,?,?,?)",
        (complaint_id, event_type, actor, suggested_dept, final_dept, reason, reason_code,
         json.dumps(details) if details else None))


def history(complaint_id):
    return fetch_all("SELECT * FROM ledger WHERE complaint_id=? ORDER BY id", (complaint_id,))


def save_correction(complaint_id, text, wrong_dept, correct_dept):
    """Stored as a labelled example only. No automatic retraining."""
    execute("INSERT INTO corrections (complaint_id, text, wrong_dept, correct_dept) VALUES (?,?,?,?)",
            (complaint_id, text, wrong_dept, correct_dept))
'''
FILES['core/ownership.py'] = r'''"""Engine 6: ownership-conflict checker. Flags overlap; never decides."""
import pandas as pd
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
'''
FILES['core/router_baseline.py'] = r'''"""Engine 3: keyword/rule baseline. Build and evaluate this BEFORE any ML."""
import pandas as pd
from .config import KEYWORDS, CONFIDENCE_THRESHOLD


def load_keywords():
    df = pd.read_csv(KEYWORDS, encoding='utf-8-sig')
    out = {}
    for _, r in df.iterrows():
        out.setdefault(r["department"], []).append(str(r["keyword"]).lower())
    return out


def route(text: str, kw=None):
    kw = kw or load_keywords()
    t = text.lower()
    scores, evidence = {}, {}
    for dept, words in kw.items():
        hits = [w for w in words if w in t]
        if hits:
            scores[dept] = len(hits)
            evidence[dept] = hits
    if not scores:
        return {"top3": [], "evidence": {}, "confidence": 0.0, "abstained": True}
    total = sum(scores.values())
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:3]
    top3 = [{"dept": d, "score": round(s / total, 2)} for d, s in ranked]
    conf = top3[0]["score"]
    tie = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
    abstained = conf < CONFIDENCE_THRESHOLD or tie
    return {"top3": top3, "evidence": {d: evidence[d] for d, _ in ranked},
            "confidence": conf, "abstained": abstained}
'''
FILES['core/router_ml.py'] = r'''"""Engine 3: TF-IDF + Logistic Regression. TODO after the baseline is evaluated."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from .config import CONFIDENCE_THRESHOLD


class TfidfRouter:
    def __init__(self):
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self.clf = LogisticRegression(max_iter=1000)

    def fit(self, texts, labels):
        self.clf.fit(self.vec.fit_transform(texts), labels)
        return self

    def route(self, text, threshold=CONFIDENCE_THRESHOLD):
        X = self.vec.transform([text])
        probs = self.clf.predict_proba(X)[0]
        order = probs.argsort()[::-1][:3]
        top3 = [{"dept": self.clf.classes_[i], "score": round(float(probs[i]), 2)} for i in order]
        names = self.vec.get_feature_names_out()
        nz = X.nonzero()[1]
        evidence = {"matched_terms": [names[i] for i in nz][:8]}   # grounded in the input text
        conf = top3[0]["score"]          # NOT assumed calibrated
        return {"top3": top3, "evidence": evidence, "confidence": conf, "abstained": conf < threshold}
'''
FILES['core/splitter.py'] = r'''"""Engine 2: compound complaint splitter. Proposes only. A human confirms or merges back."""
import re
from . import router_baseline

CONNECTORS = r"\band\b|\baur\b|(?<!\S)और(?!\S)|\bplus\b|;|\.\s+(?=[A-Z\u0900-\u097F])"


def propose_split(text: str):
    parts = [p.strip() for p in re.split(CONNECTORS, text, flags=re.I) if p and len(p.strip()) > 8]
    if len(parts) < 2:
        return {"is_compound": False, "parts": [], "note": "single issue"}
    kw = router_baseline.load_keywords()
    routed = [(p, router_baseline.route(p, kw)) for p in parts]
    depts = {r["top3"][0]["dept"] for _, r in routed if r["top3"]}
    # Parts that map to one department, or have no signal, are NOT split.
    if len(depts) < 2:
        return {"is_compound": False, "parts": [],
                "note": "possible multi-clause text but one owner or unclear; kept intact"}
    return {"is_compound": True,
            "parts": [{"text": p, "suggestion": r} for p, r in routed],
            "note": "proposed split; needs human confirmation"}
'''
FILES['pages/1_Intake.py'] = r'''import uuid
import streamlit as st
from core import intake, splitter, router_baseline, ownership
from core.db import init_db, insert_complaint, insert_suggestion
from core.ledger import log_event
from core.config import SIM_LABEL

init_db()
st.title("1. Intake")
st.warning(SIM_LABEL)

text = st.text_area("Complaint (Hindi / English / Hinglish)", height=120)
channel = st.selectbox("Channel", ["portal", "phone", "social", "in-person"])
loc_hint = st.text_input("Location (optional, staff-assisted)")

if st.button("Process") and text.strip():
    rec = intake.process(text, channel, loc_hint)
    st.session_state["rec"] = rec
    st.session_state["split"] = splitter.propose_split(text)
    st.session_state["route"] = router_baseline.route(text)

if "rec" in st.session_state:
    rec, sp, rt = st.session_state["rec"], st.session_state["split"], st.session_state["route"]
    st.subheader("Extracted")
    st.json({k: v for k, v in rec.items() if k != "original_text"})
    q = intake.clarification_question(rec)
    if q:
        st.info(f"Clarification question: {q}")

    st.subheader("Suggestion (baseline)")
    if rt["abstained"]:
        st.error("Not sure -> manual review queue")
    for t in rt["top3"]:
        st.write(f"- {t['dept']} ({t['score']})  evidence: {rt['evidence'].get(t['dept'])}")
        for o in ownership.check(t["dept"]):
            st.warning(f"Possible overlap with {o['overlap_owner']} ({o['issue_type']}). "
                       f"Source: {o['source']} [{o['verification']}]")

    st.subheader("Split proposal")
    st.write(sp["note"])
    if sp["is_compound"]:
        for p in sp["parts"]:
            st.write(f"- {p['text']} -> {[x['dept'] for x in p['suggestion']['top3'][:1]]}")

    if st.button("Save to review queue"):
        rec["case_id"] = f"CASE-{uuid.uuid4().hex[:6].upper()}"
        cid = insert_complaint(rec)
        insert_suggestion(cid, "baseline", rt["top3"], rt["evidence"], rt["confidence"], rt["abstained"])
        top = rt["top3"][0]["dept"] if rt["top3"] else None
        log_event(cid, "suggested", "system", suggested_dept=top,
                  details={"abstained": rt["abstained"], "confidence": rt["confidence"]})
        st.success(f"Saved as {rec['case_id']}")
        # TODO: if sp["is_compound"] and a human confirms, insert sub-issues with parent_id=cid and the same case_id
'''
FILES['pages/2_Review.py'] = r'''import json
import streamlit as st
from core.db import init_db, fetch_all
from core.ledger import log_event, history, save_correction
from core.config import REASON_CODES, REVIEW_ACTIONS, SIM_LABEL
from core import ownership

init_db()
st.title("2. Human Review")
st.warning(SIM_LABEL)

rows = fetch_all("SELECT id, case_id, language, original_text FROM complaints ORDER BY id DESC")
if not rows:
    st.info("No complaints yet. Use Intake first.")
    st.stop()

pick = st.selectbox("Complaint", rows,
                    format_func=lambda r: f"{r['case_id']} | {r['language']} | {r['original_text'][:50]}")
st.write("**Original text:**", pick["original_text"])

sug = fetch_all("SELECT * FROM suggestions WHERE complaint_id=? ORDER BY id DESC LIMIT 1", (pick["id"],))
suggested = None
if sug:
    top3 = json.loads(sug[0]["top3"])
    suggested = top3[0]["dept"] if top3 else None
    st.write("**Suggestion:**", top3, "| confidence:", sug[0]["confidence"],
             "| abstained:", bool(sug[0]["abstained"]))

action = st.radio("Action", REVIEW_ACTIONS, horizontal=True)
final = st.text_input("Final department", value=suggested or "")
reason = st.text_area("Reason (mandatory for edit / escalate)")
code = st.selectbox("Transfer-reason code", REASON_CODES)

if st.button("Submit decision"):
    try:
        log_event(pick["id"], action, "reviewer", suggested_dept=suggested, final_dept=final or None,
                  reason=reason, reason_code=code if action in ("edit", "escalate") else None)
        if action == "edit" and suggested and final != suggested:
            save_correction(pick["id"], pick["original_text"], suggested, final)  # labelled example only
        st.success("Logged. Previous entries are untouched.")
    except ValueError as e:
        st.error(str(e))

st.subheader("Ledger (append-only)")
h = history(pick["id"])
st.dataframe(h)
b = ownership.detect_bounce(h)
if b:
    st.warning(f"Transfer pattern flagged (no blame): {b['pattern']}")
'''
FILES['pages/3_Challenge.py'] = r'''import streamlit as st
from core.db import init_db, fetch_all, execute
from core.ledger import log_event
from core.config import SIM_LABEL

init_db()
st.title("3. Challenge / Request review")
st.warning(SIM_LABEL)

rows = fetch_all("SELECT id, case_id, original_text FROM complaints ORDER BY id DESC")
if not rows:
    st.info("No complaints yet.")
    st.stop()

st.subheader("Raise a challenge")
pick = st.selectbox("Case", rows, format_func=lambda r: f"{r['case_id']} | {r['original_text'][:50]}")
who = st.radio("Raised by", ["staff", "citizen"], horizontal=True)
why = st.text_area("Why is this routing wrong?")
if st.button("Submit challenge") and why.strip():
    execute("INSERT INTO challenges (complaint_id, raised_by, reason) VALUES (?,?,?)",
            (pick["id"], who, why))
    log_event(pick["id"], "challenge", who, reason=why)
    st.success("Sent to the review queue.")

st.subheader("Open challenges")
for ch in fetch_all("SELECT * FROM challenges WHERE status='open'"):
    st.write(f"#{ch['id']} (case {ch['complaint_id']}, by {ch['raised_by']}): {ch['reason']}")
    note = st.text_input("Resolution note", key=f"n{ch['id']}")
    if st.button("Resolve", key=f"r{ch['id']}") and note.strip():
        execute("UPDATE challenges SET status='resolved' WHERE id=?", (ch["id"],))
        log_event(ch["complaint_id"], "challenge_resolved", "reviewer", reason=note)
        st.rerun()
'''
FILES['pages/4_Evaluation.py'] = r'''import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import streamlit as st
from scripts.evaluate import run, summary
from core.config import SIM_LABEL

st.title("4. Evaluation")
st.error(SIM_LABEL)
st.caption("Baseline on the frozen test split. Numerator/denominator reported; small n means preliminary.")

split = st.selectbox("Split", ["test", "val", "train"])
if st.button("Run baseline"):
    out = run(split)
    st.code(summary(out))
    st.subheader("Failures and abstentions")
    st.dataframe(out[out.outcome != "correct"])
# TODO: TF-IDF vs baseline table, coverage-vs-accuracy curve, language gap with confidence intervals
'''
FILES['scripts/__init__.py'] = ''
FILES['scripts/evaluate.py'] = r'''"""Baseline evaluation on the frozen test split.
Single-owner rows: accuracy on answered + abstentions.  UNCLEAR rows: correct = abstain.
MULTI rows: correct = splitter flags compound.  Always report numerator/denominator."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pandas as pd
from core.config import COMPLAINTS, ROOT
from core import router_baseline, splitter


def run(split="test", save_failures=False):
    df = pd.read_csv(COMPLAINTS, encoding="utf-8-sig")
    df = df[df["split"] == split]
    kw = router_baseline.load_keywords()
    rows = []
    for _, r in df.iterrows():
        res = router_baseline.route(r["text"], kw)
        pred = None if res["abstained"] else res["top3"][0]["dept"]
        flagged = splitter.propose_split(r["text"])["is_compound"]
        label = r["owner_label"]
        kind = "compound" if label == "MULTI" else "unclear" if label == "UNCLEAR" else "single"
        if kind == "single":
            outcome = "abstained" if pred is None else ("correct" if pred == label else "wrong")
        elif kind == "unclear":
            outcome = "correct" if pred is None else "wrong"          # should abstain
        else:
            outcome = "correct" if flagged else "wrong"               # should flag compound
        rows.append({"id": r["id"], "text": r["text"], "language": r["language"], "kind": kind,
                     "label": label, "pred": pred, "split_flagged": flagged,
                     "overlap": r.get("has_overlap", 0), "outcome": outcome})
    out = pd.DataFrame(rows)
    if save_failures:
        fails = out[out.outcome != "correct"]
        fails.to_csv(ROOT / "docs" / "baseline_failures.csv", index=False, encoding="utf-8-sig")
    return out


def summary(out):
    lines = [f"Rows: {len(out)}"]
    s = out[out.kind == "single"]
    ans = s[s.outcome != "abstained"]
    lines.append(f"Single-owner: {(s.outcome=='correct').sum()}/{len(s)} correct overall, "
                 f"{(ans.outcome=='correct').sum()}/{len(ans)} correct when answered, "
                 f"{(s.outcome=='abstained').sum()}/{len(s)} abstained")
    u = out[out.kind == "unclear"]
    lines.append(f"Unclear: {(u.outcome=='correct').sum()}/{len(u)} correctly abstained")
    c = out[out.kind == "compound"]
    lines.append(f"Compound: {(c.outcome=='correct').sum()}/{len(c)} flagged as multi-issue")
    fs = s[s.split_flagged]
    lines.append(f"False splits on single-issue rows: {len(fs)}/{len(s)}")
    lines.append("By language (single-owner, correct/n):")
    for lang, g in s.groupby("language"):
        lines.append(f"  {lang}: {(g.outcome=='correct').sum()}/{len(g)} "
                     f"(wrong {(g.outcome=='wrong').sum()}, abstained {(g.outcome=='abstained').sum()})")
    lines.append("SIMULATED / SYNTHETIC data. Small n: preliminary only.")
    return "\n".join(lines)


if __name__ == "__main__":
    o = run("test", save_failures=True)
    print(summary(o))
    print("\nFailures saved to docs/baseline_failures.csv")
'''
FILES['scripts/init_db.py'] = r'''import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from core.db import init_db
from core.config import DB_PATH

init_db()
print(f"Database ready: {DB_PATH}")
'''
FILES['db/schema.sql'] = r'''-- NagrikSetu schema. All demo data is SYNTHETIC.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS complaints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL,              -- shared by parent + sub-issues
    parent_id       INTEGER REFERENCES complaints(id),  -- NULL for the original complaint
    original_text   TEXT NOT NULL,              -- NEVER modified
    language        TEXT NOT NULL,              -- english | hindi | hinglish | uncertain
    normalized_text TEXT,                       -- separate field, Hinglish normalisation
    channel         TEXT DEFAULT 'portal',      -- portal | phone | social | in-person
    location        TEXT DEFAULT 'unknown',     -- never invented
    issue           TEXT,
    requested_action TEXT,
    missing_fields  TEXT,                       -- comma-separated
    is_synthetic    INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suggestions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id),
    method        TEXT NOT NULL,                -- baseline | tfidf_lr
    top3          TEXT NOT NULL,                -- JSON: [{dept, score}]
    evidence      TEXT,                         -- JSON: matched words / rules
    confidence    REAL,
    abstained     INTEGER NOT NULL DEFAULT 0,   -- 1 = manual queue
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only decision ledger (see triggers below)
CREATE TABLE IF NOT EXISTS ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id    INTEGER NOT NULL REFERENCES complaints(id),
    event_type      TEXT NOT NULL,   -- suggested | accept | edit | clarify | escalate | challenge | challenge_resolved | transfer
    actor           TEXT NOT NULL,   -- system | operator | reviewer | citizen
    suggested_dept  TEXT,
    final_dept      TEXT,
    reason          TEXT,            -- mandatory on edit / escalate / transfer
    reason_code     TEXT,            -- wrong_category | missing_info | overlapping_ownership | duplicate_report | other
    details         TEXT,            -- JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TABLE IF NOT EXISTS challenges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id),
    raised_by     TEXT NOT NULL,             -- staff | citizen
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Corrections saved as labelled examples (NO automatic retraining)
CREATE TABLE IF NOT EXISTS corrections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    text         TEXT NOT NULL,
    wrong_dept   TEXT,
    correct_dept TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
'''
FILES['docs/ai_log.md'] = r'''# AI Log (keep updating from day 1)
| Date | Tool | Prompt / link | Output summary | Accepted / Changed / Rejected | Verification | Reason |
|---|---|---|---|---|---|---|
| 2026-10-13 | Claude | 'Create Gwalior-setting synthetic dataset and review the labels yourself' | 96 complaints, responsibility table, keywords, 2nd-pass label audit; rebalanced test split (Drainage was 9/27) | Accepted | Structural checks run in Python; semantic labels NOT human-verified | Team chose to rely on AI labelling; disclosed in dataset card |
'''
FILES['docs/decision_index.md'] = r'''# Decision Index
| # | Decision | Alternatives rejected | Evidence label (CASE/EXTERNAL/ASSUMPTION/UNKNOWN) | Owner |
|---|---|---|---|---|
'''

# misnamed / misplaced files to remove (safe: only these exact names)
REMOVE = ["core/app.py", "core/requirements.txt",
          "pages/Challenge.py", "pages/Evaluation.py", "pages/Intake.py", "pages/Review.py",
          "pages/_init_py", "pages/__init__.py",
          "core/_init_py", "scripts/_init_py", "data/_init_py", "db/_init_py", "docs/_init_py",
          "docs/__init__.py", "data/__init__.py", "db/__init__.py", "_init_py"]

for rel, content in FILES.items():
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print("wrote", rel)
for rel in REMOVE:
    p = ROOT / rel
    if p.exists():
        p.unlink()
        print("removed", rel)
print("\nDone. Next: pip install -r requirements.txt  ->  python scripts/init_db.py  ->  python scripts/evaluate.py  ->  streamlit run app.py")
