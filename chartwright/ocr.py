"""OCR for scanned charts (PDF pages that are images, or photo/scan files).

Engine: RapidOCR (ONNX, models bundled inside the project's .venv — no system install, no network).
The output is converted to the same (char, x0, x1, baseline_y, size) tuples the PDF text-layer
reader produces, in PDF points, so column / chord / layout logic is shared.
"""
from __future__ import annotations

import io
import logging
import statistics
from typing import Optional

_ENGINE = None
_REC_ENGINE = None   # separate instance for single-mark reads: rec-only calls change a shared engine's output format


def available() -> bool:
    try:
        import rapidocr  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR
        logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)
        # permissive detection: chord letters are short, isolated and easy to miss at defaults
        _ENGINE = RapidOCR(params={
            "Global.text_score": 0.1, "Det.box_thresh": 0.2, "Det.thresh": 0.1, "Det.unclip_ratio": 2.0,
        })
        logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)
    return _ENGINE


def _rec_engine():
    global _REC_ENGINE
    if _REC_ENGINE is None:
        from rapidocr import RapidOCR
        logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)
        _REC_ENGINE = RapidOCR()
        logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)
    return _REC_ENGINE


# ---------------------------------------------------------------- image prep
def _estimate_skew(gray) -> float:
    """Degrees to rotate to make text lines horizontal (projection-profile search)."""
    import numpy as np
    from PIL import Image

    small = gray.copy()
    small.thumbnail((900, 900))
    a = np.asarray(small, dtype=np.float32)
    ink = (a < (a.mean() - 0.5 * a.std())).astype(np.float32)
    if ink.sum() < 50:
        return 0.0
    im = Image.fromarray((ink * 255).astype("uint8"))
    best, best_ang = -1.0, 0.0
    for ang in np.arange(-4.0, 4.01, 0.25):
        r = np.asarray(im.rotate(float(ang), resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)
        score = float(np.var(r.sum(axis=1)))
        if score > best:
            best, best_ang = score, float(ang)
    return best_ang


def prepare(png_bytes: bytes):
    """Grayscale, auto-contrast, deskew. Returns a PIL image."""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(png_bytes)).convert("L")
    im = ImageOps.autocontrast(im, cutoff=2)
    ang = _estimate_skew(im)
    if abs(ang) >= 0.2:
        im = im.rotate(ang, resample=Image.BICUBIC, expand=True, fillcolor=255)
    return im



# ---------------------------------------------------------------- missed-chord recovery
def _as_chords(txt: str):
    """Read OCR text as chord tokens, tolerating the usual slips (c -> C, trailing 1 -> 7). None if not chords."""
    from .convert import _split_chords

    txt = txt.strip().replace("♯", "#").replace("♭", "b")
    for cand in (txt, txt[:1].upper() + txt[1:], txt[:-1] + "7" if txt.endswith("1") else None,
                 (txt[:1].upper() + txt[1:])[:-1] + "7" if txt.endswith("1") else None):
        if not cand:
            continue
        toks = cand.split()
        out = []
        for t in toks:
            sp = _split_chords(t)
            if not sp:
                out = None
                break
            out += sp
        if out:
            return out
    return None


