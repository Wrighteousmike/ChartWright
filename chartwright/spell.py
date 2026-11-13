"""Dictionary logic for OCR'd lyrics: split joined words, rejoin broken ones, repair look-alike
letters, and suggest corrections for words it can't vouch for.

Only lyric words are touched, never chords. Auto-fixes are conservative (same letters, same
positions, or a split of an unknown word into known words); everything else becomes a *suggestion*
that the UI lets the user accept. A chord sitting in a gap between two fragments marks an
intentional syllable split ("ski [G]es"), so those are never rejoined.
"""
from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from .paths import DATA, USER_WORDS
MIN_COUNT = 20_000               # a dictionary entry must be at least this common to be "known"

# 1- and 2-letter English words we accept (the big list is full of junk at this length)
SHORT_OK = {"a", "i", "o", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it",
            "me", "my", "no", "of", "oh", "on", "or", "so", "to", "up", "us", "we", "ye", "am", "ah"}

# look-alike substitutions OCR makes (1 char -> 1 char, so positions are preserved)
CONFUSABLE = {
    "l": "Ii1", "I": "l1", "1": "lI", "|": "lI", "0": "oO", "O": "0", "5": "sS", "S": "5", "8": "B",
    "6": "G", "i": "l", "e": "c", "c": "e", "u": "n", "n": "u", "a": "o", "o": "a", "h": "b", "b": "h",
    "v": "y", "y": "v", "t": "f", "f": "t",
}
DIGITISH = set("01|568")

_WORD = re.compile(r"^([^A-Za-z0-9|]*)([A-Za-z0-9|]+)([^A-Za-z0-9|]*)$")


