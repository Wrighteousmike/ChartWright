"""Run: .venv/bin/python tests/test_sample.py
Converts the sample PDF and compares with the hand-made ChordPro file
(ignoring runs of spaces, which the PDF cannot tell us about)."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chordpro_maker.readers import convert_file, text_to_chordpro

S = ROOT / "tests" / "samples"
norm = lambda t: [re.sub(r"\s+", " ", l).strip() for l in t.strip().splitlines()]


def check(name, got, want):
    g, w = norm(got), norm(want)
    bad = [(i + 1, a, b) for i, (a, b) in enumerate(zip(g, w)) if a != b]
    ok = g == w
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({len(w)} lines)")
    for i, a, b in bad[:10]:
        print(f"   line {i}\n     got : {a}\n     want: {b}")
    if len(g) != len(w):
        print(f"   line count {len(g)} vs {len(w)}")
    return ok


want = (S / "title-clear.expected.cho").read_text()
results = [check("PDF -> ChordPro", convert_file(S / "title-clear.pdf"), want)]

# chord-over-lyric plain text (what you'd get from a .txt/.docx) -> same song
text = (S / "title-clear.chordsheet.txt")
if text.exists():
    results.append(check("plain-text chord sheet -> ChordPro", convert_file(text), want))
# already-ChordPro input passes straight through
results.append(check("ChordPro passthrough", text_to_chordpro(want), want))

# ---- OCR: a degraded scan (rotated, blurred, noisy) as image-only PDF and as a JPG.
# OCR is never perfect, so score it: chords recovered and lines matching the original.
def check_ocr(name, path, selections=None, want_text=want, min_chords=0.95, min_lines=0.85):
    got = convert_file(path, selections)
    g, w = norm(got), norm(want_text)
    chords = lambda t: len(re.findall(r"\[", t))
    rec = chords(got) / max(1, chords(want_text))
    lines = sum(a == b for a, b in zip(g, w)) / len(w)
    ok = rec >= min_chords and lines >= min_lines
    print(f"{'PASS' if ok else 'FAIL'}  {name}  chords {rec:.0%}  exact lines {lines:.0%}")
    return ok

results.append(check_ocr("scanned PDF (OCR)", S / "title-clear.scan.pdf"))
results.append(check_ocr("scanned JPG (OCR)", S / "title-clear.scan.jpg"))
# harder scans: faded (low contrast) and high-res. Chords are the point: recall AND no invented chords.
def check_chords(name, path, min_recall=0.95, max_extra=1):
    from collections import Counter
    got = Counter(re.findall(r"\[([^\]]+)\]", convert_file(path)))
    exp = Counter(re.findall(r"\[([^\]]+)\]", want))
    rec = sum((got & exp).values()) / sum(exp.values())
    extra = sum((got - exp).values())
    ok = rec >= min_recall and extra <= max_extra
    print(f"{'PASS' if ok else 'FAIL'}  {name}  chords found {rec:.0%}, invented {extra}")
    return ok

results.append(check_chords("faded scan: chord recall", S / "title-clear.faded.jpg"))
results.append(check_chords("hi-res scan: chord recall", S / "title-clear.hires.jpg", 0.99, 0))
# drag-box on the scan: right-hand column only = Verse 3
sel = convert_file(S / "title-clear.scan.pdf", [{"page": 0, "rect": [300, 75, 590, 400]}])
v3 = want[want.index("{comment: Verse 3}"):]
results.append(check_ocr("scan + selection box (Verse 3)", S / "title-clear.scan.pdf",
                         [{"page": 0, "rect": [300, 75, 590, 400]}], v3, 0.95, 0.9))
sys.exit(0 if all(results) else 1)
