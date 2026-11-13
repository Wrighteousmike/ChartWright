# ChartWright

Turns a chord chart (PDF, scan/photo, DOCX or text) into a ChordPro `.cho` file. For PDFs you can drag a box
around just the part of the chart you want.

Everything lives in this folder (code, samples, and a private `.venv`). Nothing is read from or written
to other projects; uploads are kept in `.work/` and deleted when the server stops.

## Run

**Double-click `ChartWright.app`** (in this folder; drag it to the Dock if you like). It starts the local server
quietly, opens your browser, and reopens the same page if it is already running. The server quits by itself a couple
of minutes after you close the tab. If anything misbehaves, double-click `Start ChartWright.command` instead
(same thing in a visible Terminal window), or look in `.run/server.log`. Keep the app inside the project folder; if
the folder is moved, the app rebuilds its private Python environment on first launch (needs internet once).

From a terminal:

    cd path/to/ChartWright
    .venv/bin/python -m chartwright            # opens http://127.0.0.1:8791 (next free port if busy)

Drop a file on the page. For a PDF, drag one or more boxes on the page image (boxes can span pages and
are combined in order), press **Convert**, edit the text if needed, then **Copy** or **Save .cho**.
With no boxes the whole document is converted.

Command line:

    .venv/bin/python -m chartwright convert chart.pdf -o song.cho
    .venv/bin/python -m chartwright convert chart.pdf --page 1 --rect 300,75,590,400

Setup from scratch: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

## Supported input

| Type | How |
|---|---|
| PDF with a text layer | Characters + positions via PyMuPDF; columns detected; each chord is placed on the lyric character beneath it |
| Digital sheet music / lead sheet PDF (Sibelius, MuseScore, Finale, Dorico…) | Auto-detected from the staff lines; see "Sheet music" below |
| Scanned PDF, or an image (.png .jpg .tif .bmp .gif .webp) | Built-in OCR (see below), then the same pipeline as above |
| .docx | Paragraph text, treated as chord-over-lyrics (best in a monospace font such as Courier) |
| .txt .md .crd .pro … | Chord-over-lyrics; files already in ChordPro are passed through untouched |
| .rtf .odt .doc .html | Converted to text with macOS `textutil`, then as above |

## Download (no Python needed)

Grab the zip for your system from the repository's **Releases** page: *macOS-AppleSilicon* (M1 and newer), *macOS-Intel*,
or *Windows*. Unzip and double-click **ChartWright**. It starts quietly, opens your browser, and quits by itself a couple of
minutes after you close the tab. Nothing is uploaded anywhere: everything, including OCR, runs on your computer.

The apps are not code-signed, so the first launch shows a warning:
- **macOS:** "can't be opened because Apple cannot check it": right-click the app, choose **Open**, then **Open** again
  (or System Settings, Privacy & Security, **Open Anyway**). You only do this once.
- **Windows:** SmartScreen "Windows protected your PC": click **More info**, then **Run anyway**.

Your own dictionary words are kept in `~/Library/Application Support/ChartWright` (macOS) or `%APPDATA%\ChartWright` (Windows).
Old `.doc`, `.rtf` and `.odt` files can only be read on a Mac; save them as `.docx` or `.txt` elsewhere.

### Building the apps yourself

    pip install -r requirements-build.txt
    pyinstaller packaging/chartwright.spec --noconfirm --distpath build/dist --workpath build/work

The GitHub Action in `.github/workflows/build.yml` runs the tests and builds all three versions; pushing a tag such as
`v1.0.0` attaches the zips to a release.

## Sheet music

A PDF exported from notation software has a real text layer plus vector staff lines, so no music recognition is
needed. Staves are found from the drawings; per staff, chord symbols (decoded from music fonts: `B¨`→`Bb`,
`G‹`→`Gm`, `F(“4)`→`Fsus4`) are paired with the lyric syllable beneath them, once per stacked verse. Syllables
joined by hyphens become words (`ado[Bb]ration`), a word broken across systems keeps its trailing hyphen, verse
numbers (`1.` `2.`) become `{comment: Verse N}`, a verse that starts mid-song (verse 4) opens on the chord already
sounding, and repeat pickups (`2. Long lay our` at the end of the last staff) are dropped. Title, credits
(`{lyricist}`, `{arranger}`, `{meta: tune …}`), `{key}` (inferred), `{copyright}` and `{meta: ccli …}` come from
the page header and footer. Drag a box to take only some systems.

