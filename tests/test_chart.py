"""Chord chart preview/PDF: .venv/bin/python tests/test_chart.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fitz
from chordpro_maker.chart import parse, original_key, transpose_chord, render_pdf

text = (ROOT / "tests/samples/title-clear.expected.cho").read_text()
ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", name, extra)

def pdf_text(data):
    with fitz.open("pdf", data) as d:
        return "\n".join(p.get_text() for p in d), len(d)

check("transpose C->G (+7)", [transpose_chord(c, 7, False) for c in ("C", "Am", "F/A", "Dm7", "G")] == ["G", "Em", "C/E", "Am7", "D"])
check("flats vs sharps", transpose_chord("C", 3, True) == "Eb" and transpose_chord("C", 2, False) == "D" and transpose_chord("F", 1, False) == "F#")
check("non-chords untouched", transpose_chord("N.C.", 5, False) == "N.C.")
s = parse(text)
check("directives parsed", s.title.startswith("When I can read") and s.key == "C" and original_key(s) == (0, False))

data, info = render_pdf(text)
t, n = pdf_text(data)
check("original key renders", "Key: C" in t and "Am" in t and "weeping" in t and info["original"] == "C", info["pages"])

data, info = render_pdf(text, key="G")
t, _ = pdf_text(data)
check("key G: tonic and a transposed minor chord", "Key: G" in t and "Em" in t and "Dm7" not in t and "Am7" in t)

data, info = render_pdf(text, key="G", capo=2)
t, _ = pdf_text(data)
check("key G + capo 2 prints shapes in F", "Capo: 2" in t and "play shapes in F" in t and "Bb" in t and info["shapes"] == "F", info["shapes"])

d1, i1 = render_pdf(text, columns=1)
d2, i2 = render_pdf(text, columns=2)
check("two columns need fewer pages than one", i2["pages"] < i1["pages"], (i1["pages"], i2["pages"]))
with fitz.open("pdf", d2) as d:
    xs = {round(b[0]) for b in d[0].get_text("blocks") if b[1] > 150}
check("two columns really are side by side", len({x for x in xs if x > 300}) >= 1 and len({x for x in xs if x < 100}) >= 1, sorted(xs)[:6])

check("empty text still renders", render_pdf("")[0][:4] == b"%PDF")
long_pdf = render_pdf("{title: T}\n" + "[C]word " * 80, columns=1)[0]
with fitz.open("pdf", long_pdf) as d:
    right = max(b[2] for p in d for b in p.get_text("blocks"))
check("long lines wrap inside the page", right <= 595 - 46 + 2, right)
with fitz.open("pdf", render_pdf("Ski  [G]es here", size="small")[0]) as d:
    w = {x[4]: x for x in d[0].get_text("words")}
check("syllable padding does not split a word", "Ski" in w and "es" in w and abs(w["es"][0] - w["Ski"][2]) < 1.0,
      (w.get("Ski"), w.get("es")))
sys.exit(0 if ok else 1)
