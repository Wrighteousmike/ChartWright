"""Chord-shift logic (runs the browser's own shift.js under node): .venv/bin/python tests/test_shift.py"""
import json, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
node = shutil.which("node")
if not node:
    print("SKIP chord-shift tests: node not installed"); sys.exit(0)

JS = r"""
const S = require(process.argv[1]);
const out = [];
const t = (name, cond, extra) => out.push([name, !!cond, extra === undefined ? '' : String(extra)]);
const sample = "When [C]I can read my [F]title clear";
let L = S.parseLine(sample);
t("parse: text without markers", L.text === "When I can read my title clear", L.text);
t("parse: chord positions", JSON.stringify(L.chords) === JSON.stringify([{pos:5,name:'C'},{pos:19,name:'F'}]), JSON.stringify(L.chords));
t("round trip is exact", S.serializeLine(L) === sample);
for (const raw of ["[Am]eyes.  [G]    [F]", "[C] [G] [Am]", "no chords at all", "[C][C/E][F2]And rise", "Ski  [G]es", "end[D]", ""]) {
  t("round trip: " + JSON.stringify(raw), S.serializeLine(S.parseLine(raw)) === raw);
}
L = S.parseLine("When [C]I can read my [F]title clear");
t("move right by 2", S.moveChord(L, 0, 7) && S.serializeLine(L) === "When I [C]can read my [F]title clear", S.serializeLine(L));
L = S.parseLine("When [C]I can read my [F]title clear");
S.moveChord(L, 1, 18);
t("move left by 1 (mid-word allowed)", S.serializeLine(L) === "When [C]I can read my[F] title clear", S.serializeLine(L));
L = S.parseLine("ab[C]cd");
t("clamps at the line start", S.moveChord(L, 0, -5) && S.serializeLine(L) === "[C]abcd");
L = S.parseLine("ab[C]cd");
t("clamps at the line end", S.moveChord(L, 0, 99) && S.serializeLine(L) === "abcd[C]");
L = S.parseLine("ab[C]cd");
t("no-op move reports false", S.moveChord(L, 0, 2) === false);
L = S.parseLine("ab[C][G]cd");
S.moveChord(L, 0, 4);
t("moving one chord leaves its neighbour", S.serializeLine(L) === "ab[G]cd[C]", S.serializeLine(L));
L = S.parseLine("[C]hello [G]world");
S.moveChord(L, 1, 0);
t("chords landing together keep a stable order", S.serializeLine(L) === "[C][G]hello world", S.serializeLine(L));
t("word step right", S.wordStep("hello big world", 0, 1) === 6 && S.wordStep("hello big world", 6, 1) === 10);
t("word step left", S.wordStep("hello big world", 10, -1) === 6 && S.wordStep("hello big world", 6, -1) === 0);
t("word step stops at the ends", S.wordStep("hi there", 3, 1) === 8 && S.wordStep("hi there", 0, -1) === 0);
const other = S.parseLine("a [C]b"); const before = JSON.stringify(other.text);
S.moveChord(other, 0, 0);
t("text itself never changes", JSON.stringify(other.text) === before && S.serializeLine(other).replace(/\[C\]/, "") === "a b");
console.log(JSON.stringify(out));
"""
r = subprocess.run([node, "-e", JS, str(ROOT / "chartwright/static/shift.js")], capture_output=True, text=True)
if r.returncode:
    print("FAIL node error:", r.stderr[:400]); sys.exit(1)
ok = True
for name, cond, extra in json.loads(r.stdout.strip().splitlines()[-1]):
    ok &= cond; print("PASS" if cond else "FAIL", name, extra if not cond else "")
sys.exit(0 if ok else 1)
