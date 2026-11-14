"""Tiny local web app (stdlib only). Binds to 127.0.0.1; files never leave the machine."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ocr import available as ocr_available
from .paths import RUN, WORK
from .readers import IMAGE_EXTS, ScannedPdfError, convert_file, pdf_page_count

STATIC = Path(__file__).parent / "static"
# uploads live inside the project folder, not in a system temp dir
DOCS: dict[str, Path] = {}
MAX_UPLOAD = 100 * 1024 * 1024
LAST_PING: list = [None]                                  # time of the page's last heartbeat


class Handler(BaseHTTPRequestHandler):
    server_version = "ChartWright/1.0"

    def log_message(self, *a):  # quiet
        pass

    # -- helpers
    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_UPLOAD:
            raise ValueError("file too large")
        return self.rfile.read(n)

    # -- routes
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/static/") and u.path.endswith(".js"):
                f = (STATIC / Path(u.path).name)
                if f.is_file():
                    return self._send(200, f.read_bytes(), "text/javascript; charset=utf-8")
            if u.path == "/api/ping":
                LAST_PING[0] = time.time()
                return self._json({"ok": True})
            if u.path == "/api/page":
                import fitz
                with fitz.open(DOCS[q["id"]]) as d:
                    page = d[int(q["n"])]
                    zoom = float(q.get("zoom", 2))
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                    return self._send(200, pix.tobytes("png"), "image/png")
            return self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/open":
                name = Path(q.get("name", "upload")).name
                data = self._body()
                doc_id = uuid.uuid4().hex[:12]
                WORK.mkdir(parents=True, exist_ok=True)
                path = WORK / f"{doc_id}-{name}"
                path.write_bytes(data)
                DOCS[doc_id] = path
                info = {"id": doc_id, "name": name, "kind": "text", "ocr": ocr_available()}
                if path.suffix.lower() == ".pdf" or path.suffix.lower() in IMAGE_EXTS:
                    info.update(kind="pdf", pages=pdf_page_count(path))
                else:
                    info["chordpro"] = convert_file(path)
                return self._json(info)
            if u.path == "/api/convert":
                req = json.loads(self._body() or b"{}")
                sel = req.get("selections") or None
                mode = req.get("ocr", "auto")
                if mode not in ("auto", "force", "off"):
                    mode = "auto"
                notes: list = []
                layout = req.get("layout", "auto")
                if layout not in ("auto", "chart", "sheet"):
                    layout = "auto"
                cols = str(req.get("columns", "auto"))
                text = convert_file(DOCS[req["id"]], sel, mode, notes, layout, cols if cols in ("1", "2") else "auto")
                for i, n in enumerate(notes):
                    n["id"] = i
                return self._json({"chordpro": text, "review": notes})
            if u.path in ("/api/preview", "/api/pdf"):
                from .chart import render_pdf, render_preview
                req = json.loads(self._body() or b"{}")
                kw = dict(key=str(req.get("key") or ""), capo=int(req.get("capo") or 0),
                          columns=2 if int(req.get("columns") or 1) == 2 else 1,
                          size=str(req.get("size") or "medium"), title=str(req.get("title") or ""))
                text = str(req.get("text") or "")
                if u.path == "/api/preview":
                    return self._json(render_preview(text, **kw))
                data, info = render_pdf(text, **kw)
                return self._send(200, data, "application/pdf")
            if u.path == "/api/dict/add":
                req = json.loads(self._body() or b"{}")
                from .spell import available as spell_ok, get_speller
                if spell_ok():
                    get_speller().add_user_word(req.get("word", ""))
                return self._json({"ok": True})
            return self._send(404, b"not found", "text/plain")
        except ScannedPdfError as e:
            return self._json({"error": str(e)}, 422)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def _bind(port: int) -> ThreadingHTTPServer:
    """Use the requested port, or the next free one: another local app may already own it."""
    for p in range(port, port + 30):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
    raise OSError(f"No free port found in {port}-{port + 29}")


def running_url() -> str | None:
    """URL of a ChartWright server that is already running (second launch of the app), else None."""
    import urllib.request
    try:
        p = (RUN / "port").read_text().strip()
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/", timeout=2) as r:
            if b"<title>ChartWright" in r.read(2048):
                return f"http://127.0.0.1:{p}/"
    except Exception:  # noqa: BLE001
        pass
    return None


def serve(port: int = 8791, open_browser: bool = True, auto_quit: bool = False):
    if open_browser and auto_quit:             # app launch: reuse a running copy instead of starting a second
        url = running_url()
        if url:
            webbrowser.open(url)
            return
    srv = _bind(port)
    port = srv.server_address[1]
    if port != 8791 and port != 0:
        print(f"(port busy, using {port} instead)", flush=True)
    url = f"http://127.0.0.1:{port}/"
    print(f"ChartWright running at {url}  (Ctrl+C to stop)", flush=True)
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "port").write_text(str(port))
    from .spell import available as spell_ok, get_speller
    if spell_ok():                       # warm the dictionary so the first scan isn't slow
        threading.Thread(target=get_speller, daemon=True).start()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if auto_quit:
        # the page pings every 10 s; once it has gone quiet (tab closed) the server shuts itself down
        idle = float(os.environ.get("CPM_IDLE_SECS", 120))
        started = time.time()

        def watchdog():
            while True:
                time.sleep(2)
                last = LAST_PING[0]
                if (last is None and time.time() - started > max(idle, 180)) or \
                        (last is not None and time.time() - last > idle):
                    print("No browser tab open any more - shutting down.", flush=True)
                    srv.shutdown()
                    return
        threading.Thread(target=watchdog, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        (RUN / "port").unlink(missing_ok=True)
        for p in DOCS.values():
            p.unlink(missing_ok=True)
