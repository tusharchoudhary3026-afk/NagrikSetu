"""Small validation boundary for optional browser-generated speech transcripts."""


def validate_transcript_submission(text: str, speech_used: bool, confirmed: bool) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter a complaint first.")
    from .config import feature_enabled
    if speech_used and not feature_enabled("voice"):
        raise PermissionError("Voice intake is disabled by configuration. Type the complaint instead.")
    if speech_used and not confirmed:
        raise ValueError("Review and confirm the speech transcript before processing it.")
    # Validate emptiness without changing the citizen's entered text. Normalized
    # text belongs in its separate field; original_text must remain byte-for-byte.
    return text
