"""ChordPro -> printable chord chart (PDF), with key change, capo and 1/2-column layout.

The same PDF is used for the on-screen preview (rendered to PNG) and for the download, so what you see is what
you get. Chords sit above the syllable they belong to; long lines wrap at word boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz

from .chords import is_chord
from .keys import NAMES_FLAT, NAMES_SHARP, best_key, key_name, parse_chord, parse_key

_SEG = re.compile(r"\[([^\]]*)\]")
_DIRECTIVE = re.compile(r"^\s*\{\s*([A-Za-z_]+)\s*(?::\s*(.*?))?\s*\}\s*$")
_SECTION_START = {"start_of_verse": "Verse", "sov": "Verse", "start_of_chorus": "Chorus", "soc": "Chorus",
                  "start_of_bridge": "Bridge", "sob": "Bridge", "start_of_tab": "Tab", "sot": "Tab"}
_SECTION_END = {"end_of_verse", "eov", "end_of_chorus", "eoc", "end_of_bridge", "eob", "end_of_tab", "eot"}
_COMMENT = {"comment", "c", "comment_italic", "ci", "comment_box", "cb"}
_META = {"title": "title", "t": "title", "subtitle": "sub", "st": "sub", "artist": "sub", "author": "sub",
         "composer": "sub", "lyricist": "sub", "arranger": "sub", "copyright": "copy"}


@dataclass
class Song:
    title: str = ""
    subs: list = field(default_factory=list)
    copyright: str = ""
    key: str = ""
    items: list = field(default_factory=list)      # ("label", text) | ("line", [(chord|None, text)]) | ("gap",)


def parse(text: str) -> Song:
    s = Song()
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if line.lstrip().startswith("#"):
            continue
        m = _DIRECTIVE.match(line)
        if m:
            name, val = m.group(1).lower(), (m.group(2) or "").strip()
            if name in _META:
                kind = _META[name]
                if kind == "title":
                    s.title = val
                elif kind == "copy":
                    s.copyright = val
                elif val:
                    s.subs.append(val)
            elif name == "key":
                s.key = val
            elif name in _COMMENT and val:
                s.items.append(("label", val))
            elif name in _SECTION_START:
                s.items.append(("label", val or _SECTION_START[name]))
            elif name in _SECTION_END or name in ("new_page", "np", "capo"):
                pass
            continue
        if not line.strip():
            if s.items and s.items[-1][0] != "gap":
                s.items.append(("gap",))
            continue
        ms = list(_SEG.finditer(line))
        if not ms:
            segs = [(None, line)]
        else:
            segs = [(None, line[:ms[0].start()])] if ms[0].start() > 0 else []
            for i, m2 in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
                segs.append((m2.group(1).strip(), line[m2.end():end]))
        s.items.append(("line", segs))
    while s.items and s.items[-1][0] == "gap":
        s.items.pop()
    return s


def all_chords(song: Song) -> list:
    out = []
    for it in song.items:
        if it[0] == "line":
            for c, _ in it[1]:
                if c and is_chord(c):
                    p = parse_chord(c)
                    if p:
                        out.append(p)
    return out


def original_key(song: Song):
    """-> (tonic_pc, minor) or None. Declared {key:} wins; otherwise inferred from the chords."""
    declared = parse_key(song.key)
    if declared:
        return declared
    ch = all_chords(song)
    if not ch:
        return None
    t, minor, _ = best_key(ch)
    return t, minor


def key_options(orig) -> list:
    """The 12 keys in the same mode as the original (names as musicians write them)."""
    if not orig:
        return []
    minor = orig[1]
    names = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    if minor:
        names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
    return [n + ("m" if minor else "") for n in names]


_CH = re.compile(r"^([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?$")


def transpose_chord(tok: str, n: int, flats: bool) -> str:
    if n % 12 == 0:
        return tok
    m = _CH.match(tok)
    if not m:
        return tok
    names = NAMES_FLAT if flats else NAMES_SHARP

    def pc(x):
        return (({"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[x[0]]) + (1 if x[1:] == "#" else -1 if x[1:] == "b" else 0))

    out = names[(pc(m.group(1)) + n) % 12] + m.group(2)
    if m.group(3):
        out += "/" + names[(pc(m.group(3)) + n) % 12]
    return out


_SIZES = {"small": 10.0, "medium": 12.0, "large": 14.0}
_PAGE_W, _PAGE_H, _MARGIN = 595.0, 842.0, 46.0     # A4


def _fix_text(t: str) -> str:
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("…", "..."), ("\t", "    "),
                 ("♯", "#"), ("♭", "b")):
        t = t.replace(a, b)
    return t.encode("latin-1", "replace").decode("latin-1")


def _w(text: str, font: str, size: float) -> float:
    return fitz.get_text_length(text, fontname=font, fontsize=size)


def _cells(segs, fs):
    """Split a line into word-sized cells that carry their chord; mark where wrapping is allowed."""
    cells, prev_end_space = [], True
    for chord, text in segs:
        pieces = re.findall(r"\S+\s*|\s+", text) or [""]
        for j, p in enumerate(pieces):
            cells.append({"chord": chord if j == 0 else None, "text": p, "brk": prev_end_space if j == 0 else True})
            prev_end_space = p == "" and prev_end_space or p[-1:].isspace()
    for c in cells:
        tw = _w(c["text"], "helv", fs)
        cw = _w(c["chord"], "hebo", fs) + fs * 0.35 if c["chord"] else 0
        c["w"] = max(tw, cw)
    return cells


def _rows(segs, fs, colw):
    cells = _cells(segs, fs)
    if cells:
        cells[0]["text"] = cells[0]["text"].lstrip()
        cells[0]["w"] = max(_w(cells[0]["text"], "helv", fs),
                            _w(cells[0]["chord"], "hebo", fs) + fs * 0.35 if cells[0]["chord"] else 0)
    rows, cur, x, indent = [], [], 0.0, 0.0
    for c in cells:
        if cur and c["brk"] and x + c["w"] > colw - indent + 0.5:
            rows.append((indent, cur))
            cur, x, indent = [], 0.0, fs * 1.2
            if not c["chord"]:
                c["text"] = c["text"].lstrip()
                c["w"] = _w(c["text"], "helv", fs)
        cur.append((x, c))
        x += c["w"]
    if cur:
        rows.append((indent, cur))
    return rows


def render_pdf(text: str, key: str = "", capo: int = 0, columns: int = 1, size: str = "medium",
               title: str = "") -> tuple[bytes, dict]:
    """-> (pdf bytes, info). `key` is the key you want to *sound in*; with a capo the printed shapes are lower."""
    song = parse(text)
    orig = original_key(song)
    target = parse_key(key) if key else None
    capo = max(0, min(11, int(capo or 0)))
    shift = ((target[0] - orig[0]) % 12) if (target and orig) else 0
    shape_shift = (shift - capo) % 12
    shape_tonic = ((orig[0] + shape_shift) % 12) if orig else 0
    flats = bool(orig) and (NAMES_FLAT[shape_tonic] + ("m" if orig[1] else "")) in {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm", "Abm", "Dbm"}

    def tc(c):
        return transpose_chord(c, shape_shift, flats) if (c and is_chord(c)) else c

    fs = _SIZES.get(size, 12.0)
    columns = 2 if columns == 2 else 1
    gutter = 26.0
    colw = (_PAGE_W - 2 * _MARGIN - gutter * (columns - 1)) / columns
    bottom = _PAGE_H - _MARGIN - 8
    sounding = key_name((orig[0] + shift) % 12, orig[1]) if orig else ""
    shapes = key_name(shape_tonic, orig[1]) if orig else ""

    title_txt = _fix_text(song.title or title or "Untitled")
    # ---- header (page 1, full width)
    header = []     # (text, font, size, colour, gap_before)
    header.append((title_txt, "hebo", 21, (0.1, 0.1, 0.1), 0))
    for sub in song.subs:
        header.append((_fix_text(sub), "helv", 10, (0.38, 0.38, 0.38), 3))
    meta = []
    if sounding:
        meta.append(f"Key: {sounding}")
    if capo:
        meta.append(f"Capo: {capo}" + (f"   (play shapes in {shapes})" if shapes else ""))
    if meta:
        header.append(("    ".join(meta), "hebo", 11, (0.55, 0.23, 0.07), 8))
    head_h = sum(sz * 1.25 + gap for _, _, sz, _, gap in header) + 16

    # ---- blocks (atomic: a label stays with its first line)
    blocks, pending_label = [], None
    for it in song.items:
        if it[0] == "gap":
            blocks.append({"h": fs * 0.75, "gap": True, "parts": []})
        elif it[0] == "label":
            pending_label = _fix_text(it[1])
        else:
            segs = [(tc(c), _fix_text(t)) for c, t in it[1]]
            for i in range(len(segs) - 1):      # "ski  [G]es": the extra spaces only made room for the chord
                t, nxt = segs[i][1], segs[i + 1][1]
                if len(t) - len(t.rstrip()) >= 2 and t.strip() and nxt[:1].isalpha():
                    segs[i] = (segs[i][0], t.rstrip())
            rows = _rows(segs, fs, colw)
            parts, h = [], 0.0
            if pending_label:
                parts.append(("label", pending_label, h))
                h += fs * 1.55 + 2
                pending_label = None
            for indent, cells in rows:
                has_chord = any(c["chord"] for _, c in cells)
                rh = fs * 1.2 + (fs * 1.25 if has_chord else 0) + 1.5
                parts.append(("row", (indent, cells, has_chord), h))
                h += rh
            blocks.append({"h": h, "gap": False, "parts": parts})

    # ---- paginate into columns
    placed, page, col, y = [], 0, 0, _MARGIN + head_h
    top_of = lambda p: _MARGIN + (head_h if p == 0 else 0)  # noqa: E731
    for b in blocks:
        if b["gap"] and y <= top_of(page) + 0.1:
            continue
        if not b["gap"] and y + b["h"] > bottom and y > top_of(page) + 0.1:
            col += 1
            if col >= columns:
                col, page = 0, page + 1
            y = top_of(page)
        placed.append((page, col, y, b))
        y += b["h"]
    pages = (placed[-1][0] + 1) if placed else 1

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=_PAGE_W, height=_PAGE_H)
    p0 = doc[0]
    y = _MARGIN
    for txt, font, sz, colour, gap in header:
        y += gap
        p0.insert_text((_MARGIN, y + sz), txt, fontname=font, fontsize=sz, color=colour)
        y += sz * 1.25
    p0.draw_line((_MARGIN, _MARGIN + head_h - 8), (_PAGE_W - _MARGIN, _MARGIN + head_h - 8), color=(0.8, 0.78, 0.72), width=0.6)
    for page_i, col_i, y0, b in placed:
        pg = doc[page_i]
        x0 = _MARGIN + col_i * (colw + gutter)
        for kind, data, dy in b["parts"]:
            if kind == "label":
                pg.insert_text((x0, y0 + dy + fs * 1.1), data, fontname="hebo", fontsize=fs * 0.95, color=(0.25, 0.25, 0.25))
                continue
            indent, cells, has_chord = data
            base = y0 + dy + (fs * 1.25 if has_chord else 0) + fs
            for cx, c in cells:
                x = x0 + indent + cx
                if c["chord"]:
                    pg.insert_text((x, base - fs * 1.25), c["chord"], fontname="hebo", fontsize=fs, color=(0.55, 0.23, 0.07))
                if c["text"].strip():
                    pg.insert_text((x, base), c["text"], fontname="helv", fontsize=fs, color=(0.05, 0.05, 0.05))
    if song.copyright:
        doc[pages - 1].insert_text((_MARGIN, _PAGE_H - _MARGIN + 6), _fix_text(song.copyright), fontname="helv", fontsize=8, color=(0.5, 0.5, 0.5))
    if pages > 1:
        for i in range(pages):
            pg = doc[i]
            pg.insert_text((_PAGE_W - _MARGIN - 30, _PAGE_H - _MARGIN + 6), f"{i + 1} / {pages}", fontname="helv", fontsize=8, color=(0.5, 0.5, 0.5))
    doc.set_metadata({"title": title_txt, "producer": "ChordPro Maker"})
    data = doc.tobytes(garbage=3, deflate=True)
    info = {"pages": pages, "original": key_name(*orig) if orig else "", "options": key_options(orig),
            "key": sounding, "shapes": shapes, "title": title_txt}
    return data, info


def render_preview(text: str, **kw) -> dict:
    import base64
    data, info = render_pdf(text, **kw)
    with fitz.open("pdf", data) as d:
        info["images"] = [base64.b64encode(p.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).tobytes("png")).decode() for p in d]
    return info
