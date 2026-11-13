"""Chord / section-heading recognition."""
from __future__ import annotations

import re

_ROOT = r"[A-G][#b♯♭]?"
_QUALITY = (
    r"(?:maj|min|dim|aug|sus|add|m|M|mi|ma|\+|°|ø|-)?"
)
_EXT = r"(?:\d{1,2}|sus\d?|add\d{1,2}|maj\d{1,2}|[#b♯♭+\-]\d{1,2}|\([^)\s]*\))*"
CHORD_RE = re.compile(rf"^{_ROOT}{_QUALITY}{_EXT}(?:/{_ROOT})?$")
# Tokens that may sit on a chord line without being chords themselves.
NEUTRAL = {"|", "||", "/", "-", "%", "N.C.", "NC", "x2", "x3", "x4", "(x2)", "(x3)", "(x4)", "2x", "3x", "4x"}

SECTION_RE = re.compile(
    r"^\[?\s*(verse|chorus|pre[- ]?chorus|bridge|intro|outro|interlude|instrumental|"
    r"tag|refrain|ending|turnaround|coda|vamp|solo|hook|breakdown|channel|"
    r"pre|v|ch)\s*\d*\s*\]?\s*(\(.*\))?\s*:?$",
    re.I,
)


def is_chord(tok: str) -> bool:
    return bool(CHORD_RE.match(tok))


def is_chord_line(tokens: list[str]) -> bool:
    if not tokens:
        return False
    real = 0
    for t in tokens:
        if is_chord(t):
            real += 1
        elif t not in NEUTRAL:
            return False
    return real > 0


def section_label(text: str) -> str | None:
    """Return a tidy label ('Verse 1') if `text` is a section heading."""
    t = text.strip()
    if len(t) < 2 or not SECTION_RE.match(t):
        return None
    t = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", t.strip("[]: ").strip())   # "VERSE1" -> "VERSE 1"
    return re.sub(r"\s+", " ", t).title() if t.isupper() or t.islower() else re.sub(r"\s+", " ", t)
