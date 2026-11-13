"""Digital sheet music / lead sheets (Sibelius, MuseScore, Finale, Dorico … exported to PDF) -> ChordPro.

No music recognition: these PDFs carry a real text layer (chord symbols above the staff, lyric syllables
below it). The staff lines are vector drawings, so staves — and therefore "systems" — are found exactly.
Per system we pair each chord symbol with the lyric syllable under it, once per verse (stacked lyric rows).

Scanned sheet music has no staff drawings or text layer and is not handled here (it falls back to OCR).
"""
from __future__ import annotations

import re
import statistics
from typing import Optional

from .chords import is_chord

# glyphs used by music chord fonts (Sibelius "Opus Chords Std" etc.)
GLYPHS = {
    "¨": "b", "♭": "b", "♯": "#", "‹": "m", "“": "sus", "°": "dim", "º": "dim", "ø": "m7b5",
    "∆": "maj7", "Δ": "maj7", "−": "-", "–": "-", "+": "+", "(": "", ")": "", " ": "",
}
_NOTATION_FONT = re.compile(r"opus(?!.*chord)|bravura|maestro|petaluma|leland|emmentaler|feta|finale|sibelius", re.I)
_CHORD_FONT = re.compile(r"chord", re.I)
_LABEL = re.compile(r"^(\d+)[.)]$")
_HYPHENS = {"-", "–", "‐", "‑"}


# ---------------------------------------------------------------- staves
def find_staves(page) -> list[tuple[float, float]]:
    """(top, bottom) of every five-line staff on the page, from the vector drawings."""
    ys: list[float] = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 0.05 and abs(it[1].x - it[2].x) > page.rect.width * 0.25:
                ys.append(round(it[1].y, 1))
            elif it[0] == "re" and it[1].height < 1.6 and it[1].width > page.rect.width * 0.25:
                ys.append(round((it[1].y0 + it[1].y1) / 2, 1))
    ys = sorted(set(ys))
    staves, cur = [], []
    for y in ys:
        if cur and y - cur[-1] > 8.0:
            if len(cur) >= 5:
                staves.append((cur[0], cur[-1]))
            cur = []
        cur.append(y)
    if len(cur) >= 5:
        staves.append((cur[0], cur[-1]))
    return staves


def looks_like_sheet_music(page) -> bool:
    return len(find_staves(page)) >= 1


# ---------------------------------------------------------------- tokens
def _tokens(page, clips):
    """Text tokens (split on spaces inside each span): dict(t,x0,x1,y,size,font)."""
    import fitz

    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    toks = []
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                cur = []
                for c in s["chars"] + [{"c": " ", "bbox": (0, 0, 0, 0), "origin": (0, 0)}]:
                    if c["c"].isspace():
                        if cur:
                            toks.append(dict(t="".join(k["c"] for k in cur), x0=cur[0]["bbox"][0], x1=cur[-1]["bbox"][2],
                                             y=cur[0]["origin"][1], size=s["size"], font=s["font"]))
                        cur = []
                    else:
                        cur.append(c)
    if clips:
        def inside(t):
            cx, cy = (t["x0"] + t["x1"]) / 2, t["y"] - t["size"] * 0.3
            return any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in clips)
        toks = [t for t in toks if inside(t)]
    return toks


def decode_chord(text: str):
    """Chord-font glyphs -> plain symbol ('B¨7/D' -> 'Bb7/D', 'F(“4)' -> 'Fsus4'). Returns (symbol, ok)."""
    sym = "".join(GLYPHS.get(c, c) for c in text)
    return sym, is_chord(sym) or bool(re.fullmatch(r"[A-G][#b]?[A-Za-z0-9#b+\-]*(/[A-G][#b]?)?", sym))


def _rows(tokens, tol_frac=0.4):
    rows: list[list[dict]] = []
    for t in sorted(tokens, key=lambda t: (t["y"], t["x0"])):
        if rows and abs(t["y"] - statistics.mean(r["y"] for r in rows[-1])) <= tol_frac * t["size"]:
            rows[-1].append(t)
        else:
            rows.append([t])
    return [sorted(r, key=lambda t: t["x0"]) for r in rows]


