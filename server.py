#!/usr/bin/env python3
"""Sheet Cheat: a small local web server.

Serves the viewer in ./web and reads the notes on each page with Audiveris.
The browser renders each PDF page to a PNG and posts it here; we run
Audiveris on it, turn its MusicXML into note positions (see omr.py) and
cache the result, so a page is only ever analysed once.

Run:  python3 server.py        then open http://localhost:8765
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import omr

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
CACHE = ROOT / "cache"
MAX_UPLOAD = 60 * 1024 * 1024
AUDIVERIS_TIMEOUT = 15 * 60
CACHE_VERSION = 2  # bump when omr.py changes; pages are re-placed from the saved MusicXML

AUDIVERIS_CANDIDATES = [
    "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
    str(Path.home() / "Applications/Audiveris.app/Contents/MacOS/Audiveris"),
    "/opt/audiveris/bin/Audiveris",
    "C:/Program Files/Audiveris/Audiveris.exe",
]

# Audiveris is memory hungry, so read one page at a time.
audiveris_lock = threading.Lock()


def find_audiveris() -> str | None:
    env = os.environ.get("AUDIVERIS")
    if env:
        return env if Path(env).exists() else None
    for name in ("audiveris", "Audiveris"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in AUDIVERIS_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    # any version of the macOS app, e.g. "Audiveris 5.6.app"
    for apps in (Path("/Applications"), Path.home() / "Applications"):
        for exe in sorted(apps.glob("Audiveris*.app/Contents/MacOS/*")):
            if exe.is_file() and os.access(exe, os.X_OK):
                return str(exe)
    return None


def cache_path(doc: str, page: int) -> Path:
    return CACHE / doc / f"page-{page}.v{CACHE_VERSION}.json"


def cached_result(doc: str, page: int) -> dict | None:
    """The saved result for a page, rebuilt from Audiveris' saved MusicXML if
    it was made by an older version of omr.py (no need to run Audiveris again)."""
    path = cache_path(doc, page)
    if path.exists():
        return json.loads(path.read_text())
    scores = [p for p in (CACHE / doc / f"page-{page}{ext}" for ext in (".mxl", ".musicxml", ".xml"))
              if p.exists()]
    if not scores:
        return None
    result = omr.notes_from_files(scores)
    result["page"] = page
    path.write_text(json.dumps(result))
    return result


def analyse_page(doc: str, page: int, png: bytes) -> dict:
    audiveris = find_audiveris()
    if not audiveris:
        raise RuntimeError("Audiveris is not installed (see README, step 2)")

    with audiveris_lock:
        cached = cached_result(doc, page)
        if cached is not None:  # another request finished it while we waited
            return cached

        work = Path(tempfile.mkdtemp(prefix="sheetcheat-"))
        try:
            image = work / f"page-{page}.png"
            image.write_bytes(png)
            out = work / "out"
            out.mkdir()
            cmd = [audiveris, "-batch", "-export", "-output", str(out), "--", str(image)]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=AUDIVERIS_TIMEOUT)
            log = proc.stdout.decode("utf-8", "replace")
            (CACHE / doc).mkdir(parents=True, exist_ok=True)
            (CACHE / doc / f"page-{page}.audiveris.log").write_text(log)

            scores = sorted(p for p in out.rglob("*")
                            if p.suffix in (".mxl", ".musicxml")
                            or (p.suffix == ".xml" and not p.name.startswith(".")))
            if not scores:
                result = {"notes": [], "space": None,
                          "message": "Audiveris found no music on this page."}
            else:
                result = omr.notes_from_files(scores)
                # keep a copy of the MusicXML, handy for debugging or opening in MuseScore
                for s in scores:
                    shutil.copy(s, CACHE / doc / f"page-{page}{s.suffix}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

        result["page"] = page
        cache_path(doc, page).write_text(json.dumps(result))
        return result


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".css": "text/css",
        ".html": "text/html; charset=utf-8",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        # always serve the newest app files after an update
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("  " + (fmt % args) + "\n")

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def page_route(self):
        m = re.fullmatch(r"/api/page/([0-9a-f]{16,64})/(\d{1,4})", self.path.split("?")[0])
        return (m.group(1), int(m.group(2))) if m else None

    def do_GET(self):
        if self.path == "/api/status":
            return self.send_json({"audiveris": find_audiveris()})
        route = self.page_route()
        if route:
            try:
                result = cached_result(*route)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            if result is not None:
                return self.send_json(result)
            return self.send_json({"error": "not analysed yet"}, HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_POST(self):
        route = self.page_route()
        if not route:
            return self.send_json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            return self.send_json({"error": "bad upload size"}, HTTPStatus.BAD_REQUEST)
        png = self.rfile.read(length)
        try:
            result = analyse_page(route[0], route[1], png)
        except subprocess.TimeoutExpired:
            return self.send_json({"error": "Audiveris took too long on this page"},
                                  HTTPStatus.INTERNAL_SERVER_ERROR)
        except Exception as exc:  # report anything else to the page
            return self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.send_json(result)


def main():
    parser = argparse.ArgumentParser(description="Sheet Cheat local server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()

    CACHE.mkdir(exist_ok=True)
    audiveris = find_audiveris()
    url = f"http://localhost:{args.port}"
    print(f"Sheet Cheat is running at {url}   (press Ctrl+C to stop)")
    if audiveris:
        print(f"Using Audiveris at {audiveris}")
    else:
        print("WARNING: Audiveris not found. PDFs will display but notes won't be named.")
        print("         Install it (README step 2) or set AUDIVERIS=/path/to/Audiveris")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
