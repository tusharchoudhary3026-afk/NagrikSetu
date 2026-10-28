"""Small validation boundary for optional browser-generated speech transcripts."""


def validate_transcript_submission(text: str, speech_used: bool, confirmed: bool) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Enter a complaint first.")
    if speech_used and not confirmed:
        raise ValueError("Review and confirm the speech transcript before processing it.")
    return cleaned
