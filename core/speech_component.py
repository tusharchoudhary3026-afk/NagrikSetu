"""Registered Streamlit speech component shared with the intake page."""
from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "components" / "speech_input"
speech_input = components.declare_component(
    "nyayaflow_speech_input", path=str(_COMPONENT_DIR))
