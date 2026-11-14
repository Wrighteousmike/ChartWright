"""Turn positioned lines (from a PDF or plain text) into ChordPro.

The same engine serves both inputs: a PDF supplies real x/y coordinates, a
plain-text file supplies column index / row index (every char is 1 unit wide).
"""
from __future__ import annotations

import re
import statistics
from typing import Optional
from dataclasses import dataclass, field

from .chords import is_chord, is_chord_line, is_neutral, section_label


@dataclass
class Ch:
    c: str
    x0: float
    x1: float


@dataclass
class Line:
    chars: list[Ch]
    y: float            # baseline
    size: float = 1.0
    col_start: bool = False   # first line of a new column / page
    words: list = field(default_factory=list)
    dropped: list = field(default_factory=list)   # junk tokens removed from an OCR'd chord line

    def __post_init__(self):
        self.words = _split_words(self.chars)

    @property
    def text(self) -> str:
        return " ".join("".join(c.c for c in w) for w in self.words)

    @property
    def tokens(self) -> list[str]:
        return ["".join(c.c for c in w) for w in self.words]


def _split_words(chars: list[Ch]) -> list[list[Ch]]:
    words, cur = [], []
    for ch in chars:
        if ch.c.isspace():
            if cur:
                words.append(cur)
                cur = []
        else:
            cur.append(ch)
    if cur:
        words.append(cur)
    return words


# ---------------------------------------------------------------- chords → lyrics
def merge_chords(chord_line: Line, lyric: Line, snap: bool = False) -> str:
    """Insert each chord before the lyric character it sits above."""
    lch = [c for w in lyric.words for c in w]          # non-space chars
    inserts: dict[int, list[str]] = {}
    trailing: list[str] = []
    for w, tok in zip(chord_line.words, chord_line.tokens):
        cx = w[0].x0
        if snap and lyric.words:
            # OCR char boxes are fuzzy: a chord within ~1 char of a word start belongs to that word start
            cw = statistics.median(c.x1 - c.x0 for c in lch)
            starts = [lw[0] for lw in lyric.words if "".join(c.c for c in lw) not in ("-", "–", "—")]
            near = min(starts, key=lambda c: abs(c.x0 - cx))     # a lone "-" between syllables is never the target
            if abs(near.x0 - cx) <= 1.4 * cw:
                cx = near.x0 + 0.01
        # first char that ends after the chord's left edge (inside it, or the next one after a gap)
        i = next((k for k, c in enumerate(lch) if c.x1 > cx + 1e-6), None)
        if i is not None and cx - lch[i].x0 > 0.5 * (lch[i].x1 - lch[i].x0):
            i = i + 1 if i + 1 < len(lch) else None      # nearer the following char
        if i is None:
            trailing.append(tok)
            continue
        inserts.setdefault(i, []).append(tok)

    out, idx = [], 0
    for wi, w in enumerate(lyric.words):
        if wi:
            out.append(" ")
        for ch in w:
            for t in inserts.get(idx, []):
                out.append(f"[{t}]")
            out.append(ch.c)
            idx += 1
    for t in trailing:
        out.append(f" [{t}]")
    return "".join(out).strip() if out else " ".join(f"[{t}]" for t in trailing)


# ---------------------------------------------------------------- front matter
_KEY = re.compile(r"^key\s*[-:=]\s*(.+)$", re.I)
_CAPO = re.compile(r"^capo\s*[-:=]?\s*(\d+)\b.*$", re.I)
_TEMPO = re.compile(r"^(?:tempo|bpm)\s*[-:=]?\s*(\d+)\b.*$", re.I)
_TIME = re.compile(r"^time\s*[-:=]\s*(\d+/\d+)$", re.I)
_FOOTER = re.compile(r"rendered by chordpro|^page \d+( of \d+)?$|^\d+$|^songsele\w*\W*$|^by ?c+\W?[a-z]*$|^songselebyc\w*", re.I)


def _front_matter(texts: list[str]) -> tuple[list[str], list[str]]:
    """Split pre-song lines into (header lines, directives)."""
    head, meta = [], []
    title_done = False
    for t in texts:
        if (m := _KEY.match(t)):
            meta.append(f"{{key: {m.group(1).strip()}}}")
        elif (m := _CAPO.match(t)):
            meta.append(f"{{capo: {m.group(1)}}}")
        elif (m := _TEMPO.match(t)):
            meta.append(f"{{tempo: {m.group(1)}}}")
        elif (m := _TIME.match(t)):
            meta.append(f"{{time: {m.group(1)}}}")
        elif not title_done:
            head.append(f"{{title: {t}}}")
            title_done = True
        elif "|" in t or re.match(r"^(by|words|music|arr\w*|author|composer)\b", t, re.I):
            head.append(f"{{author: {t}}}")
        else:
            head.append(f"{{subtitle: {t}}}")
    return head, meta