def _recover_chords(img, res, line_infos, scale, origin_x, origin_y):
    """Find ink the detector ignored just above lyric lines, read each mark alone, keep valid chords."""
    import cv2
    import numpy as np

    gray = np.asarray(img.convert("L"))
    H, W = gray.shape
    if not line_infos:
        return []
    h = float(np.median([li["h"] for li in line_infos]))
    if h < 8:
        return []

    # binarise (dark ink = 255), drop specks
    bs = max(15, int(h * 2) | 1)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, bs, 12)
    # blank out everything the detector already claimed
    claimed = np.zeros_like(ink)
    for poly in res.boxes:
        cv2.fillPoly(claimed, [np.asarray(poly, dtype=np.int32)], 255)
    claimed = cv2.dilate(claimed, np.ones((3, 3), np.uint8))
    ink[claimed > 0] = 0
    n0, lab0, st0, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = st0[:, cv2.CC_STAT_AREA] >= 0.03 * h * h          # vectorised: one lookup, not one scan per speck
    keep[0] = False
    ink = np.where(keep[lab0], ink, 0).astype(np.uint8)

    # cluster neighbouring strokes into marks (chord glyphs sit close; separate chords are far apart)
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(0.35 * h)), max(3, int(0.12 * h))))
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(ink, kern), connectivity=8)

    lyric = [li for li in line_infos if li["lyric"]]
    out = []
    eng = _rec_engine()
    for k in range(1, n):
        x, y, w, hh, area = st[k]
        if not (0.3 * h <= hh <= 1.7 * h and 0.15 * h <= w <= 7 * h):
            continue
        cy = y + hh / 2
        # must sit in the band above a lyric line, horizontally within its span
        if not any(0 < li["cy"] - cy < 2.3 * h and li["x0"] - 2 * h <= x + w / 2 <= li["x1"] + 3 * h for li in lyric):
            continue
        # tight bounding box of the real ink (not the dilated cluster)
        ys, xs = np.nonzero(ink[y:y + hh, x:x + w])
        if len(xs) == 0:
            continue
        tx0, tx1, ty0, ty1 = x + xs.min(), x + xs.max() + 1, y + ys.min(), y + ys.max() + 1
        pad = int(0.35 * h)
        crop = gray[max(0, ty0 - pad):min(H, ty1 + pad), max(0, tx0 - pad):min(W, tx1 + pad)]
        crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        try:
            r = eng(cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB), use_det=False, use_cls=False, use_rec=True)
        except Exception:  # noqa: BLE001
            continue
        if not r or not r.txts:
            continue
        toks = _as_chords(r.txts[0])
        conf = float(r.scores[0]) if r.scores else 0.0
        if not toks or conf < 0.2:
            continue
        # lay the characters out evenly across the mark's tight box
        text = " ".join(toks)
        step = (tx1 - tx0) / max(1, len(text))
        size = max(4.0, 0.8 * h / scale)
        Y = origin_y + (ty1 - 0.0) / scale
        chars = []
        for i, c in enumerate(text):
            chars.append((c, origin_x + (tx0 + i * step) / scale, origin_x + (tx0 + (i + 1) * step) / scale, Y, size))
        chars.append((" ", chars[-1][2], chars[-1][2], Y, size))
        out.append((chars, min(conf, 0.5)))
    return out

# ---------------------------------------------------------------- recognition
def recognise_pixmap(png_bytes: bytes, center_x: float, center_y: float, scale: float):
    """OCR a rendered image. Returns [(chars, confidence)] per text line; chars are tuples in page points.

    scale: image pixels per PDF point. center: page position of the region's centre. Coordinates are anchored
    to the centre (not a corner) so passes at different zooms/deskew expansions agree with each other.
    """
    import numpy as np

    img = prepare(png_bytes)
    origin_x = center_x - img.width / 2 / scale
    origin_y = center_y - img.height / 2 / scale
    res = _engine()(np.asarray(img.convert("RGB")), return_word_box=True, return_single_char_box=True)
    if res is None or res.word_results is None:
        return []

    lines_out = []
    line_infos = []
    txts = list(res.txts) if res.txts is not None else []
    for li, line in enumerate(res.word_results):
        cl = [(t, b) for t, conf, b in line if t and t.strip()]
        if not cl:
            continue
        chars = []
        boxes = []
        for t, b in cl:
            xs = [p[0] for p in b]
            ys = [p[1] for p in b]
            boxes.append((t, min(xs), max(xs), min(ys), max(ys)))
        widths = [x1 - x0 for _, x0, x1, _, _ in boxes if x1 > x0]
        mw = statistics.median(widths) if widths else 1.0
        h = statistics.median(y1 - y0 for _, _, _, y0, y1 in boxes)
        base = statistics.median(y1 for _, _, _, _, y1 in boxes) - 0.12 * h
        size = max(4.0, 0.8 * h / scale)
        X = lambda v: origin_x + v / scale          # noqa: E731
        Y = origin_y + base / scale

        # Prefer the recogniser's own text (it has correct spaces); boxes supply positions.
        text = txts[li] if li < len(txts) else None
        if text is not None and len(text.replace(" ", "")) == len(boxes) and \
                all(a == b[0] for a, b in zip(text.replace(" ", ""), boxes)):
            bi = 0
            prev_x1 = None
            pending = False
            for ch in text:
                if ch == " ":
                    pending = True
                    continue
                t, x0, x1, _, _ = boxes[bi]
                bi += 1
                if pending and prev_x1 is not None:
                    chars.append((" ", X(prev_x1), X(max(x0, prev_x1)), Y, size))
                pending = False
                chars.append((t, X(x0), X(x1), Y, size))
                prev_x1 = x1
        else:                                          # fallback: infer spaces from gaps
            prev_x1 = None
            for t, x0, x1, _, _ in boxes:
                if prev_x1 is not None and x0 - prev_x1 > 0.6 * mw:
                    chars.append((" ", X(prev_x1), X(x0), Y, size))
                chars.append((t, X(x0), X(x1), Y, size))
                prev_x1 = x1
        if chars and not chars[-1][0].isspace():
            chars.append((" ", chars[-1][2], chars[-1][2], Y, size))
        if chars:
            ltxt = (text or "")
            line_infos.append(dict(
                h=h, cy=statistics.median((y0 + y1) / 2 for _, _, _, y0, y1 in boxes),
                x0=min(b[1] for b in boxes), x1=max(b[2] for b in boxes),
                lyric=sum(ch.isalpha() for ch in ltxt) >= 3 and sum(ch.islower() for ch in ltxt) >= 2))
            sc = float(res.scores[li]) if res.scores is not None and li < len(res.scores) else 0.5
            lines_out.append((chars, sc))
    try:
        lines_out += _recover_chords(img, res, line_infos, scale, origin_x, origin_y)
    except Exception:  # noqa: BLE001 - recovery is a bonus, never a blocker
        pass
    return lines_out


