"""Engine 1: intake + extraction. Rule-based. Never invents missing facts."""
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
ISSUE_CATEGORIES = [
    ("Drainage", ("waterlogging", "water logged", "blocked drain", "drain", "nali", "नाली", "sewer", "सीवर", "manhole", "मैनहोल", "paani bhara", "पानी भरा")),
    ("Electricity", ("streetlight", "street light", "electric wire", "live wire", "hanging wire", "bijli", "बिजली", "स्ट्रीटलाइट", "बिजली का तार")),
    ("Sanitation", ("garbage", "waste", "kachra", "कचरा", "dustbin", "dead animal", "toilet", "कूड़ेदान")),
    ("Water supply", ("water supply", "tap", "pipeline", "pipe leak", "paani", "पानी", "नल", "पाइपलाइन")),
    ("Road damage", ("pothole", "road", "footpath", "sadak", "gadda", "गड्ढा", "सड़क", "फुटपाथ")),
]
ISSUE_CLUES = {term for _, terms in ISSUE_CATEGORIES for term in terms}


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
    lowered = (text or "").casefold()
    for category, terms in ISSUE_CATEGORIES:
        if any(term.casefold() in lowered for term in terms):
            return category
    return "unknown"


def extract_requested_action(text: str) -> str | None:
    actions = [("repair", ("repair", "fix", "theek karo", "मरम्मत")),
               ("clean", ("clean", "remove garbage", "safai", "सफाई")),
               ("clear", ("clear", "unblock", "saaf", "खोलें")),
               ("inspect", ("inspect", "check", "jaancha", "जांच"))]
    lowered = (text or "").casefold()
    return next((action for action, phrases in actions if any(p.casefold() in lowered for p in phrases)), None)


def process(text: str, channel: str = "portal", location_hint: str | None = None) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Complaint text cannot be empty.")
    if channel not in {"portal", "phone", "social", "in-person"}:
        raise ValueError("Choose a supported intake channel.")
    loc = location_hint.strip() if location_hint and location_hint.strip() else extract_location(text)
    rec = {
        "original_text": text,
        "language": detect_language(text),
        "normalized_text": normalize(text),
        "channel": channel,
        "location": loc,
        "issue": extract_issue(text),
        "requested_action": extract_requested_action(text),
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
