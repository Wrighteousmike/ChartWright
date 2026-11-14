"""OCR chord-token clean-up: raised numbers, shouted 'SUS', doubled digits, bar lines."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from chartwright.convert import _read_chord_token, _tidy_chord_token
from chartwright.chords import is_chord_line

bad = 0
def check(name, ok):
    global bad
    print(("PASS " if ok else "FAIL ") + name)
    bad += (not ok)

check("superscript 2", _read_chord_token("F²") == ["F2"])
check("GSUS -> Gsus", _read_chord_token("GSUS") == ["Gsus"])
check("GsuS -> Gsus", _read_chord_token("GsuS") == ["Gsus"])
check("doubled raised digit F22 -> F2", _tidy_chord_token("F22") == "F2")
check("real chords untouched", all(_tidy_chord_token(t) == t for t in ["Am7", "C/E", "D7/F#", "G11", "Dm7(4)", "Gsus"]))
check("bar lines and repeats are neutral", is_chord_line("|: F2 | C/E :||".split()))
check("a lyric is not a chord line", not is_chord_line("I lift my eyes".split()))
from chartwright.convert import Line, Ch, merge_chords
def mk(words, y, step=10.0, start=0.0, gap=1):
    chars, x = [], start
    for w in words:
        for c in w:
            chars.append(Ch(c, x, x + step)); x += step
        chars.append(Ch(" ", x, x + step * gap)); x += step * gap
    return Line(chars[:-1], y, 10.0)
lyr = mk(["diso", "-", "bedience"], 20)          # "diso" 0-40, "-" 50-60, "bedience" 70-150
chd = Line([Ch("F", 66, 76), Ch("2", 76, 84)], 0, 10.0)
check("chord near a syllable after a lone hyphen lands on the syllable, not the hyphen",
      merge_chords(chd, lyr, snap=True) == "diso - [F2]bedience")
sys.exit(1 if bad else 0)
