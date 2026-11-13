"""Key plausibility: .venv/bin/python tests/test_keys.py"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chordpro_maker.keys import check_groups, best_key, parse_chord, key_name

text = (ROOT / "tests/samples/title-clear.expected.cho").read_text()
groups, cur = [], []
for line in text.splitlines():
    if line.startswith("{comment:"):
        if cur: groups.append(cur)
        cur = []
    cur += re.findall(r"\[([^\]]+)\]", line)
groups.append(cur)

ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", name, extra)

keys = [key_name(*best_key([parse_chord(c) for c in g])[:2]) for g in groups]
check("per-section keys: Verse 1/2 = C, Verse 3 = D (header says C!)", keys == ["C", "C", "D"], keys)
check("clean chart raises no questions", all(not f for f in check_groups(groups, "C")),
      [list(f.values()) for f in check_groups(groups, "C") if f])

# a dropped 'm' (Am -> A) and a letter slip should be questioned, with a sensible suggestion
bad = [list(g) for g in groups]
bad[0][bad[0].index("Am")] = "A"
f = check_groups(bad, "C")[0]
check("'A' where the key wants 'Am' is flagged with 'Am' suggested",
      any(v["chord"] == "A" and "Am" in v["suggestions"] for v in f.values()), list(f.values()))

bad = [list(g) for g in groups]
bad[2][bad[2].index("Em")] = "F#"            # F# does not fit D major as a plain chord
f = check_groups(bad, "C")[2]
check("plain F# major in D (the key wants F#m, if anything) is questioned",
      any(v["chord"] == "F#" for v in f.values()), [v["why"] + " -> " + ",".join(v["suggestions"]) for v in f.values()])
bad = [list(g) for g in groups]
bad[0][2] = "Eb"; bad[0][5] = "Ab"           # nonsense chords in C
f = check_groups(bad, "C")[0]
check("chords far outside the key are flagged", len(f) >= 1, [v["why"] for v in f.values()])

# a chord used many times is the arrangement's choice, not an OCR error
many = [["C", "F", "G", "C", "Bb", "C", "F", "Bb", "G", "Bb", "C", "Bb"]]
check("repeated borrowed chord (Bb in C) is not nagged", not check_groups(many, "C")[0])
check("too few chords -> stays quiet", not any(check_groups([["C", "Q"]], "C")))

# end to end through the converter: chord-over-lyric text with 'Am' misread as 'A' in Verse 1
from chordpro_maker.convert import lines_to_chordpro
from chordpro_maker.readers import _text_to_lines
sheet = (ROOT / "tests/samples/title-clear.chordsheet.txt").read_text()
bad_sheet = re.sub(r"\bAm(\s+Dm7)", lambda m: "A " + m.group(1), sheet, count=1)   # first Am (Verse 1) -> A
assert bad_sheet != sheet
notes = []
out = lines_to_chordpro(_text_to_lines(bad_sheet), ocr=True, notes=notes)
kn = [n for n in notes if n["kind"] == "key"]
check("converter raises a key note for the misread chord", any(n["frm"] == "[A]" and "[Am]" in n["suggestions"] for n in kn),
      [(n["frm"], n["suggestions"], n["line"]) for n in kn])
check("note points at the right output line", kn and "[A]" in out.splitlines()[kn[0]["line"]], kn[0]["line"] if kn else None)
clean = []
lines_to_chordpro(_text_to_lines(sheet), ocr=True, notes=clean)
check("the clean sheet raises no key notes", not [n for n in clean if n["kind"] == "key"], [n["frm"] for n in clean if n["kind"] == "key"])
sys.exit(0 if ok else 1)
