from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .readers import convert_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="chartwright",
                                 description="Convert a chord chart (PDF/DOCX/text) to ChordPro.")
    sub = ap.add_subparsers(dest="cmd")
    cv = sub.add_parser("convert", help="convert a file on the command line")
    cv.add_argument("file")
    cv.add_argument("-o", "--output", help="output .cho/.txt (default: print)")
    cv.add_argument("--page", type=int, default=1, help="1-based page for --rect")
    cv.add_argument("--ocr", choices=["auto", "force", "off"], default="auto",
                    help="text recognition for scans: auto (only if no text layer), force, off")
    cv.add_argument("--layout", choices=["auto", "chart", "sheet"], default="auto",
                    help="auto-detect (default), 'chart' = chord chart, 'sheet' = digital sheet music / lead sheet")
    cv.add_argument("--rect", help="selection box x0,y0,x1,y1 in PDF points")
    sv = sub.add_parser("serve", help="start the drag-a-box web app (default)")
    sv.add_argument("--port", type=int, default=8791)
    sv.add_argument("--no-browser", action="store_true")
    sv.add_argument("--auto-quit", action="store_true", help="exit when the browser tab has been closed for a while")
    args = ap.parse_args(argv)

    if args.cmd == "convert":
        sel = None
        if args.rect:
            sel = [{"page": args.page - 1, "rect": [float(v) for v in args.rect.split(",")]}]
        notes: list = []
        text = convert_file(args.file, sel, args.ocr, notes, args.layout)
        for n in notes:
            what = (f"{n['frm']} -> {n['to']}" if n['to'] else f"{n['frm']}  ({n['why']}; try: {', '.join(n['suggestions']) or '-'})" if n.get('why') else f"{n['frm']}  (suggest: {', '.join(n['suggestions']) or '-'})")
            print(f"[review:{n['kind']}] line {(n['line'] or 0) + 1}: {what}", file=sys.stderr)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0

    from .server import serve
    serve(getattr(args, "port", 8791), not getattr(args, "no_browser", False), getattr(args, "auto_quit", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