# ---------------------------------------------------------------- OCR clean-up
_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

def _split_chords(tok: str):
    """'GA' -> ['G','A'];  'Bm7' -> ['Bm7'].  None if it can't be read as chords."""
    tok = tok.replace("♯", "#").replace("♭", "b")
    if is_chord(tok):
        return [tok]
    for i in range(len(tok) - 1, 0, -1):
        if is_chord(tok[:i]):
            rest = _split_chords(tok[i:])
            if rest:
                return [tok[:i]] + rest
    return None


def _tidy_chord_token(tok: str) -> str:
    """Superscript digits -> plain, 'GSUS'/'GsuS' -> 'Gsus', a raised digit read twice ('F22' -> 'F2')."""
    tok = tok.translate(_SUPER).replace(",", " ").strip()
    tok = re.sub(r"\(n0", "(no", tok)
    if re.match(r"^[A-Ga-g][#b]?", tok):
        tok = re.sub(r"(?i)sus", "sus", tok)
        tok = re.sub(r"(?i)(?<=[A-Ga-g#b])maj(?=\d|$)", "maj", tok)
        m = re.match(r"^(.*?[A-Za-z#])(\d)\2$", tok)
        if m and m.group(2) != "1":
            tok = m.group(1) + m.group(2)
    return tok


def _read_chord_token(tok: str):
    """_split_chords plus the usual OCR slips: lowercase root (c -> C), raised 7 read as 1 / ? / l."""
    tok = _tidy_chord_token(tok)
    if " " in tok:                                   # "Am7,F2" -> two chords
        parts = [_read_chord_token(t) for t in tok.split()]
        return [c for p in parts for c in p] if all(parts) else None
    for cand in dict.fromkeys([tok, tok[:1].upper() + tok[1:]]):
        sp = _split_chords(cand)
        if sp:
            return sp
        if len(cand) > 1 and cand[-1] in "1?lI|":
            sp = _split_chords(cand[:-1] + "7")
            if sp:
                return sp
    return None


_EXTENSION = re.compile(r"^(\d{1,2}|sus\d?|add\d{1,2}|maj\d{1,2})$")


def _merge_extensions(line: Line) -> list:
    """OCR often reads a raised '7' as its own token ('Dm 7'): glue it back if it sits right against a chord."""
    out: list = []
    for w, tok in zip(line.words, line.tokens):
        if out and _EXTENSION.match(tok):
            pw = out[-1]
            ptok = "".join(c.c for c in pw)
            if is_chord(ptok + tok) and not is_chord(ptok + tok + "x") and w[0].x0 - pw[-1].x1 <= 0.9 * line.size:
                out[-1] = pw + w
                continue
        out.append(w)
    return out


def repair_chord_line(line: Line) -> Line:
    """If an OCR'd line is mostly chords, fix merged chords and drop stray junk tokens."""
    if len(line.words) > 14 or (is_chord_line(line.tokens)
                                and all(_tidy_chord_token(t) == t for t in line.tokens)):
        return line
    pieces, good = [], 0
    for w in _merge_extensions(line):
        tok = "".join(c.c for c in w)
        if is_neutral(tok):                      # bar line / repeat sign: keep, but it isn't evidence either way
            pieces.append((w, [tok]))
            continue
        sp = _read_chord_token(tok)
        if not sp and tok in ("9", "6") and len(line.words) > 2:   # a bold G is often read as 9 / 6
            sp = ["G"]
        if sp:
            good += 1
            pieces.append((w, sp))
        else:
            pieces.append((w, None))
    # lone digits / symbols (a detached "7", noise) don't count against the line
    eligible = sum(1 for w, _ in pieces if re.search(r"[A-Za-z]", "".join(c.c for c in w)))
    if good == 0 or good < 0.6 * max(1, eligible):
        return line
    chars: list[Ch] = []
    dropped = [ "".join(c.c for c in w) for w, sp in pieces if not sp]
    for w, sp in pieces:
        if not sp:
            continue
        x0, x1 = w[0].x0, w[-1].x1
        n = sum(len(t) for t in sp)
        pos = x0
        for t in sp:
            if chars:
                chars.append(Ch(" ", chars[-1].x1, pos))
            span = (x1 - x0) * len(t) / n
            for k, c in enumerate(t):
                chars.append(Ch(c, pos + span * k / len(t), pos + span * (k + 1) / len(t)))
            pos += span
    out = Line(chars, line.y, line.size, line.col_start)
    out.dropped = dropped
    return out


_HEADINGS = ["verse", "chorus", "pre-chorus", "bridge", "intro", "outro", "interlude", "instrumental",
             "turnaround", "ending", "refrain", "tag", "coda"]


