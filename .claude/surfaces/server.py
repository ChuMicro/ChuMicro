"""Localhost submit server: the shared transport beneath every one-shot surface.

Serves a self-contained HTML page over http on 127.0.0.1:<free port>, writes each POST's
body verbatim to a sink file, prints a '<received> -> <sink>' line, and by default shuts
down after the FIRST POST. A session is one submission, so the process *completing* is
itself the submit signal (read the sink then). A surface that tunes iteratively opts into
`persistent` mode: it STAYS UP and accepts many submits. Auto-opens the page unless an env
var is set (an orchestrating session sets it and opens the URL itself). Transport ONLY: it
never parses or applies the submission.

Pure stdlib. The off-request-thread shutdown is load-bearing: shutdown() must not run on
the request thread, so it is handed to a daemon thread; serve_forever() then returns.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import urllib.parse
import webbrowser
from datetime import datetime


def serve_oneshot(directory, page, *, post_path, sink_name, env_no_open,
                  label_received, label_closed, on_get=None, missing_hint="",
                  persistent=False, response=None, label_open=None, port=0,
                  on_serving=None, exclusive_page=False):
    """Serve `directory/page`; write each POST to `post_path` into `directory/sink_name`.

    Default (one-shot): stop after the FIRST POST. Write the request body, print
    '<label_received> -> <sink>', and shut down. With `persistent=True` the server STAYS
    UP across many POSTs: each writes the latest body (latest wins), prints
    '<label_received> -> <sink>  (#n at ts)', and the page stays usable; stop it with
    Ctrl-C. `response` is an optional callable (n, ts) -> dict for the JSON reply body
    (default `{"ok": true}`); persistent surfaces pass one to feed the page a submit
    counter and timestamp. `on_get` (or None) runs before each GET of the page: the picker
    uses it to re-render a stale page, a static surface passes None. `label_open`
    overrides the start line's suffix after the URL. Auto-opens the URL unless
    `env_no_open` is set. `missing_hint` is appended to the not-found message. Prints
    'SERVING <url>' on start and '<label_closed> <sink>' on close. Returns the sink path.

    `on_serving(url, port)` (optional) is called ONCE, after the socket is bound and
    listening but before serve_forever(): the detached launcher's hook for publishing its
    grandchild's real URL back to the parent. A bound socket already queues the parent's
    verifying GET, so nothing has to sleep-and-poll for readiness.

    `exclusive_page=True` makes this server serve exactly ONE page: any *other* `.html`
    request answers 410 Gone naming the live URL, and a bare `/` redirects to the page.
    Without it the server hands back every stale page still lying in the directory with a
    200, the failure that let a wrong URL from another round (or another session) look
    correct to the human. Non-page assets (audio and images) are unaffected.
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
            rel = urllib.parse.unquote(self.path.split("?")[0]).lstrip("/")
            if exclusive_page:
                # ONE round, ONE page: a stale URL from another round must never read as this
                # one. The directory holds every page ever built here, so without this a
                # different session's (or a superseded) page answers 200 and looks correct.
                if rel in ("", "index.html"):
                    self.send_response(302)
                    self.send_header("Location", "/" + page)
                    self.end_headers()
                    return
                if rel.lower().endswith((".html", ".htm")) and rel != page:
                    body = (f"410 Gone: this server is serving {page!r} only.\n"
                            f"The page you asked for belongs to a DIFFERENT round.\n"
                            f"Live page: http://127.0.0.1:{self.server.server_port}/{page}\n").encode()
                    self.send_response(410)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            if on_get is not None and rel in ("", page):
                on_get()
            # HTTP Range support: SimpleHTTPRequestHandler has NONE, and without byte ranges
            # Chrome cannot SEEK inside a served <audio>. A seek, or an A/B switch to an
            # unbuffered position, snapped playback back to 0 (the "switching restarts the
            # track, cannot skip to sections" report on minutes-long media). Single-range
            # only, which is all a media element ever sends; anything else falls through to
            # the stock full-body path.
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                path = self.translate_path(self.path)
                try:
                    size = os.path.getsize(path)
                    lo_s, _, hi_s = rng[len("bytes="):].partition("-")
                    lo = int(lo_s) if lo_s else max(0, size - int(hi_s))   # bytes=-N = final N
                    hi = min(int(hi_s), size - 1) if (lo_s and hi_s) else size - 1
                except (OSError, ValueError):
                    super().do_GET()
                    return
                if lo > hi or lo >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self._ranged = True                      # end_headers: don't re-add Accept-Ranges
                self.send_header("Content-Type", self.guess_type(path))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {lo}-{hi}/{size}")
                self.send_header("Content-Length", str(hi - lo + 1))
                self.end_headers()
                with open(path, "rb") as fh:
                    fh.seek(lo)
                    remaining = hi - lo + 1
                    while remaining > 0:
                        chunk = fh.read(min(65536, remaining))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            return          # the media element aborts ranges constantly; normal
                        remaining -= len(chunk)
                return
            super().do_GET()

        def end_headers(self):
            # advertise seekability on plain GET responses so the media element ASKS for ranges
            if self.command == "GET" and not getattr(self, "_ranged", False):
                try:
                    self.send_header("Accept-Ranges", "bytes")
                except Exception:  # noqa: BLE001 - a torn-down socket mid-header; nothing to add
                    pass
            super().end_headers()

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

    # `port`: 0 = ephemeral, the default. A caller may pin a port so a supervisor can RESTART
    # a killed server at a STABLE url. Two concurrent sessions sharing one output root were
    # reaping each other's one-shot listeners mid-round; a pinned port means the reload works
    # instead of stranding the human on a dead ephemeral port.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/{page}"
    print(f"SERVING {url}{label_open or ''}", flush=True)
    if on_serving is not None:
        on_serving(url, server.server_port)   # the socket is bound + listening; a caller may connect now
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
