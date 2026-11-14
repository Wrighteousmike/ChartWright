// Chord-shift logic: pure functions (no DOM) so they can be unit-tested with node.
// A ChordPro line "Be[C]fore [G]you" is held as plain text "Before you" plus chords [{pos, name}],
// where pos = index of the character the chord sits in front of (pos === text.length means "after the last character").
(function (root) {
  const CHORD = /\[([^\]]*)\]/g;

  function parseLine(raw) {
    const chords = []; let text = '', last = 0, m;
    CHORD.lastIndex = 0;
    while ((m = CHORD.exec(raw))) {
      text += raw.slice(last, m.index);
      chords.push({ pos: text.length, name: m[1] });
      last = m.index + m[0].length;
    }
    text += raw.slice(last);
    return { text, chords };
  }

  // chords keep their relative order when they share a position
  function serializeLine(line) {
    const order = line.chords.map((c, i) => [c, i]).sort((a, b) => a[0].pos - b[0].pos || a[1] - b[1]).map(x => x[0]);
    let out = '', k = 0;
    for (let i = 0; i <= line.text.length; i++) {
      while (k < order.length && order[k].pos === i) out += '[' + order[k++].name + ']';
      if (i < line.text.length) out += line.text[i];
    }
    return out;
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function moveChord(line, idx, newPos) {
    const c = line.chords[idx];
    if (!c) return false;
    const p = clamp(Math.round(newPos), 0, line.text.length);
    if (p === c.pos) return false;
    c.pos = p;
    return true;
  }

  // next/previous word start from pos (dir = +1 / -1); falls back to the line ends
  function wordStep(text, pos, dir) {
    const start = i => i === 0 ? text.length > 0 && text[0] !== ' ' : text[i - 1] === ' ' && text[i] !== undefined && text[i] !== ' ';
    if (dir > 0) { for (let i = pos + 1; i < text.length; i++) if (start(i)) return i; return text.length; }
    for (let i = pos - 1; i > 0; i--) if (start(i)) return i;
    return 0;
  }

  const api = { parseLine, serializeLine, moveChord, wordStep };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ChordShift = api;
})(typeof window !== 'undefined' ? window : globalThis);
