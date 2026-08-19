#!/usr/bin/env python
"""Local HTTP server for the material-heat dashboard.

Serves the qcqianchuan project root so the web pages can fetch their data
sources (data/accounts/<acct>/*.json, *.jsonl) directly — no per-run HTML
regeneration needed. Pages poll the JSON/JSONL endpoints and re-render.

Usage:
  python scripts/serve_dashboard.py            # foreground
  python scripts/serve_dashboard.py --port 8890
"""
import argparse
import functools
import json
import pathlib
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]

# .jsonl has no standard MIME; make sure it comes back as text/plain so
# fetch().text() works everywhere.
MIME_OVERRIDES = {
    ".jsonl": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # allow the pages to be opened from anywhere (same-origin anyway)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):
        ext = pathlib.Path(path).suffix.lower()
        if ext in MIME_OVERRIDES:
            return MIME_OVERRIDES[ext]
        return super().guess_type(path)

    def log_message(self, fmt, *args):
        sys.stderr.write("[dashboard] %s\n" % (fmt % args))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8890)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
    print(json.dumps({
        "ok": True,
        "url": f"http://127.0.0.1:{args.port}/web/material_heat_dashboard.html",
        "root": str(ROOT),
    }))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