def repair_headings(lines: list) -> list:
    """OCR garbles short all-caps headings ('VEER SEE' for 'VERSE 3'). Snap them to the nearest known heading;
    a missing number continues the previous heading of the same name."""
    import difflib
    seen: dict = {}
    out = []
    for l in lines:
        t = l.text.strip()
        letters = [c for c in t if c.isalpha()]
        if is_chord_line(l.tokens) or not letters or len(t) > 18 or len(l.words) > 3:
            out.append(l)
            continue
        label = section_label(t)
        if not label and sum(c.isupper() for c in letters) >= 0.8 * len(letters) and len(letters) >= 4:
            word = re.sub(r"[^a-z]", "", t.lower())
            best = max(_HEADINGS, key=lambda h: difflib.SequenceMatcher(None, word, h.replace("-", "")).ratio())
            if difflib.SequenceMatcher(None, word, best.replace("-", "")).ratio() >= 0.6:
                m = re.search(r"\d+", t)
                label = best.title() + (f" {m.group()}" if m else "")
                if not m and best in ("verse", "chorus", "bridge") and best in seen:
                    label = f"{best.title()} {seen[best] + 1}"
        if label:
            m = re.match(r"([A-Za-z-]+)\s*(\d+)?", label)
            if m and m.group(2):
                seen[m.group(1).lower()] = int(m.group(2))
        if label and label != section_label(t) and label.lower() != t.lower():
            x0, x1 = l.chars[0].x0, l.chars[-1].x1
            n = len(label)
            chars = [Ch(c, x0 + (x1 - x0) * k / n, x0 + (x1 - x0) * (k + 1) / n) for k, c in enumerate(label)]
            nl = Line(chars, l.y, l.size, l.col_start)
            out.append(nl)
        else:
            out.append(l)
    return out


_LOWER_I = re.compile(r"(?<=[a-z])I|I(?=[a-z]{0,1}\b)(?<=[a-z]I)")


def fix_ocr_lyric(text: str) -> str:
    """Cheap fixes for classic OCR slips: l/I/1/| confusion inside words, comma spacing."""
    text = re.sub(r"(?<![\w])1(?= [a-z])", "I", text)                         # May 1 but -> May I but
    text = re.sub(r"(?<![A-Z])II(?![A-Z])", "ll", text)                       # faII -> fall
    text = re.sub(r"(?<=[a-z])[I|1](?=[a-z!?,.;:]|\b)", "l", text)            # wiId -> wild
    text = re.sub(r"(?<=[a-z] )(\[[^\]]+\])[I|1](?=[a-z])", r"\1l", text)     # wor [G]Id -> wor [G]ld
    text = re.sub(r"(?<=[a-z\]])1$", "l", text)                                # al [A]1 -> al [A]l
    return re.sub(r"(?<=[a-z]),(?=[a-z]{2})", ", ", text)