- Layout dropdown / `--layout`: **Auto** (detect), **Chord chart**, **Sheet music** (force).
- Scanned or photographed sheet music has no staff drawings or text layer, so it is **not** handled here (it falls
  back to the chord-chart OCR path, which won't understand staves). Notes are not transcribed; only chords + lyrics.
- Lyric typos in the source are kept as printed (`tingguished`, `I'l`). Other engravers' chord fonts: unknown glyphs are
  listed in the review panel.

## OCR (scans and photos)

Built in and self-contained: RapidOCR (ONNX) with its models lives in the project `.venv`; no system
install, no network, nothing leaves the machine.

- **Auto** (default): a page or selection box with no text layer is OCR'd; PDFs with real text skip OCR (fast, exact).
- **Always OCR**: ignore the text layer (useful when a PDF's embedded text is garbled). **Off**: never OCR.
  Same options on the command line: `convert scan.jpg --ocr force`.
- Dragging a box on a scan OCRs just that region, at ~300 dpi.
- **Missed-chord recovery**: after the normal read, any ink the detector ignored just above a lyric line is cut
  out, read on its own, and kept only if it parses as a real chord (`Dm7`, `C/G`, `D/F#`…), so it can be permissive
  without inventing chords. Chord-line repair also glues a detached raised `7` back onto its chord (`Dm 7` → `Dm7`),
  fixes lowercase roots (`c` → `C`), splits merged chords (`GA` → `G A`), and drops isolated footer debris. All
  passes are anchored to the page centre and merged longest-first, so a line read twice never doubles up.
  On the test scans: chords found 100% (clean, hi-res and faded variants), none invented.
- Pipeline for scans: auto-contrast → deskew (up to ±4°) → permissive text detection at two resolutions,
  merged (keeping the more confident reading of each line) → per-character positions so chords still land
  on the right syllable → clean-up (merged chords like `GA` → `G A`, junk tokens dropped on chord lines,
  `l`/`I`/`1` slips inside words).
- **Dictionary logic** (`spell.py`, `lyricfix.py`; SymSpell + bundled English word list + `data/extra_words.txt` hymn
  vocabulary + your own `data/user_words.txt`). Only lyric words are touched, never chords. Automatically:
  splits joined words (`bidfarewell` → `bid farewell`), rejoins broken ones (`hom e` → `home`), repairs
  look-alike letters (`faII` → `fall`, `Iord` → `Lord`, `Itake` → `I take`). Words repeated in the chart count as
  known (choruses), capitalised names and `Jehovah`-style words are left alone, and a chord sitting in the gap
  between two fragments marks an intentional syllable split (`ski [G]es`), so those are never rejoined.
  Everything uncertain becomes a **suggestion** (`sheperd` → `shepherd`), never applied silently.
- **Review panel** (web app): lists each automatic fix (with **Undo**), each unknown word with clickable
  suggestions (**Keep** / **Add to dictionary**), and chord-line junk that was dropped. Clicking a word jumps to its
  line in the text box. The CLI prints the same list to stderr as `[review:…]` lines.
- Dictionary logic runs on OCR input only; text-layer PDFs are exact and are not second-guessed.
- Expect ~6 s per page (two passes). On the degraded test scan (rotated, blurred, noisy) it recovers ~99% of
  the chords and ~90–95% of lines exactly; remaining errors are chords the OCR never saw and the odd misread, so
  proofread the text box. **Very low-resolution, heavily blurred or noisy scans (≈100 dpi, tilted, speckled) can still fail**: the engine merges
  the chord row into the lyric row above it before any chord logic runs. Re-scan at 200–300 dpi if you can. Cleaner scans do better; use ~200–300 dpi, upright, good contrast.

## Chord chart preview and PDF export

Next to the ChordPro text there is a **Chord chart preview** tab (works on converted text, or on anything you paste or edit).

- **Key**: pick any of the 12 keys; every chord is transposed (including slash bass notes). The original key comes from
  `{key: …}`, otherwise it is inferred from the chords. Flats or sharps are chosen to suit the key.
- **Capo**: 0-11. The key you pick is the *sounding* key; the printed shapes drop by the capo number and the header says
  e.g. `Key: G   Capo: 2 (play shapes in F)`. A `{capo}` directive in the text is ignored; the Capo box decides.
- **Columns**: 1 or 2. **Size**: small / medium / large (A4).
- **Export PDF** downloads exactly what the preview shows (the preview *is* the PDF, rendered by `chartwright/chart.py`).

Supported ChordPro: `{title}`, `{subtitle}`/`{artist}`/`{author}`, `{key}`, `{comment}`, `{start_of_verse|chorus|bridge}`
(and short forms), `{copyright}`, `#` comments. Others are ignored. Test: `.venv/bin/python tests/test_chart.py`.

## Pipeline (chartwright/)

- `ocr.py` – scan preparation (deskew/contrast), RapidOCR, multi-pass merge into the same char format as the PDF reader
- `sheetmusic.py` – staff detection, chord-glyph decoding, chord→syllable pairing per verse
- `keys.py` – per-section key inference and chord plausibility (review notes for OCR'd charts)
- `readers.py` – file loading; PDF char extraction, footer removal, column/gutter detection, row grouping (tolerates superscript chord extensions like the 7 in Dm7)
- `chords.py` – chord and section-heading recognition
- `spell.py` / `lyricfix.py` – dictionary: word judging (known / look-alike fix / split / suggest) and positioned-line correction
- `convert.py` – chord line + lyric line pairing, chord insertion, front matter (`{title}`, `{author}`, `{key}`…), blank-line detection → ChordPro
- `server.py`, `static/index.html` – local drag-a-box UI; `cli.py` – command line

## Test

    .venv/bin/python tests/test_sample.py

Converts `tests/samples/title-clear.pdf` and compares it with the hand-written
`title-clear.expected.cho` (ignoring runs of spaces), plus a `.txt` version of the same song. It also OCRs a
deliberately degraded scan (`title-clear.scan.pdf` / `.jpg`), with and without a selection box, and scores it
(chords recovered, lines matching) rather than demanding a perfect match.

## Known limits

- Runs of spaces inside split syllables (`ski  [G]es`) can't be recovered from a PDF; output uses one space.
- Section headings are written as `{comment: Verse 1}` (matching your sample), not `start_of_verse`.
- Proportional-font DOCX/TXT charts may misplace chords by a character; the text box lets you fix it.

## Licence

ChartWright is free software under the **GNU Affero General Public License v3.0** (see `LICENSE`). You can use, share and
modify it; if you distribute a modified version, or run one as a network service, you must make your source available
under the same licence. It builds on PyMuPDF (AGPL), RapidOCR/ONNX Runtime, SymSpell, python-docx, NumPy and Pillow, each
under its own licence.

Copyright (C) 2026 Michael Wright.