def _bbox(line):
    xs = [c[1] for c in line] + [c[2] for c in line]
    h = line[0][4] / 0.8                       # ~ detected box height in points
    return min(xs), line[0][3] - 0.88 * h, max(xs), line[0][3] + 0.12 * h


def _overlap_frac(a, b):
    """Overlap area as a fraction of the smaller box."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1e-6, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def _text_of(line) -> str:
    return "".join(c[0] for c in line if not c[0].isspace()).lower()


def _same_text(a, b) -> bool:
    """Long-ish lines only: is one line's text (mostly) contained in the other's? (re-read, or fragment of a line)
    Chords are far too short to qualify, so a chord is never mistaken for part of the lyric under it."""
    import difflib
    ta, tb = _text_of(a), _text_of(b)
    if min(len(ta), len(tb)) < 6:
        return False
    m = sum(x.size for x in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_matching_blocks())
    return m / min(len(ta), len(tb)) > 0.6


def _near_same_row(a, b) -> bool:
    """Loose geometry for the text test (passes deskew slightly differently): within a line height, x-overlapping."""
    h = max(a[3] - a[1], b[3] - b[1])
    if abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2) > 1.0 * h:
        return False
    w = min(a[2], b[2]) - max(a[0], b[0])
    return w > 0.3 * min(a[2] - a[0], b[2] - b[0])


def _same_line(a, b):
    """Two detections of the same text: similar vertical centre, overlapping horizontally."""
    h = min(a[3] - a[1], b[3] - b[1])
    if abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2) > 0.4 * h:
        return False
    w = min(a[2], b[2]) - max(a[0], b[0])
    return w > 0.4 * min(a[2] - a[0], b[2] - b[0])


def ocr_page_chars(page, clip=None, passes=(2600, 1800)):
    """Render the page (or clip) at a couple of resolutions, OCR each, and union the text lines
    (detection is noisy: a chord missed at one scale is often found at another)."""
    import fitz

    rect = fitz.Rect(clip) if clip else page.rect
    pool: list = []          # every reading from every pass: (chars, bbox, confidence)
    for max_px in passes:
        zoom = min(300 / 72, max_px / max(rect.width, rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        for line, conf in recognise_pixmap(pix.tobytes("png"), (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2, zoom):
            pool.append((line, _bbox(line), conf))
    # Greedy merge, order-independent: longest reading first (then most confident); a reading is dropped
    # if something already kept covers the same text in the same place (re-read, or a fragment of a line).
    pool.sort(key=lambda t: (-len(_text_of(t[0])), -t[2]))
    kept: list = []
    for line, bb, conf in pool:
        dup = any(_same_line(bb, k[1]) or (_near_same_row(bb, k[1]) and _same_text(line, k[0])) for k in kept)
        if not dup:
            kept.append((line, bb, conf))
    # restore reading order (top to bottom, left to right) so downstream grouping is stable
    kept.sort(key=lambda t: (round(t[1][1] / 4), t[1][0]))
    return [c for line, _, _ in kept for c in line]
