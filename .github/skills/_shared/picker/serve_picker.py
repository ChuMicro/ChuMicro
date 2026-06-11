#!/usr/bin/env python3
"""Serve a rendered decision page over localhost and loop its Submit button back to the session.

A page from render_picker.py carries a selection bar whose blob the human can always
copy and paste back into the session. Served over http, the same bar also shows a
**Submit to session** button: it POSTs the blob here, and this server writes it to
<dir>/selection.txt and prints one `SELECTION RECEIVED -> <path>` line to stdout.
The orchestrating session runs this server in the background and watches its stdout
(the Monitor tool reads it), so a submit arrives as an event carrying the same blob a
paste would. The server is transport only: it never parses or applies a selection.

Binds 127.0.0.1 on a free port. Tries to auto-open the page unless PICKER_NO_OPEN is
set — a convenience for a human running this directly. An orchestrating session sets
PICKER_NO_OPEN=1 and runs `open <url>` on the printed SERVING line itself: from a
sandboxed background process the auto-open either fails silently or lands late as a
duplicate tab, so the session must be the only opener.

A refresh always shows the current spec: on each GET of the page, when <dir>/spec.json
or render_picker.py is newer than the rendered page, the server re-renders before
serving and prints one `RERENDERED <path>` line. The server stays selection-agnostic —
it never parses or applies what comes back.

Usage: serve_picker.py <dir> [<page>]      (default page: picker.html)
Stdout: `SERVING <url>` once on start, `RERENDERED <path>` per stale-refresh,
one `SELECTION RECEIVED -> <path>` line per submit.
"""
import http.server
import os
import subprocess
import sys
import webbrowser

RENDERER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_picker.py")


def main():
    directory = os.path.abspath(sys.argv[1])
    page = sys.argv[2] if len(sys.argv) > 2 else "picker.html"
    if not os.path.exists(os.path.join(directory, page)):
        print(f"refusing to serve: {directory}/{page} does not exist", flush=True)
        raise SystemExit(2)
    sink = os.path.join(directory, "selection.txt")
    spec_path = os.path.join(directory, "spec.json")
    page_path = os.path.join(directory, page)

    def rerender_if_stale():
        if not os.path.exists(spec_path):
            return
        try:
            page_mtime = os.path.getmtime(page_path)
            if max(os.path.getmtime(spec_path), os.path.getmtime(RENDERER)) <= page_mtime:
                return
            result = subprocess.run(
                [sys.executable, RENDERER, spec_path, directory],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                print(f"RERENDERED {page_path}", flush=True)
            else:
                tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
                print(f"RENDER FAILED (serving stale page): {tail}", flush=True)
        except OSError:
            pass

    class PickerHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, *args):  # stdout is the session's event stream; keep request noise off it
            pass

        def do_GET(self):
            if self.path.split("?")[0].lstrip("/") in ("", page):
                rerender_if_stale()
            super().do_GET()

        def do_POST(self):
            if self.path.rstrip("/") != "/selection":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            blob = self.rfile.read(length).decode("utf-8", "replace")
            with open(sink, "w") as handle:
                handle.write(blob)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            print(f"SELECTION RECEIVED -> {sink}", flush=True)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PickerHandler)
    url = f"http://127.0.0.1:{server.server_port}/{page}"
    print(f"SERVING {url}", flush=True)
    if not os.environ.get("PICKER_NO_OPEN"):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless/SSH: the printed URL is the fallback
            pass
    server.serve_forever()


if __name__ == "__main__":
    main()
