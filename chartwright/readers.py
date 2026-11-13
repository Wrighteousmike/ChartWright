"""Input readers: PDF (optionally with selection boxes), DOCX, and text-like files."""
from __future__ import annotations

import re
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from .convert import Ch, Line, lines_to_chordpro

Rect = Sequence[float]  # x0, y0, x1, y1 in PDF points (unrotated page space)

TEXT_EXTS = {".txt", ".md", ".cho", ".crd", ".chopro", ".chordpro", ".pro", ".onsong", ".text"}
TEXTUTIL_EXTS = {".rtf", ".rtfd", ".odt", ".doc", ".html", ".htm", ".webarchive"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".jp2"}
MIN_TEXT_CHARS = 15          # fewer real characters than this => treat as scanned


class ScannedPdfError(RuntimeError):
    pass


# ------------------------------------------------------------------ PDF
def _drop_footer(chars, size):
    rows: list[list] = []
    for c in sorted(chars, key=lambda c: c[3]):
        if rows and abs(c[3] - rows[-1][0][3]) <= 0.5 * size:
            rows[-1].append(c)
        else:
            rows.append([c])
    keep = []
    for r in rows:
        t = "".join(c[0] for c in sorted(r, key=lambda c: c[1]))
        if re.search(r"chord\s?pro|rendered by|rend\w{0,3}red|\bcharts?$", t, re.I):
            continue
        keep += r
    return keep


def _page_lines(page, clip: Optional[Rect], ocr: str = "auto") -> tuple[list[Line], bool]:
    """Returns (lines, used_ocr). ocr: 'auto' | 'force' | 'off'."""
    import fitz
    from . import ocr as ocr_mod

    rect = fitz.Rect(clip) if clip else page.rect
    raw = page.get_text("rawdict", clip=rect, flags=fitz.TEXT_PRESERVE_WHITESPACE)
    chars = []
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                for c in s["chars"]:
                    x0, y0, x1, y1 = c["bbox"]
                    # keep chars whose centre is inside the selection
                    if clip and not (rect.x0 <= (x0 + x1) / 2 <= rect.x1 and rect.y0 <= (y0 + y1) / 2 <= rect.y1):
                        continue
                    chars.append((c["c"], x0, x1, c["origin"][1], s["size"]))
    used_ocr = False
    real = sum(1 for c in chars if not c[0].isspace())
    if ocr == "force" or (ocr == "auto" and real < MIN_TEXT_CHARS):
        if not ocr_mod.available():
            raise ScannedPdfError("This looks like a scan, but the OCR engine is not installed "
                                  "(pip install rapidocr onnxruntime in the project .venv).")
        chars = ocr_mod.ocr_page_chars(page, clip)
        used_ocr = True
    if not chars:
        return [], used_ocr
    size = statistics.median(c[4] for c in chars)

    # ---- drop footer/watermark rows (e.g. "Rendered by ChordPro") before column logic
    chars = _drop_footer(chars, size)
    if not chars:
        return [], used_ocr

    # ---- columns: wide, (almost) empty vertical gutters in the x-density histogram
    x_min = min(c[1] for c in chars)
    x_max = max(c[2] for c in chars)
    nb = int(x_max - x_min) + 2
    dens = [0] * nb
    for c in chars:
        if c[0].isspace():
            continue
        for k in range(int(c[1] - x_min), int(c[2] - x_min) + 1):
            dens[k] += 1
    min_gap = max(18, int(2.6 * size))
    lim = max(1, int(0.08 * max(dens)))
    gutters, k = [], 0
    while k < nb:
        if dens[k] <= lim:
            j = k
            while j < nb and dens[j] <= lim:
                j += 1
            if j - k >= min_gap and k > 0 and j < nb:
                gutters.append(x_min + (k + j) / 2)
            k = j
        else:
            k += 1
    edges = [-1e9] + gutters + [1e9]

    # assign each char to a column; rows that straddle a gutter (centred titles) stay whole
    def col_of(x):
        return sum(1 for g in gutters if x >= g)

    assign = {}
    grows: list[list] = []
    for c in sorted(chars, key=lambda c: c[3]):
        if grows and abs(c[3] - grows[-1][0][3]) <= 0.5 * size:
            grows[-1].append(c)
        else:
            grows.append([c])
    for r in grows:
        r_cols = {col_of((c[1] + c[2]) / 2) for c in r}
        straddle = len(r_cols) > 1 and any(
            abs((c[1] + c[2]) / 2 - g) <= min_gap / 2 for g in gutters for c in r)
        lead = col_of(min(c[1] for c in r))
        for c in r:
            assign[id(c)] = lead if straddle else col_of((c[1] + c[2]) / 2)

    result: list[Line] = []
    for ci in range(len(gutters) + 1):
        col = [c for c in chars if assign[id(c)] == ci]
        col.sort(key=lambda c: (c[3], c[1]))
        rows: list[list] = []
        for c in col:
            if rows and abs(c[3] - rows[-1][0][3]) <= 0.5 * size:
                rows[-1].append(c)
            else:
                rows.append([c])
        first = True
        for row in rows:
            row.sort(key=lambda c: c[1])
            seq: list[Ch] = []
            pending_space = False
            for c in row:
                if c[0].isspace():
                    pending_space = True
                    continue
                if seq and seq[-1].c != " " and (pending_space or (not used_ocr and c[1] - seq[-1].x1 > 0.22 * size)):
                    seq.append(Ch(" ", seq[-1].x1, c[1]))
                pending_space = False
                seq.append(Ch(c[0], c[1], c[2]))
            if seq:
                y = statistics.median(c[3] for c in row)
                result.append(Line(seq, y, size, col_start=first))
                first = False
    return result, used_ocr