# ---------------------------------------------------------------- lyric rows -> syllables
def _syllables(row):
    """Row tokens -> (verse_label|None, words) where words = [[(syllable, centre_x), ...], ...]; hyphens join syllables."""
    label = None
    toks = list(row)
    if toks and _LABEL.match(toks[0]["t"]):
        label = int(_LABEL.match(toks[0]["t"]).group(1))
        toks = toks[1:]
    words: list[list[tuple]] = []
    join_next = False
    for t in toks:
        txt = t["t"]
        if txt in _HYPHENS:
            join_next = True
            continue
        if re.fullmatch(r"_+", txt):
            continue
        cx = (t["x0"] + t["x1"]) / 2
        if txt.endswith("-") and len(txt) > 1:            # "ri-" glued form
            syl, joins = txt[:-1], True
        else:
            syl, joins = txt, False
        if join_next and words:
            words[-1].append((syl, cx))
        else:
            words.append([(syl, cx)])
        join_next = joins
    if join_next and words:                       # row ends mid-word ("un-" / next system "numbered")
        s_txt, cx = words[-1][-1]
        words[-1][-1] = (s_txt + "-", cx)
    return label, words


def _place_chords(words, chords, tol=12.0):
    """Insert each chord before the syllable under it (nearest centre within tol, else the next syllable)."""
    syl = [(w, s, cx) for w, word in enumerate(words) for s, (_, cx) in enumerate(word)]
    if not syl:
        return None
    put: dict[tuple, list] = {}
    trailing: list = []
    lead = syl[0][2] - tol
    chords_all = chords
    chords = [(c, x) for c, x in chords if x >= lead]       # earlier chords: before this verse line starts
    for cname, ccx in chords:
        j = min(range(len(syl)), key=lambda k: abs(syl[k][2] - ccx))
        if abs(syl[j][2] - ccx) > tol:                       # nothing sung on that note: next syllable to the right
            j = next((k for k in range(len(syl)) if syl[k][2] >= ccx), None)
        if j is None:
            trailing.append(cname)
        else:
            put.setdefault((syl[j][0], syl[j][1]), []).append(cname)
    # a line that starts mid-system begins on whatever chord is already sounding
    first = (syl[0][0], syl[0][1])
    if first not in put:
        active = [c for c, cx in chords_all if cx <= syl[0][2] + tol]
        if active:
            put[first] = [active[-1]]
    out = []
    for w, word in enumerate(words):
        text = ""
        for s, (syl_txt, _) in enumerate(word):
            for c in put.get((w, s), []):
                text += f"[{c}]"
            text += syl_txt
        out.append(text)
    line = " ".join(out)
    for c in trailing:
        line += f" [{c}]"
    return line


# ---------------------------------------------------------------- header / footer
def _meta_from(rows) -> tuple[list[str], list[str]]:
    head, extra = [], []
    for r in rows:
        txt = " ".join(t["t"] for t in r)
        if m := re.match(r"^(?:words|lyrics|text)\s*(?:by)?\s*:?\s*(.+)$", txt, re.I):
            head.append(f"{{lyricist: {m.group(1).strip()}}}")
        elif m := re.match(r"^(?:music|composer|tune)\s*(?:by)?\s*:?\s*(.+)$", txt, re.I):
            kind = "tune" if txt.lower().startswith("tune") else "composer"
            head.append(f"{{composer: {m.group(1).strip()}}}" if kind == "composer" else f"{{meta: tune {m.group(1).strip()}}}")
        elif m := re.match(r"^(?:arr\.?|arranged by|arrangement)\s*:?\s*(.+)$", txt, re.I):
            head.append(f"{{arranger: {m.group(1).strip()}}}")
        else:
            extra.append(txt)
    return head, extra


