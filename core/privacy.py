"""Conservative masking for common Indian phone numbers, emails, and named contacts."""
import re

PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")
PERSON = re.compile(
    r"(?i)(\b(?:my name is|name is|contact|call|mr\.?|mrs\.?|ms\.?|shri|smt\.?)\s+)"
    r"([A-Z][a-z]{1,30}(?:\s+[A-Z][a-z]{1,30}){0,2})"
)
PROPER_NAME = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2}\b")
KNOWN_PLACES = {
    "thatipur", "morar", "hazira", "dd nagar", "kampoo", "phool bagh", "maharaj bada",
    "jayendraganj", "gole ka mandir", "jhansi road", "tansen road", "sirol road",
    "city centre", "station road", "civil lines", "central park", "bus stop", "bus stand",
}


def mask_text(text: str) -> str:
    text = PHONE.sub(lambda m: "XXXXXX" + re.sub(r"\D", "", m.group(0))[-4:], text or "")
    text = EMAIL.sub(lambda m: "***@" + m.group(1), text)
    text = PERSON.sub(lambda m: m.group(1) + "[NAME REDACTED]", text)
    return PROPER_NAME.sub(lambda m: m.group(0) if m.group(0).casefold() in KNOWN_PLACES else "[NAME REDACTED]", text)
