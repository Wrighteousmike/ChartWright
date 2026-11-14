"""Two-column pages: .venv/bin/python tests/test_columns.py  (builds its own synthetic PDF, nothing copyrighted)"""
import sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fitz
from chartwright.readers import convert_file

ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", name, extra)

def make(path):
    d = fitz.open(); p = d.new_page()
    p.insert_text((50, 50), "Test Song", fontsize=16)
    p.insert_text((50, 66), "Key - C", fontsize=9)
    def block(x, y, label, rows):
        p.insert_text((x, y), label, fontsize=9, fontname="hebo"); y += 16
        for chords, lyric in rows:
            for cx, c in chords: p.insert_text((x + cx, y), c, fontsize=9, fontname="hebo")
            y += 11; p.insert_text((x, y), lyric, fontsize=9); y += 16
        return y
    # left and right columns deliberately sit on DIFFERENT baselines, as in real exports
    block(50, 110, "VERSE 1", [([(0, "C"), (60, "F")], "Left column line one here"), ([(10, "G")], "Left column line two here")])
    block(330, 103, "CHORUS", [([(0, "Am"), (70, "G")], "Right column line one here"), ([(20, "D")], "Right column line two here")])
    for i, t in enumerate(["Footer text centred on the page across the gutter", "Another centred footer line", "(c) centred"]):
        p.insert_text((297 - fitz.get_text_length(t, fontsize=8) / 2, 700 + i * 10), t, fontsize=8)
    d.save(path)

with tempfile.TemporaryDirectory() as t:
    pdf = Path(t) / "two.pdf"; make(pdf)
    for mode in ("auto", "2"):
        out = convert_file(pdf, columns=mode)
        i_left, i_right = out.find("line two here"), out.find("{comment: Chorus}")
        check(f"columns={mode}: left column is read fully before the right", 0 < i_left < i_right, out.replace("\n", " | ")[:200])
        check(f"columns={mode}: chords stay with their own column's words",
              "[C]Left" in out and "[Am]Right" in out and "[G]" in out, "")
    out = convert_file(pdf)
    check("centred footer ends up after both columns", out.find("Footer text") > out.rfind("column l"))
sys.exit(0 if ok else 1)