def pdf_page_count(path: str | Path) -> int:
    import fitz
    with fitz.open(path) as d:
        return len(d)


def _is_sheet_music(path: Path) -> bool:
    import fitz
    from .sheetmusic import looks_like_sheet_music
    try:
        with fitz.open(path) as d:
            return any(looks_like_sheet_music(p) for p in d)
    except Exception:  # noqa: BLE001
        return False


def convert_pdf(path: str | Path, selections: Optional[list[dict]] = None, ocr: str = "auto",
                notes: Optional[list] = None, layout: str = "auto") -> str:
    """selections: [{"page": 0, "rect": [x0,y0,x1,y1]}, ...]; None = whole document.
    Also handles image files (png/jpg/tiff…), which PyMuPDF opens as one-page documents.
    ocr: 'auto' (OCR only where there is no text layer), 'force', or 'off'."""
    import fitz

    # digital sheet music (staves + text): chords above the staff, lyrics below -> its own reader
    if layout == "sheet" or (layout == "auto" and Path(path).suffix.lower() == ".pdf" and _is_sheet_music(Path(path))):
        from .sheetmusic import convert_sheet
        text = convert_sheet(path, selections, notes)
        if text:
            return text
        if layout == "sheet":
            raise ScannedPdfError("No chords or lyrics could be read from this sheet music "
                                  "(is it a scan? try layout 'Chord chart' with OCR).")

    lines: list[Line] = []
    used = False
    with fitz.open(path) as doc:
        if selections:
            for s in selections:
                page = doc[s["page"]]
                r = fitz.Rect(s["rect"]) * page.derotation_matrix
                ls, u = _page_lines(page, r, ocr)
                lines += ls
                used |= u
        else:
            for page in doc:
                ls, u = _page_lines(page, None, ocr)
                lines += ls
                used |= u
        if not lines:
            raise ScannedPdfError(
                "No text found here. Try a different box, or set text recognition to 'Always OCR'."
                if ocr != "off" else
                "No selectable text found and OCR is switched off."
            )
    return lines_to_chordpro(lines, ocr=used, notes=notes)


# ------------------------------------------------------------------ text / docx
def _text_to_lines(text: str) -> list[Line]:
    lines = []
    for n, raw in enumerate(text.expandtabs(8).splitlines()):
        if not raw.strip():
            continue
        lines.append(Line([Ch(c, i, i + 1) for i, c in enumerate(raw.rstrip())], float(n)))
    return lines


def text_to_chordpro(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    # Already ChordPro (inline [chords] or directives)? keep as-is.
    if re.search(r"^\s*\{\s*(title|t|start_of|comment|key)\b", text, re.M | re.I) or \
       re.search(r"\[[A-G][#b]?[^\]\s]*\]", text):
        return text if text.endswith("\n") else text + "\n"
    return lines_to_chordpro(_text_to_lines(text))


def _docx_text(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            out.append("   ".join(c.text.strip() for c in row.cells))
    return "\n".join(out)


def _textutil(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "out.txt"
        subprocess.run(["textutil", "-convert", "txt", "-output", str(dst), str(path)],
                       check=True, capture_output=True)
        return dst.read_text(errors="replace")


def convert_file(path: str | Path, selections: Optional[list[dict]] = None, ocr: str = "auto",
                 notes: Optional[list] = None, layout: str = "auto") -> str:
    """notes: pass a list to receive review items (OCR auto-fixes / suggestions)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf" or ext in IMAGE_EXTS:
        return convert_pdf(p, selections, ocr, notes, layout)
    if ext == ".docx":
        return text_to_chordpro(_docx_text(p))
    if ext in TEXTUTIL_EXTS:
        return text_to_chordpro(_textutil(p))
    if ext in TEXT_EXTS or ext == "":
        return text_to_chordpro(p.read_text(encoding="utf-8", errors="replace"))
    raise ValueError(f"Unsupported file type: {ext}")
