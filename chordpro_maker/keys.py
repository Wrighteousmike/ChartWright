"""Key plausibility: flag chords that don't fit the key, as a second opinion on OCR'd chord letters.

The key is inferred per *section* (hymns modulate: your sample says "Key - C" but Verse 3 is in D); the key
declared in the header is only a tie-breaker. Nothing is changed automatically: unlikely chords become review
notes with a suggested in-key alternative (e.g. `A` -> `Am`, `Fb`-style slips, E <-> F).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm"}

_CHORD = re.compile(r"^([A-G])([#b♯♭]?)(.*?)(?:/([A-G])([#b♯♭]?))?$")

# (semitones above tonic, quality) — M major, m minor, d diminished
MAJOR_STRICT = {(0, "M"), (2, "m"), (4, "m"), (5, "M"), (7, "M"), (9, "m"), (11, "d")}
MAJOR_EXTRA = {(10, "M"), (3, "M"), (8, "M"), (5, "m"), (2, "M"), (4, "M"), (9, "M"), (11, "M"), (7, "m"), (0, "m"), (11, "m")}
MINOR_STRICT = {(0, "m"), (2, "d"), (3, "M"), (5, "m"), (7, "m"), (8, "M"), (10, "M")}
MINOR_EXTRA = {(7, "M"), (5, "M"), (0, "M"), (2, "m"), (1, "M"), (4, "M"), (11, "d"), (9, "d"), (3, "m"), (10, "m")}
MAJOR_ROOTS = {0, 2, 4, 5, 7, 9, 11}
MINOR_ROOTS = {0, 2, 3, 5, 7, 8, 10}


def parse_chord(tok: str):
    """-> (root_pc, quality, bass_pc|None, suffix) or None. quality: M m d a(ug) s(us)"""
    m = _CHORD.match(tok.replace("♯", "#").replace("♭", "b"))
    if not m:
        return None
    root = (PC[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)]) % 12
    rest = m.group(3)
    bass = None
    if m.group(4):
        bass = (PC[m.group(4)] + {"#": 1, "b": -1, "": 0}[m.group(5)]) % 12
    if "sus" in rest:
        q = "s"
    elif "dim" in rest or "°" in rest or "ø" in rest or "b5" in rest:
        q = "d"
    elif "aug" in rest or rest.startswith("+"):
        q = "a"
    elif rest.startswith(("maj", "ma", "M")):
        q = "M"
    elif rest.startswith(("m", "-")):
        q = "m"
    else:
        q = "M"
    return root, q, bass, rest


def parse_key(text: str):
    """'C', 'F#m', 'Bb', 'Am' -> (tonic_pc, is_minor) or None."""
    m = re.match(r"^\s*([A-G])([#b♯♭]?)\s*(m|min|minor)?\s*$", text or "")
    if not m:
        return None
    t = (PC[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2).replace("♯", "#").replace("♭", "b")]) % 12
    return t, bool(m.group(3))


def key_name(tonic: int, minor: bool) -> str:
    base = NAMES_FLAT[tonic] if (NAMES_FLAT[tonic] + ("m" if minor else "")) in FLAT_KEYS else NAMES_SHARP[tonic]
    return base + ("m" if minor else "")


def chord_name(pc: int, q: str, tonic: int, minor: bool) -> str:
    n = (NAMES_FLAT if (NAMES_FLAT[tonic] + ("m" if minor else "")) in FLAT_KEYS else NAMES_SHARP)[pc % 12]
    return n + {"M": "", "m": "m", "d": "dim", "a": "aug", "s": "sus4"}[q]


def _tables(minor: bool):
    return (MINOR_STRICT, MINOR_EXTRA, MINOR_ROOTS) if minor else (MAJOR_STRICT, MAJOR_EXTRA, MAJOR_ROOTS)


def _fit(ch, tonic: int, minor: bool) -> float:
    """1 = in key, 0.5 = common borrowed/secondary chord, 0 = doesn't fit."""
    root, q, bass, _ = ch
    strict, extra, roots = _tables(minor)
    deg = (root - tonic) % 12
    if q in ("s", "a"):
        return 1.0 if deg in roots else 0.0
    if (deg, q) in strict:
        return 1.0
    if (deg, q) in extra:
        return 0.5
    return 0.0


def best_key(chords: list, declared=None):
    """Most plausible key for these parsed chords -> (tonic, minor, fit_fraction). Declared key breaks ties."""
    best = None
    for tonic in range(12):
        for minor in (False, True):
            score = sum(_fit(c, tonic, minor) for c in chords)
            # tonic chord at the start/end is a strong clue
            for c in (chords[0], chords[-1]):
                if c[0] == tonic and c[1] == ("m" if minor else "M"):
                    score += 0.75
            if declared and declared == (tonic, minor):
                score += 0.4
            if not minor:
                score += 0.01             # prefer major on a dead heat
            if best is None or score > best[0]:
                best = (score, tonic, minor)
    _, tonic, minor = best
    fit = sum(_fit(c, tonic, minor) for c in chords) / len(chords)
    return tonic, minor, fit


def _suggest(ch, tonic: int, minor: bool) -> list[str]:
    """Plausible in-key replacements: same root with the key's quality, then neighbouring letters."""
    root, q, bass, rest = ch
    strict, _, _ = _tables(minor)
    out: list[str] = []
    # same root, quality the key expects (A -> Am in C)
    for (deg, qq) in sorted(strict):
        if (tonic + deg) % 12 == root and qq != q:
            out.append(chord_name(root, qq, tonic, minor) + (rest if qq in ("M", "m") and q in ("M", "m") and not rest.startswith(("m", "maj", "M")) else ""))
    # OCR letter slips: same quality, root one step away (E<->F, B<->C, C<->G ...)
    for d in (1, -1, 2, -2):
        r2 = (root + d) % 12
        for (deg, qq) in strict:
            if (tonic + deg) % 12 == r2 and qq == q:
                out.append(chord_name(r2, qq, tonic, minor) + (rest if q in ("M", "m") else ""))
    seen, res = set(), []
    for o in out:
        if o not in seen:
            seen.add(o); res.append(o)
    return res[:3]


def check_groups(groups: list[list[str]], declared_key: Optional[str] = None):
    """groups: chord symbols per section. Returns a list (per group) of dicts index -> info for chords to question.

    info = {"chord", "key", "suggestions", "why"}
    """
    declared = parse_key(declared_key) if declared_key else None
    results: list[dict] = []
    for g in groups:
        flags: dict = {}
        parsed = [(i, parse_chord(c)) for i, c in enumerate(g)]
        parsed = [(i, p) for i, p in parsed if p]
        if len(parsed) < 3:
            results.append(flags)
            continue
        chords = [p for _, p in parsed]
        tonic, minor, fit = best_key(chords, declared)
        if fit < 0.6:                            # no clear key: stay quiet rather than cry wolf
            results.append(flags)
            continue
        kname = key_name(tonic, minor)
        counts = Counter(g)
        for i, p in parsed:
            f = _fit(p, tonic, minor)
            sym = g[i]
            if f >= 1.0:
                continue
            if counts[sym] >= 4:                 # used a lot in this section: the arrangement, not an OCR slip
                continue
            sug = _suggest(p, tonic, minor)
            if f == 0.0 and counts[sym] < 3:
                why = f"{sym} doesn't fit {kname}"
            elif f == 0.5 and counts[sym] == 1 and sug:
                why = f"{sym} is unusual in {kname}"
            else:
                continue
            flags[i] = dict(chord=sym, key=kname, suggestions=sug, why=why)
        results.append(flags)
    return results
