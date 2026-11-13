"""Apply the dictionary (spell.py) to a positioned lyric line without disturbing chord alignment."""
from __future__ import annotations

import re
from typing import Optional

from .spell import _WORD, Speller, _match_case


def _text(w) -> str:
    return "".join(c.c for c in w)


def _is_gap_chord(chord_line, a, b) -> bool:
    """Is a chord sitting between the end of fragment a and the start of fragment b?"""
    if chord_line is None:
        return False
    lo = (a[-1].x0 + a[-1].x1) / 2
    hi = (b[0].x0 + b[0].x1) / 2
    return any(lo <= w[0].x0 <= hi for w in chord_line.words)


def correct_lyric(lyric, chord_line, sp: Speller, notes: list, first_in_line: bool = True):
    """Return a corrected copy of `lyric`; append review notes (dicts) to `notes`."""
    from .convert import Ch, Line

    words = [list(w) for w in lyric.words]

    # ---- A. rejoin broken fragments ("m y", "storm s", "hom e") unless a chord marks a real split
    i = 0
    while i < len(words) - 1:
        a, b = words[i], words[i + 1]
        ta, tb = _text(a), _text(b)
        if (re.fullmatch(r"[^A-Za-z]*[A-Za-z]+", ta) and re.fullmatch(r"[A-Za-z]+[^A-Za-z]*", tb)
                and not _is_gap_chord(chord_line, a, b)):
            ca, cb = re.sub(r"^[^A-Za-z]+", "", ta), re.sub(r"[^A-Za-z]+$", "", tb)
            joined = ca + cb
            weak = (not sp.known(ca)) or (not sp.known(cb))
            # joining onto a real word must be a plausible reading: "storm"+"s", "hur"+"led" yes; "with"+"al" no
            if not sp.known(ca) and not sp.known(cb):
                plausible = True
            else:
                small = cb if not sp.known(cb) else ca
                if len(small) == 1 or len(small) >= 3:
                    plausible = True
                else:                                   # 2-letter leftover: "al", "es" ...
                    plausible = (not sp.raw_token(small)) and \
                        sp.freq(joined) >= 0.02 * max(sp.freq(ca), sp.freq(cb))
            both_weak = not sp.known(ca) and not sp.known(cb)
            if weak and plausible and sp.known(joined) and (len(joined) >= 3 or both_weak):
                words[i] = a + b
                del words[i + 1]
                notes.append(dict(kind="joined", frm=f"{ta} {tb}", to=ta + tb, shown=ta + tb, suggestions=[]))
                continue
        i += 1

    # fragments on either side of a chord-marked gap are deliberate syllable splits: leave alone
    protected = set()
    for k in range(len(words) - 1):
        if _is_gap_chord(chord_line, words[k], words[k + 1]):
            for side in (k, k + 1):
                core = re.sub(r"[^A-Za-z]", "", _text(words[side]))
                if core and len(core) <= 4 and not sp.known(core):     # short non-word = syllable fragment
                    protected.add(side)
                    protected.add(k if side == k + 1 else k + 1)

    # ---- B. per-word: look-alike letters, joined words, unknown words
    out_words: list[list] = []
    for wi, w in enumerate(words):
        t = _text(w)
        m = _WORD.match(t)
        if not m or wi in protected:
            out_words.append(w)
            continue
        lead, core, trail = m.groups()
        start = len(lead)
        verdict, payload = sp.judge(core)
        if verdict == "fix":
            for k, ch in enumerate(payload):
                w[start + k].c = ch
            notes.append(dict(kind="fixed", frm=core, to=payload, shown=payload, suggestions=[]))
            out_words.append(w)
        elif verdict == "split":
            v, seg = payload
            parts_ok = all(L >= 3 or (k == 0 and L == 1) for k, L in enumerate(seg))   # allow leading "I"/"A"
            if core[:1].isupper() and not parts_ok:
                verdict = "suggest"
            else:
                for k, ch in enumerate(v):
                    w[start + k].c = ch
                pieces, p = [], start
                for L in seg:
                    pieces.append(w[p:p + L]); p += L
                pieces[0] = w[:start] + pieces[0]
                pieces[-1] = pieces[-1] + w[start + len(core):]
                for piece in pieces:
                    if len(piece) == 1 and piece[0].c in "il":
                        piece[0].c = "I"
                new = [_text(p) for p in pieces]
                notes.append(dict(kind="split", frm=core, to=" ".join(_text(p) for p in pieces).strip(),
                                  shown=" ".join(new), suggestions=[]))
                out_words.extend(pieces)
        if verdict == "suggest":
            out_words.append(w)
            skip = (len(core) < 3 or core.isupper() or (core[:1].isupper() and not (first_in_line and wi == 0))
                    or core.isdigit())
            if not skip:
                notes.append(dict(kind="suggest", frm=core, to=None, shown=core, suggestions=sp.suggest(core)))
        elif verdict == "ok":
            out_words.append(w)

    chars: list = []
    for w in out_words:
        if chars:
            chars.append(Ch(" ", chars[-1].x1, w[0].x0))
        chars.extend(w)
    return Line(chars, lyric.y, lyric.size, lyric.col_start)


def correct_plain(text: str, sp: Speller, notes: list) -> str:
    """Same thing for a plain string (title / author lines)."""
    from .convert import Ch, Line

    line = Line([Ch(c, i, i + 1) for i, c in enumerate(text)], 0.0)
    return correct_lyric(line, None, sp, notes).text
