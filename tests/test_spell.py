"""Dictionary logic: .venv/bin/python tests/test_spell.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chordpro_maker.lyricfix import correct_lyric, correct_plain
from chordpro_maker.spell import get_speller
from chordpro_maker.convert import Ch, Line

sp = get_speller()
CASES = [   # (input, expected output after automatic fixes)
    ("bidfarewell to every fear", "bid farewell to every fear"),
    ("Whenl can read mytitle clear", None),                       # only 'mytitle' must be fixed
    ("Let storm s of sorrow faII", "Let storms of sorrow fall"),
    ("Itake my hand and the Iord is near", "I take my hand and the Lord is near"),
    ("Satan's rage and hom e", "Satan's rage and home"),
    ("Jesus loves me this I know", "Jesus loves me this I know"),            # untouched
    ("Jehovah Jireh Emmanuel Gethsemane", "Jehovah Jireh Emmanuel Gethsemane"),  # names/hymn words untouched
    ("with al my heart", "with al my heart"),                                 # no bogus 'withal'
]
ok = True
for src, want in CASES:
    got = correct_plain(src, sp, [])
    good = (want is None and "my title" in got) or got == want
    ok &= good
    print(("PASS" if good else "FAIL"), repr(src), "->", repr(got))

# suggestions are offered, not applied
n = []
out = correct_plain("The Lord is my sheperd", sp, n)
sg = [x for x in n if x["kind"] == "suggest"]
good = out.endswith("sheperd") and sg and sg[0]["suggestions"][0] == "shepherd"
ok &= bool(good); print("PASS" if good else "FAIL", "suggestion, not auto-applied:", [(x["frm"], x["suggestions"]) for x in sg])

# a chord sitting in the gap marks an intentional syllable split -> fragments are left alone
def line(text, y=0.0):
    return Line([Ch(c, i, i + 1) for i, c in enumerate(text)], y)
lyric, chords = line("wor ld and hur led"), line("    G         F    ")   # G over 'ld', F over 'led'
chords = line("    G          F")
out = correct_lyric(lyric, chords, sp, []).text
good = out == "wor ld and hur led"
ok &= good; print("PASS" if good else "FAIL", "chord-marked syllable splits kept:", repr(out))
out = correct_lyric(lyric, None, sp, []).text            # same text, no chords -> rejoined
good = out == "world and hurled"
ok &= good; print("PASS" if good else "FAIL", "without chords they are rejoined:", repr(out))
sys.exit(0 if ok else 1)