def _footer_meta(rows) -> list[str]:
    out = []
    txt = " ".join(" ".join(t["t"] for t in r) for r in rows)
    if m := re.search(r"['‘“\"]([^'’”\"]{4,})['’”\"]", txt):
        out.append(f"{{subtitle: {m.group(1).strip()}}}")
    cr = " ".join(" ".join(t["t"] for t in r) for r in rows if re.search(r"©|\(c\)|copyright", " ".join(t["t"] for t in r), re.I))
    if cr:
        cr = re.sub(r"\s*CCLI\s*#?\s*\d+\.?", "", cr).strip()
        out.append(f"{{copyright: {cr}}}")
    if m := re.search(r"CCLI\s*(?:#|No\.?|Song\s*#)?\s*(\d{4,})", txt, re.I):
        out.append(f"{{meta: ccli {m.group(1)}}}")
    return out


# ---------------------------------------------------------------- main
def convert_sheet(path, selections: Optional[list[dict]] = None, notes: Optional[list] = None) -> str:
    import fitz
    from .keys import best_key, key_name, parse_chord

    with fitz.open(path) as doc:
        pages = list(range(len(doc)))
        if selections:
            pages = sorted({s["page"] for s in selections})
        verses: dict[int, list[str]] = {}
        started: set[int] = set()
        all_chords: list[str] = []
        title = None
        head_extra: list[str] = []
        head_lines: list[str] = []
        footer_rows: list = []
        intro: list[str] = []
        order_seen: list[int] = []

        for pn in pages:
            page = doc[pn]
            staves = find_staves(page)
            if not staves:
                continue
            clips = [fitz.Rect(s["rect"]) * page.derotation_matrix for s in (selections or []) if s["page"] == pn] or None
            toks = _tokens(page, clips)
            # drop notation glyphs and tokens with nothing readable (note heads, clefs, time signatures)
            toks = [t for t in toks if not _NOTATION_FONT.search(t["font"]) or _CHORD_FONT.search(t["font"])]
            toks = [t for t in toks if re.search(r"[A-Za-z0-9©]", t["t"]) or t["t"] in _HYPHENS or _LABEL.match(t["t"])
                    or _CHORD_FONT.search(t["font"])]
            body = [t for t in toks if not _CHORD_FONT.search(t["font"])]
            sizes = [t["size"] for t in body if staves[0][1] < t["y"] < staves[-1][1] + 60]
            lyric_size = statistics.mode([round(s, 1) for s in sizes]) if sizes else 9.0

            first_top = staves[0][0]
            last_bottom = staves[-1][1]

            # ---- header (above the first staff, not chords) and footer (below the last staff, small / ©)
            hdr = [t for t in body if t["y"] < first_top - 14 and not (_CHORD_FONT.search(t["font"]))]
            chordy = lambda t: bool(_CHORD_FONT.search(t["font"]))              # noqa: E731
            hdr_rows = _rows([t for t in hdr if t["y"] < first_top - 12], 0.5)
            if pn == pages[0] and hdr_rows:
                big = max(hdr_rows, key=lambda r: max(t["size"] for t in r))
                if max(t["size"] for t in big) > 1.4 * lyric_size:
                    title = " ".join(t["t"] for t in big)
                    if title.isupper():
                        title = title.title()
                    hdr_rows = [r for r in hdr_rows if r is not big]
                h, ex = _meta_from(hdr_rows)
                head_lines += h
                head_extra += ex

            below = [t for t in body if t["y"] > last_bottom + 4]
            foot = [t for t in below if t["size"] < lyric_size - 0.3 or re.search(r"©|CCLI|\(PRS\)", t["t"])]
            foot_ids = {id(t) for t in foot}
            if foot:
                # a footer is everything from the first small/© row downward
                fy = min(t["y"] for t in foot) - 3
                foot_ids |= {id(t) for t in below if t["y"] >= fy}
            footer_rows += _rows([t for t in below if id(t) in foot_ids], 0.5)

            # ---- assign remaining tokens to staves
            n = len(staves)
            lyric_tokens = [[] for _ in range(n)]
            chord_tokens = [[] for _ in range(n)]
            for t in toks:
                if id(t) in foot_ids or t["y"] < first_top - 45 and not chordy(t):
                    continue
                if t in hdr and not chordy(t) and t["y"] < first_top - 12:
                    continue
                # staff index: chords belong to the staff below them, lyrics to the staff above them
                if chordy(t):
                    cand = [i for i in range(n) if staves[i][0] > t["y"] - 2]
                    if cand:
                        chord_tokens[cand[0]].append(t)
                else:
                    cand = [i for i in range(n) if staves[i][1] < t["y"]]
                    if cand:
                        i = cand[-1]
                        gap_end = staves[i + 1][0] if i + 1 < n else 1e9
                        if t["y"] < gap_end - 2:
                            lyric_tokens[i].append(t)
                        # non-chord-font chords (other engravers): tokens just above the next staff that parse as chords
            # chords set in a normal font: rows sitting just above a staff that are entirely chord symbols
            for i in range(n):
                keep = []
                rows = _rows(lyric_tokens[i], 0.4)
                for r in rows:
                    near_next = i + 1 < n and staves[i + 1][0] - r[0]["y"] < 30
                    if near_next and all(decode_chord(t["t"])[1] for t in r):
                        chord_tokens[i + 1] += r
                    else:
                        keep += r
                lyric_tokens[i] = keep

            for i in range(n):
                chords = []
                for t in sorted(chord_tokens[i], key=lambda t: t["x0"]):
                    sym, ok = decode_chord(t["t"])
                    if not ok and notes is not None:
                        notes.append(dict(kind="chord", frm=t["t"], to=None, shown=t["t"], suggestions=[], line=None))
                    if sym:
                        chords.append((sym, (t["x0"] + t["x1"]) / 2))
                        all_chords.append(sym)
                rows = _rows([t for t in lyric_tokens[i] if not re.fullmatch(r"\d+", t["t"])], 0.4)
                if not rows:
                    if chords:                                    # instrumental system
                        line = " ".join(f"[{c}]" for c, _ in chords)
                        if not started:
                            intro.append(line)                   # before any lyric: an intro
                        else:
                            for v in verses:                      # between verses' lines: chords only, every verse
                                verses[v].append(line)
                    continue
                for rank, r in enumerate(rows):
                    label, words = _syllables(r)
                    # a verse number in the middle of a row that already has text = repeat pickup: cut it off
                    for k, t in enumerate(r[1:], 1):
                        m = _LABEL.match(t["t"])
                        if m and int(m.group(1)) in started and words:
                            label2, words = _syllables(r[:k])
                            label = label if label is not None else label2
                            break
                    verse = label if label is not None else rank + 1
                    if not words:
                        continue
                    line = _place_chords(words, chords)
                    if line:
                        verses.setdefault(verse, []).append(line)
                        started.add(verse)
                        if verse not in order_seen:
                            order_seen.append(verse)

    # ---- assemble
    if not verses and not intro:
        return ""
    head = []
    if title:
        head.append(f"{{title: {title}}}")
    foot = _footer_meta(footer_rows)
    sub = [f for f in foot if f.startswith("{subtitle")]
    head += sub + head_lines
    for ex in head_extra:
        head.append(f"{{comment: {ex}}}")
    meta = []
    parsed = [p for p in (parse_chord(c) for c in all_chords) if p]
    if parsed:
        tonic, minor, fit = best_key(parsed)
        meta.append(f"{{key: {key_name(tonic, minor)}}}")
    meta += [f for f in foot if not f.startswith("{subtitle")]

    body = []
    if intro:
        body.append("{comment: Intro}\n" + "\n".join(intro))
    for v in sorted(verses):
        body.append(f"{{comment: Verse {v}}}\n" + "\n".join(verses[v]))
    parts = ["\n".join(head)] if head else []
    if meta:
        parts.append("\n".join(meta))
    parts.append("\n\n".join(body))
    return "\n\n".join(parts).rstrip() + "\n"
