"""Localhost submit server — the shared transport beneath every webui surface.

Serves a self-contained HTML page over http on 127.0.0.1:<free port>, writes each POST's
body verbatim to a sink file, prints a '<received> -> <sink>' line, and (by default) shuts
down after the FIRST POST — a session is one submission, so the process *completing* is
itself the submit signal (read the sink then). `persistent` mode keeps the server UP across
many submits (an iterative tuning surface). Auto-opens the page unless an env var is set (an
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
from datetime import datetime


def serve_oneshot(directory, page, *, post_path, sink_name, env_no_open,
                  label_received, label_closed, on_get=None, missing_hint="",
                  persistent=False, response=None, label_open=None):
    """Serve `directory/page`; write each POST to `post_path` into `directory/sink_name`.

    Default (one-shot): stop after the FIRST POST — write the request body, print
    '<label_received> -> <sink>', and shut down. With `persistent=True` the server STAYS
    UP across many POSTs (the knob console): each writes the latest body (latest wins),
    prints '<label_received> -> <sink>  (#n at ts)', and the page stays usable; stop it
    with Ctrl-C. `response` is an optional callable (n, ts) -> dict for the JSON reply
    body (default `{"ok": true}`); persistent surfaces pass one to feed the page a submit
    counter + timestamp. `on_get` (or None) runs before each GET of the page — the picker
    uses it to re-render a stale page; the viewer/console pass None. `label_open`
    overrides the start line's suffix after the URL (e.g. the console's persistent note).
    Auto-opens the URL unless `env_no_open` is set. `missing_hint` is appended to the
    not-found message. Prints 'SERVING <url>' on start and '<label_closed> <sink>' on
    close. Returns the sink path.
    """
    directory = os.path.abspath(directory)
    if not os.path.exists(os.path.join(directory, page)):
        print(f"refusing to serve: {directory}/{page} does not exist{missing_hint}", flush=True)
        raise SystemExit(2)
    sink = os.path.join(directory, sink_name)
    state = {"n": 0}

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
            state["n"] += 1
            ts = datetime.now().strftime("%H:%M:%S")
            payload = response(state["n"], ts) if response is not None else {"ok": True}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()      # push the reply to the client BEFORE we tear down, or the
                                    # browser's fetch can hang on a half-sent response (reads as a
                                    # silent dead Submit) -- the shutdown below races this write.
            tail = f"  (#{state['n']} at {ts})" if persistent else ""
            print(f"{label_received} -> {sink}{tail}", flush=True)
            if not persistent:
                # one-shot: a submission ends the session. shutdown() must run off the
                # request thread, so hand it to a daemon thread; serve_forever() then returns.
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/{page}"
    print(f"SERVING {url}{label_open or ''}", flush=True)
    if not os.environ.get(env_no_open):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless: the printed URL is the fallback
            pass
    try:
        server.serve_forever()  # one-shot: returns once a submission triggers shutdown; persistent: until Ctrl-C
    except KeyboardInterrupt:
        pass
    server.server_close()
    print(f"{label_closed} {sink}", flush=True)
    return sink