# ---------------------------------------------------------------- main entry
def lines_to_chordpro(lines: list[Line], ocr: bool = False, notes: Optional[list] = None) -> str:
    """notes: optional list that receives review items (auto-fixes and suggestions) for OCR input."""
    lines = [l for l in lines if l.words and not _FOOTER.search(l.text.strip())]
    if ocr:
        lines = [repair_chord_line(l) for l in lines]
        lines = repair_headings(lines)
        # noise: lines with fewer than 2 plain letters/digits that aren't chords (e.g. specks read as 日, à)
        lines = [l for l in lines if is_chord_line(l.tokens) or len(re.findall(r"[A-Za-z0-9]", l.text)) >= 2]
    if not lines:
        return ""

    sp = None
    if ocr:
        try:
            from .lyricfix import correct_lyric, correct_plain
            from .spell import available as spell_available, get_speller
            if spell_available():
                sp = get_speller()
                sp.learn_document([w for l in lines if not is_chord_line(l.tokens)
                                   for w in re.findall(r"[A-Za-z]+", l.text)])
        except Exception:  # noqa: BLE001 - dictionary is an enhancement, never a blocker
            sp = None
    front_notes: list = []

    # 1. front matter = everything before first chord line / section heading
    first = next(
        (i for i, l in enumerate(lines) if is_chord_line(l.tokens) or section_label(l.text)),
        len(lines),
    )
    front_texts = [l.text for l in lines[:first]]
    if sp:
        front_texts = [correct_plain(t, sp, front_notes) for t in front_texts]
    head, meta = _front_matter(front_texts)
    body = lines[first:]

    # 2. group into blocks
    blocks: list[dict] = []

    def lyric_of(lyric, chord_line):
        """(possibly dictionary-corrected lyric line, review notes for it)"""
        bn: list = []
        if sp:
            lyric = correct_lyric(lyric, chord_line, sp, bn)
        return lyric, bn

    i = 0
    while i < len(body):
        l = body[i]
        label = section_label(l.text) if not is_chord_line(l.tokens) else None
        if label:
            blocks.append(dict(kind="section", text=f"{{comment: {label}}}", y0=l.y, y1=l.y, cs=l.col_start, notes=[]))
            i += 1
        elif is_chord_line(l.tokens):
            nxt = body[i + 1] if i + 1 < len(body) else None
            bn = [dict(kind="chord", frm=t, to=None, shown=t, suggestions=[]) for t in l.dropped]
            if (
                nxt is not None and not nxt.col_start
                and not is_chord_line(nxt.tokens) and not section_label(nxt.text)
                and 0 < nxt.y - l.y <= 2.4 * max(l.size, nxt.size)
            ):
                fixed, ln = lyric_of(nxt, l)
                text = merge_chords(l, fixed, snap=ocr)
                blocks.append(dict(kind="song", text=fix_ocr_lyric(text) if ocr else text,
                                   y0=l.y, y1=nxt.y, cs=l.col_start, notes=bn + ln))
                i += 2
            else:
                blocks.append(dict(kind="song", text=" ".join(f"[{t}]" if is_chord(t) else t for t in l.tokens),
                                   y0=l.y, y1=l.y, cs=l.col_start, notes=bn))
                i += 1
        else:
            fixed, ln = lyric_of(l, None)
            blocks.append(dict(kind="song", text=fix_ocr_lyric(fixed.text) if ocr else l.text,
                               y0=l.y, y1=l.y, cs=l.col_start, notes=ln))
            i += 1

    # 2b. key plausibility (OCR only): question chords that don't fit their section's key
    if ocr:
        try:
            from .keys import check_groups
            declared = next((m.group(1) for m in (re.match(r"\{key:\s*(.+?)\}", x) for x in meta) if m), None)
            groups, owners, cur = [], [], []
            cur_owner: list = []
            for b in blocks:
                if b["kind"] == "section":
                    if cur:
                        groups.append(cur); owners.append(cur_owner)
                    cur, cur_owner = [], []
                    continue
                for ch in re.findall(r"\[([^\]]+)\]", b["text"]):
                    cur.append(ch); cur_owner.append(b)
            if cur:
                groups.append(cur); owners.append(cur_owner)
            for flags, own in zip(check_groups(groups, declared), owners):
                for idx, info in flags.items():
                    own[idx]["notes"].append(dict(
                        kind="key", frm=f"[{info['chord']}]", to=None, shown=f"[{info['chord']}]",
                        suggestions=[f"[{x}]" for x in info["suggestions"]], why=info["why"]))
        except Exception:  # noqa: BLE001 - a second opinion, never a blocker
            pass

    # 3. blank lines where vertical gap is clearly bigger than normal
    gaps = [b["y0"] - p["y1"] for p, b in zip(blocks, blocks[1:])
            if not b["cs"] and b["kind"] == "song" and p["kind"] == "song" and b["y0"] > p["y1"]]
    normal = statistics.median(gaps) if gaps else None

    # OCR noise: a lone chord with no lyric, parked well below everything else, is footer debris ("…Charts")
    if ocr and len(blocks) > 3 and normal:
        last, prev = blocks[-1], blocks[-2]
        if (last["kind"] == "song" and re.fullmatch(r"\[[^\]]+\]", last["text"])
                and last["y0"] - prev["y1"] > 2.5 * normal):
            if notes is not None:
                notes.append(dict(kind="chord", frm=last["text"].strip("[]"), to=None, shown=last["text"],
                                  suggestions=[], line=None, dropped_stray=True))
            blocks.pop()

    out: list[str] = []
    for n, b in enumerate(blocks):
        if n:
            p = blocks[n - 1]
            blank = b["kind"] == "section" or (
                normal is not None and not b["cs"] and p["kind"] == "song"
                and b["y0"] - p["y1"] > 1.35 * normal)
            if blank:
                out.append("")
        out.append(b["text"])

    parts = []
    if head:
        parts.append("\n".join(head))
    if meta:
        parts.append("\n".join(meta))
    parts.append("\n".join(out))
    text = "\n\n".join(parts).rstrip() + "\n"

    # 4. review notes -> where they ended up in the output (line numbers, 0-based)
    if notes is not None:
        final = text.splitlines()
        used: set = set()

        def locate(ctx, shown):
            for k, ln in enumerate(final):
                if k in used:
                    continue
                if (ctx is not None and ln == ctx) or (ctx is None and shown and shown in ln):
                    used.add(k)
                    return k
            return None

        for n in front_notes:
            n["line"] = locate(None, n["shown"])
            notes.append(n)
        for b in blocks:
            if not b["notes"]:
                continue
            k = locate(b["text"], None)
            for n in b["notes"]:
                n["line"] = k
                notes.append(n)
    return text