class Speller:
    def __init__(self):
        import symspellpy
        from symspellpy import SymSpell

        self._sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=6)
        base = Path(symspellpy.__file__).parent / "frequency_dictionary_en_82_765.txt"
        self._sym.load_dictionary(str(base), 0, 1)
        self.extra: dict[str, int] = {}
        self._load_extra(DATA / "extra_words.txt")
        self._load_extra(USER_WORDS)
        self.local: set[str] = set()          # words seen repeatedly in the document being processed

    # -- vocabulary
    def _load_extra(self, path: Path):
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            w, c = parts[0].lower(), int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5_000_000
            self.extra[w] = c
            self._sym.create_dictionary_entry(w, c)

    def add_user_word(self, word: str):
        w = word.strip().lower()
        if not w or not w.isalpha():
            return
        USER_WORDS.parent.mkdir(parents=True, exist_ok=True)
        with open(USER_WORDS, "a", encoding="utf-8") as f:
            f.write(w + "\n")
        self.extra[w] = 5_000_000
        self._sym.create_dictionary_entry(w, 5_000_000)

    def learn_document(self, words: list[str]):
        """Words that occur 2+ times in this chart are probably real (repeated choruses)."""
        cnt = Counter(w.lower() for w in words if w.isalpha() and len(w) >= 3)
        self.local = {w for w, n in cnt.items() if n >= 2}

    def freq(self, w: str) -> int:
        w = w.lower()
        if len(w) <= 2:
            return 10_000_000 if w in SHORT_OK else 0
        if w in self.extra:
            return self.extra[w]
        if w in self.local:
            return 10_000_000
        n = self._sym.words.get(w, 0)
        return n if n >= MIN_COUNT else 0

    def raw_token(self, w: str) -> bool:
        """Is this a real (if rare/abbreviated) token in the big list, even though we don't accept it as a word?"""
        return self._sym.words.get(w.lower(), 0) >= MIN_COUNT

    def known(self, w: str) -> bool:
        return self.freq(w) > 0

    # -- candidate generation
    def _variants(self, core: str, max_subs: int = 2):
        """Yield (variant, n_subs) swapping look-alike characters (length preserved)."""
        idx = [i for i, c in enumerate(core) if c in CONFUSABLE]
        allcaps = core.isupper() and len(core) > 1
        yield core, 0
        for n in range(1, max_subs + 1):
            for pos in itertools.combinations(idx, n):
                for alts in itertools.product(*[CONFUSABLE[core[i]] for i in pos]):
                    v = list(core)
                    for i, a in zip(pos, alts):
                        v[i] = a
                    w = "".join(v)
                    if not allcaps and any(ch.isupper() for ch in w[1:]):
                        continue                     # 'faIl' is not a word shape; 'fall' is
                    yield w, n

    def _segment(self, w: str) -> Optional[list[int]]:
        """Split an unknown run of letters into known words; returns part lengths or None."""
        lw = w.lower()
        if len(lw) < 4 or not lw.isalpha():
            return None
        n = len(lw)
        best: dict[int, tuple[float, list[int]]] = {0: (0.0, [])}
        for end in range(1, n + 1):
            cand = None
            for start in range(max(0, end - 18), end):
                if start not in best:
                    continue
                part = lw[start:end]
                f = self.freq(part)
                if not f or (len(part) < 2 and part not in ("a", "i")) :
                    continue
                if len(part) <= 2 and part not in ("a", "i", "to", "of", "in", "my", "oh", "is", "it", "me", "we", "he", "on", "or", "be", "do", "go", "so", "no", "up", "us", "as", "at", "if", "by", "an", "ye"):
                    continue
                score = best[start][0] + math.log(f / 1e12) - 1.5    # unigram log-prob, small per-word penalty
                if cand is None or score > cand[0]:
                    cand = (score, best[start][1] + [end - start])
            if cand:
                best[end] = cand
        if n in best and len(best[n][1]) >= 2 and len(best[n][1]) <= 3:
            return best[n][1]
        return None

    def suggest(self, word: str, k: int = 3) -> list[str]:
        from symspellpy import Verbosity

        lw = word.lower()
        out: list[str] = []
        for v, _ in self._variants(word, 2):                    # look-alike letters first
            if v != word and self.known(v) and v.lower() not in out:
                out.append(v)
        for s in self._sym.lookup(lw, Verbosity.CLOSEST, max_edit_distance=2):
            if s.term != lw and self.known(s.term) and s.term not in out:
                out.append(s.term)
        seg = self._segment(word)
        if seg:
            parts, p = [], 0
            for L in seg:
                parts.append(word[p:p + L]); p += L
            out.insert(0, " ".join(parts))
        return [_match_case(o, word) for o in out[:k]]

    # -- decisions for one word. Returns ("ok"|"fix"|"split"|"suggest", payload)
    def judge(self, core: str):
        if self.known(core) or core.isdigit():
            return "ok", None
        if len(core) <= 1:
            return "ok", None
        # 1) look-alike letters -> a known word (only if clearly the best reading)
        scored = []
        for v, n in self._variants(core, 2):
            if n and self.known(v):
                scored.append((self.freq(v), n, v))
        scored.sort(key=lambda t: (t[1], -t[0]))
        if scored:
            top = scored[0]
            rest = [s for s in scored[1:] if s[1] == top[1]]
            ambiguous = bool(rest) and rest[0][0] * 10 > top[0]
            has_digit = any(c in DIGITISH for c in core)
            starts_il = core[0] in "Il1|" and top[2][0] in "Ill1|"
            if not ambiguous and (has_digit or not core[0].isupper() or starts_il):
                return "fix", _match_case(top[2], core)
        # 2) joined words: unknown, but splits cleanly into known words (also via look-alikes)
        for v, n in self._variants(core, 1):
            seg = self._segment(v)
            if seg:
                return "split", (v, seg)
        return "suggest", None


def _match_case(cand: str, ref: str) -> str:
    if ref.isupper() and len(ref) > 1:
        return cand.upper()
    if ref[:1].isupper() and cand[:1].islower():
        return cand[:1].upper() + cand[1:]
    return cand


_SPELLER: Optional[Speller] = None


def get_speller() -> Speller:
    global _SPELLER
    if _SPELLER is None:
        _SPELLER = Speller()
    return _SPELLER


def available() -> bool:
    try:
        import symspellpy  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False
