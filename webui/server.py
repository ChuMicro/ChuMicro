"""Localhost submit server: the shared transport beneath every webui surface.

Serves a self-contained HTML page over http on 127.0.0.1:<free port>, writes each POST's
body verbatim to a sink file, prints a '<received> -> <sink>' line, and shuts down after
the FIRST POST. A session is one submission, so the process *completing* is itself the
submit signal (read the sink then). Auto-opens the page unless an env var is set (an
orchestrating session sets it and opens the URL itself). Transport ONLY: it never parses or
applies the submission.

Pure stdlib. The off-request-thread shutdown is load-bearing: shutdown() must not run on
the request thread, so it is handed to a daemon thread; serve_forever() then returns.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import webbrowser


def serve_oneshot(directory, page, *, post_path, sink_name, env_no_open,
                  label_received, label_closed, on_get=None):
    """Serve `directory/page`; write each POST to `post_path` into `directory/sink_name`.

    One-shot: after the FIRST POST it writes the request body, prints
    '<label_received> -> <sink>', and shuts down. `on_get` (or None) runs before each GET
    of the page; the picker uses it to re-render a stale page. Auto-opens the URL unless
    `env_no_open` is set. Prints 'SERVING <url>' on start and '<label_closed> <sink>' on
    close. Returns the sink path.
    """
    directory = os.path.abspath(directory)
    if not os.path.exists(os.path.join(directory, page)):
        print(f"refusing to serve: {directory}/{page} does not exist", flush=True)
        raise SystemExit(2)
    sink = os.path.join(directory, sink_name)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, *args):  # stdout is the session's event stream; keep request noise off it
            pass

        def do_GET(self):
            if on_get is not None and self.path.split("?")[0].lstrip("/") in ("", page):
                on_get()
            super().do_GET()

        def do_POST(self):
            if self.path.rstrip("/") != post_path:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            blob = self.rfile.read(length).decode("utf-8", "replace")
            with open(sink, "w") as handle:           # latest submission wins
                handle.write(blob)
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()      # push the reply to the client BEFORE we tear down, or the
                                    # browser's fetch can hang on a half-sent response (reads as a
                                    # silent dead Submit) -- the shutdown below races this write.
            print(f"{label_received} -> {sink}", flush=True)
            # one-shot: a submission ends the session. shutdown() must run off the
            # request thread, so hand it to a daemon thread; serve_forever() then returns.
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/{page}"
    print(f"SERVING {url}", flush=True)
    if not os.environ.get(env_no_open):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless: the printed URL is the fallback
            pass
    try:
        server.serve_forever()  # returns once a submission triggers shutdown
    except KeyboardInterrupt:
        pass
    server.server_close()
    print(f"{label_closed} {sink}", flush=True)
    return sink
