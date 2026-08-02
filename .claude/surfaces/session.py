"""The session server: keep the server up and PUSH to the browser (the re-serve channel).

`serve_oneshot` (server.py) solves SUBMIT (browser→server) but not RE-SERVE (server→browser):
today each turn the agent re-`open()`s a fresh page, so the human manually refreshes or lands
in a new tab. This server fixes that. It owns ONE stable "canvas" URL (opened once) plus a
server→browser push channel, so each turn the agent regenerates the page and pushes a signal
(`reload` / `navigate` / `toast` / `progress` / `done`) into the SAME tab, which stays current
without a hand refresh and without a second tab piling up.

Turn-based is no obstacle: the server outlives the turn (run it in the background; the agent
hits `/push` each turn, cross-process via `push_to(port, event)`). The channel is **SSE**
(Server-Sent Events): re-serve is push-only, SSE is exactly that, it is trivial over the
stdlib server (hold the response open, write `data:` frames), auto-reconnects, and adds no
dependency. Websockets are reserved for the day a surface needs the browser to stream signal
*up* mid-page; SSE-down + POST-up (`/selection`, `/push`) covers everything turn-based until then.

Routes: GET /canvas (the current page) · GET /events (the SSE stream) · POST /push (the agent
control endpoint → fans an event to every open tab) · POST /selection (write the sink, latest
wins, + a confirm toast) · POST /shutdown (end the session). Pure stdlib.
"""
from __future__ import annotations

import http.server
import json
import os
import queue
import sys
import threading
import urllib.request


class _QuietServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer that swallows the normal client-disconnect errors. An SSE tab that
    navigates away or a curl that times out resets the connection, which is expected, not a fault."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class SessionServer:
    """A persistent canvas server with a server→browser SSE push channel.

    Usage (in-process): `s = SessionServer(dir).start(); s.push({"type": "reload"})`.
    Usage (cross-process, the agent's case): run via `main()` in the background, then
    `push_to(port, {...})` each turn after overwriting the canvas page on disk.
    """

    def __init__(self, directory, *, page="canvas.html", sink_name="submit.json"):
        self.directory = os.path.abspath(directory)
        self.page = page
        self.sink = os.path.join(self.directory, sink_name)
        self.submissions = []
        self.port = None
        self._clients = []          # list[queue.Queue], one per connected EventSource
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    # ── server→browser push ────────────────────────────────────────────────────────────────
    def push(self, event):
        """Fan `event` (a dict) to every connected tab. Returns the client count it reached."""
        frame = ("data: " + json.dumps(event) + "\n\n").encode()
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            q.put(frame)
        return len(clients)

    # ── handler ────────────────────────────────────────────────────────────────────────────
    def _handler(self):
        server = self

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=server.directory, **k)

            def log_message(self, *a):  # keep request noise off the session's stdout
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/events":
                    return server._serve_events(self)
                if path in ("/", "/canvas"):
                    self.path = "/" + server.page
                return super().do_GET()

            def do_POST(self):
                path = self.path.split("?")[0]
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
                if path == "/push":
                    try:
                        event = json.loads(raw) if raw else {}
                    except ValueError:
                        event = {}
                    return self._json({"ok": True, "clients": server.push(event)})
                if path == "/selection":
                    with open(server.sink, "w") as handle:
                        handle.write(raw)
                    server.submissions.append(raw)
                    server.push({"type": "toast", "text": "submitted", "kind": "good"})
                    print(f"submit -> {server.sink}", flush=True)
                    return self._json({"ok": True})
                if path == "/shutdown":
                    self._json({"ok": True})
                    threading.Thread(target=server.stop, daemon=True).start()
                    return
                self.send_error(404)

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

        return H

    def _serve_events(self, handler):
        """Hold the response open as an SSE stream; drain this client's queue until it drops."""
        q = queue.Queue()
        with self._lock:
            self._clients.append(q)
        try:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "keep-alive")
            handler.end_headers()
            handler.wfile.write(b": connected\n\n")
            handler.wfile.flush()
            while True:
                try:
                    frame = q.get(timeout=15)
                except queue.Empty:
                    frame = b": keepalive\n\n"     # keep the connection (and proxies) warm
                handler.wfile.write(frame)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                    # the tab closed; drop the client
        finally:
            with self._lock:
                if q in self._clients:
                    self._clients.remove(q)

    # ── lifecycle ──────────────────────────────────────────────────────────────────────────
    def start(self, port=0):
        self._httpd = _QuietServer(("127.0.0.1", port), self._handler())
        self.port = self._httpd.server_port
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def wait(self):
        """Block the caller until the server stops (POST /shutdown or stop()), so a foreground
        `serve` exits cleanly and runs its cleanup, instead of sleeping past the shutdown."""
        if self._thread is not None:
            self._thread.join()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/canvas"

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def push_to(port, event, *, path="/push", timeout=5):
    """Cross-process push: POST `event` to a running SessionServer's control endpoint.
    This is how the AGENT pushes between turns (it is a separate process from the server)."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


PORT_FILE = ".session-port"


def _port(directory):
    """The live session's port (written by `serve`); error clearly if none is running."""
    path = os.path.join(os.path.abspath(directory), PORT_FILE)
    if not os.path.exists(path):
        raise SystemExit(
            f"no live session in {directory!r}; start one: python3 -m surfaces.session serve {directory}")
    with open(path) as handle:
        return int(handle.read().strip())


