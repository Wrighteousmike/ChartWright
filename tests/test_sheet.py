"""Digital sheet music -> ChordPro: .venv/bin/python tests/test_sheet.py
The expected file was checked by eye against the rendered score."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chartwright.readers import convert_file
from chartwright.sheetmusic import find_staves, decode_chord
import fitz

S = ROOT / "tests" / "samples"
pdf = S / "risen-conqueror.lead.pdf"
if not pdf.exists():   # copyrighted lead sheet: kept out of the public repo
    print("SKIP sheet-music tests: add your own lead-sheet PDF as tests/samples/risen-conqueror.lead.pdf (+ .expected.cho)")
    sys.exit(0)
ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", name, extra)

check("8 staves found from the vector drawings", len(find_staves(fitz.open(pdf)[0])) == 8)
check("chord-font glyphs decode", [decode_chord(x)[0] for x in ("B¨", "G‹", "F(“4)", "B¨7/D", "C7")] == ["Bb", "Gm", "Fsus4", "Bb7/D", "C7"])

got = convert_file(pdf)                              # layout auto-detects sheet music
want = (S / "risen-conqueror.expected.cho").read_text()
check("whole sheet matches the verified output", got == want)
check("4 verses, 8 lines each (verse 4 starts mid-song)", [len([l for l in sec.splitlines()[1:]]) for sec in got.split("\n\n")[2:]] == [8, 8, 8, 5],
      [len(sec.splitlines()) - 1 for sec in got.split("\n\n")[2:]])
check("header: title, credits, key, copyright, CCLI",
      all(x in got for x in ("{title: The Risen Conqueror}", "{lyricist: Sam Brewster}", "{arranger: Tom Brewster}",
                              "{key: Bb}", "{copyright: © 2024 Joyful Noise", "{meta: ccli 7244445}")))
check("repeat pickups ('2. Long lay our' at the end) are not duplicated", got.count("Long lay our") == 1)
check("syllables joined into words, chords land mid-word", "diso[Eb]bedience" in got and "ex-\n" in got)
check("verse 4 opens on the chord already sounding", "{comment: Verse 4}\n[Bb]Now [Bb/A]unto" in got)

# drag a box over the first two systems only
sel = convert_file(pdf, [{"page": 0, "rect": [30, 85, 570, 262]}])
check("selection box: only the first two systems", "Declared in" in sel and "curse" not in sel and sel.count("{comment: Verse") >= 3,
      sel.count("{comment: Verse"))
# a normal chord chart must not be mistaken for sheet music
chart = convert_file(S / "title-clear.pdf")
check("chord charts still use the chart reader", "{comment: Verse 1}" in chart and "[C]I can read" in chart)
sys.exit(0 if ok else 1)