def _cmd_serve(args):
    """Run the server in the foreground; the agent BACKGROUNDS this so it outlives a turn. Seeds a
    live canvas page (so the first GET already carries the SSE client), writes the port file, and
    serves until SIGINT or POST /shutdown, cleaning up the port file on the way out."""
    import webbrowser

    from surfaces import kit
    os.makedirs(os.path.abspath(args.directory), exist_ok=True)
    server = SessionServer(args.directory, page="canvas.html").start(args.port)
    canvas = os.path.join(server.directory, "canvas.html")
    if not os.path.exists(canvas):
        with open(canvas, "w") as handle:
            handle.write(kit.page("Surfaces", "<div class='wrap'><h1>ready</h1>"
                                  "<p class='faint'>the agent will present here.</p></div>", live=True))
    with open(os.path.join(server.directory, PORT_FILE), "w") as handle:
        handle.write(str(server.port))
    print(f"SERVING {server.url}", flush=True)
    if args.open:
        try:
            webbrowser.open(server.url)
        except Exception:  # noqa: BLE001 - headless, the printed URL is the fallback
            pass
    try:
        server.wait()                        # block until POST /shutdown or Ctrl-C, then clean up
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(os.path.join(server.directory, PORT_FILE))
        except OSError:
            pass
        server.stop()
    print("session closed", flush=True)


def _cmd_show(args):
    """Set the live canvas to a page and push 'reload' into the open tab (the re-serve step).
    `--wrap` wraps a body fragment in kit.page(live=True); a full page must already be `live`."""
    from surfaces import kit

    directory = os.path.abspath(args.directory)
    src = open(args.file).read() if args.file else sys.stdin.read()
    if args.wrap:
        src = kit.page(args.title or "Surfaces", src, live=True)
    elif "EventSource" not in src:
        print("warning: page has no SSE client (build it with kit.page(live=True) or pass --wrap): "
              "the reload push won't reach it", flush=True)
    with open(os.path.join(directory, "canvas.html"), "w") as handle:
        handle.write(src)
    reached = push_to(_port(directory), {"type": "reload"}).get("clients", 0)
    print(f"shown -> canvas.html (reload pushed to {reached} tab(s))", flush=True)


def _cmd_toast(args):
    push_to(_port(args.directory), {"type": "toast", "text": args.text, "kind": args.kind})


def _cmd_progress(args):
    push_to(_port(args.directory), {"type": "progress", "value": float(args.value), "text": args.text or ""})


def _cmd_event(args):
    push_to(_port(args.directory), json.loads(args.json))


def _cmd_stop(args):
    try:
        push_to(_port(args.directory), {}, path="/shutdown")
    except Exception:  # noqa: BLE001 - already down is fine
        pass
    print("session stopped", flush=True)


def main(argv=None):
    """The live-canvas CLI (the re-serve channel): keep ONE tab live across turns and push into it:

      serve <dir> [--open]                  start the bg server (writes .session-port; agent backgrounds this)
      show  <dir> <file> [--wrap --title T] set the canvas to <file> + push reload (--wrap = wrap a body fragment)
      toast <dir> <text> [--kind good|bad]  push a status toast
      progress <dir> <0..1> [text]          push a progress tick
      event <dir> <json>                    push an arbitrary event
      stop  <dir>                           end the session
    """
    import argparse

    ap = argparse.ArgumentParser(description="Surfaces live canvas (persistent tab + SSE re-serve)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the bg session server (keep one tab live)")
    sp.add_argument("directory"); sp.add_argument("--port", type=int, default=0)
    sp.add_argument("--open", action="store_true"); sp.set_defaults(func=_cmd_serve)

    sp = sub.add_parser("show", help="set the canvas to a page + push reload")
    sp.add_argument("directory"); sp.add_argument("file", nargs="?", help="HTML file (or stdin if omitted)")
    sp.add_argument("--wrap", action="store_true", help="wrap the file (a body fragment) in kit.page(live=True)")
    sp.add_argument("--title", default=""); sp.set_defaults(func=_cmd_show)

    sp = sub.add_parser("toast", help="push a toast"); sp.add_argument("directory")
    sp.add_argument("text"); sp.add_argument("--kind", default=""); sp.set_defaults(func=_cmd_toast)

    sp = sub.add_parser("progress", help="push a progress tick"); sp.add_argument("directory")
    sp.add_argument("value"); sp.add_argument("text", nargs="?", default=""); sp.set_defaults(func=_cmd_progress)

    sp = sub.add_parser("event", help="push an arbitrary JSON event"); sp.add_argument("directory")
    sp.add_argument("json"); sp.set_defaults(func=_cmd_event)

    sp = sub.add_parser("stop", help="stop the session"); sp.add_argument("directory")
    sp.set_defaults(func=_cmd_stop)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
