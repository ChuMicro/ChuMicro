"""The surface hub: one server, one tab, many surfaces.

Before the hub, every question owned a server and every server opened a tab. Ask five
questions across a session and the human holds five tabs, four of them dead. Run two
agents and they fight over ports, mailboxes, and daemon control. Let the conversation
move past a pending question and its server lingers, still offering a decision nobody
wants. The hub removes the cause: agents stop owning servers. There is ONE hub per
repo, on a stable port, and everything an agent wants seen (a question, a report, a
status board) is POSTed to it as a *surface*. The hub owns the single browser tab.

The rules that fix the named failures:

1. One tab, ever. The hub opens the browser only when no tab is connected (it knows:
   the shell holds an SSE stream). If a tab is already open, a new surface is pushed
   into it and the shell switches over. A hub restart reuses the same port, so an old
   tab reconnects instead of dying.
2. Agents are clients, never owners. `ensure()` finds the live hub or race-safely
   starts one (O_EXCL lockfile; losers use the winner). Nothing ever kills the hub to
   take its place, and no verb here can kill another session's pending surface.
3. Surfaces have a lifecycle: pending -> answered | withdrawn | expired. When the
   conversation negates a question, the asking agent withdraws it (`withdraw`, or
   `--supersede-tag` on the replacement) and the shell greys it out in place. The hub
   itself exits after IDLE_SECONDS with no tab, no pending surface, and no waiter, so
   an abandoned hub reaps itself.
4. Submit stays exit-as-signal without a per-question server: `ask` posts the surface
   and blocks until it resolves (long-poll), writing the answer to the sink file the
   caller named. The waiting process completing is still the signal; the server just
   is not the thing that completes. Exit codes: 0 answered, 3 withdrawn, 4 expired or
   timed out, 5 hub unreachable.

Transport only: the hub never parses or applies a submission; it writes the blob to
the surface's sink and the session reads it. Pages stay self-contained kit pages; the
shell embeds them in an iframe, and their relative POST (`selection` / `submit` /
`answers`) lands scoped under /s/<id>/, so the same page works served alone or hubbed.
Pure stdlib. State (lock, log, surfaces) lives under STATE_DIR, gitignored.

Routes: GET / (the shell) . GET /events (shell SSE) . GET /api/state . GET /s/<id>/
(the surface page) . GET /s/<id>/a/<path> (registered assets, Range-capable) . GET
/s/<id>/wait?timeout=N (long-poll a resolution) . POST /api/post . POST /api/update .
POST /api/withdraw . POST /api/push (toast/progress) . POST /s/<id>/submit (aliases:
selection, answers) . POST /api/shutdown.

CLI (module form, from the repo root):
  serve [--port N] [--idle SECS]     run the hub in the foreground (ensure() spawns this)
  ask <page.html> --sink <path> [--title T] [--tag TAG] [--session S] [--assets DIR]
                                     post + wait; prints ANSWERED/WITHDRAWN -> sink
  post <page.html> [--kind status|report] [--title T] [--tag TAG] [--assets DIR]
                                     post without waiting; prints the surface id + url
  update <id> <page.html>            replace a surface's page in place (same card, same tab)
  withdraw <id|--tag TAG> [--reason WHY]
  push <id> --toast TEXT | --progress 0..1 [--text T]
  status                             one line per surface + client/waiter counts
  open                               reopen the browser tab on the live hub
  stop                               shut the hub down (surfaces persist for the next one)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from webui import kit  # noqa: E402  (one palette, one shell; ADR/decision record in this repo)

# ---- repo constants (the catered part) --------------------------------------------------
HUB_NAME = "chumicro"                      # shown in the shell header and the tab title
SPAWN_CWD = os.path.dirname(_HERE)    # the dir holding the webui package (spawned server's cwd)
REPO_ROOT = os.path.dirname(_HERE)
STATE_DIR = os.path.join(REPO_ROOT, ".scratch", "hub")
DEFAULT_PORT = 17871                  # stable per repo, so a reopened hub revives the old tab
IDLE_SECONDS = 900                    # no tab + no pending + no waiter this long -> exit
PENDING_TTL = 24 * 3600               # a pending surface older than this expires
ENV_NO_OPEN = "HUB_NO_OPEN"           # set on a poster to forbid the auto-open for its post
KEEP_RESOLVED = 20                    # answered/withdrawn surfaces kept for the shell's history

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")


# ---- small shared helpers ----------------------------------------------------------------
def _now():
    return time.time()


def _state_dir(override=None):
    d = os.path.abspath(override or os.environ.get("HUB_STATE_DIR") or STATE_DIR)
    os.makedirs(os.path.join(d, "surfaces"), exist_ok=True)
    return d


def _lock_path(state):
    return os.path.join(state, "hub.lock")


def _read_lock(state):
    try:
        with open(_lock_path(state)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _probe(port, timeout=0.8):
    """True when a live hub answers /api/state on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("hub") == HUB_NAME
    except Exception:  # noqa: BLE001  (any failure means: not our live hub)
        return False


def _api(port, path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---- the surface registry -----------------------------------------------------------------
class Surface:
    __slots__ = ("id", "title", "kind", "session", "tag", "sink", "asset_dir",
                 "status", "created", "resolved", "reason", "event", "rev")

    def to_meta(self):
        return {k: getattr(self, k) for k in self.__slots__ if k != "event"}


class Registry:
    """In-memory surface table, mirrored to <state>/surfaces/<id>/ so a hub restart
    reloads history and still-pending questions instead of orphaning their waiters."""

    def __init__(self, state):
        self.state = state
        self.by_id = {}
        self.lock = threading.Lock()
        self._counter = 0
        self._load()

    def _dir(self, sid):
        return os.path.join(self.state, "surfaces", sid)

    def _load(self):
        root = os.path.join(self.state, "surfaces")
        for sid in sorted(os.listdir(root)):
            meta_path = os.path.join(root, sid, "meta.json")
            try:
                with open(meta_path) as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            s = Surface()
            for k in Surface.__slots__:
                if k != "event":
                    setattr(s, k, meta.get(k))
            s.event = threading.Event()
            if s.status != "pending":
                s.event.set()
            self.by_id[s.id] = s

    def _persist(self, s):
        os.makedirs(self._dir(s.id), exist_ok=True)
        tmp = os.path.join(self._dir(s.id), "meta.json.tmp")
        with open(tmp, "w") as fh:
            json.dump(s.to_meta(), fh)
        os.replace(tmp, os.path.join(self._dir(s.id), "meta.json"))

    def add(self, html, *, title, kind, session, tag, sink, asset_dir):
        with self.lock:
            self._counter += 1
            digest = hashlib.sha1(f"{title}{session}{self._counter}{_now()}".encode()).hexdigest()[:6]
            s = Surface()
            s.id = f"s{self._counter:03d}-{digest}"
            s.title, s.kind, s.session, s.tag = title, kind, session, tag
            s.sink, s.asset_dir = sink, asset_dir
            s.status, s.created, s.resolved, s.reason, s.rev = "pending", _now(), None, "", 1
            s.event = threading.Event()
            os.makedirs(self._dir(s.id), exist_ok=True)
            with open(os.path.join(self._dir(s.id), "page.html"), "w") as fh:
                fh.write(html)
            self._persist(s)
            self.by_id[s.id] = s
            self._prune()
            return s

    def update_page(self, sid, html):
        s = self.by_id.get(sid)
        if s is None:
            return None
        with open(os.path.join(self._dir(sid), "page.html"), "w") as fh:
            fh.write(html)
        s.rev += 1
        self._persist(s)
        return s

    def resolve(self, sid, status, reason=""):
        s = self.by_id.get(sid)
        if s is None or s.status != "pending":
            return s
        s.status, s.resolved, s.reason = status, _now(), reason
        self._persist(s)
        s.event.set()
        return s

    def _prune(self):
        resolved = sorted((s for s in self.by_id.values() if s.status != "pending"),
                          key=lambda s: s.resolved or 0)
        for s in resolved[:-KEEP_RESOLVED] if len(resolved) > KEEP_RESOLVED else []:
            self.by_id.pop(s.id, None)
            shutil.rmtree(self._dir(s.id), ignore_errors=True)

    def pending(self):
        return [s for s in self.by_id.values() if s.status == "pending"]

    def ordered(self):
        return sorted(self.by_id.values(), key=lambda s: s.created)


# ---- the hub server ------------------------------------------------------------------------
import http.server  # noqa: E402


class HubServer:
    def __init__(self, state, port=DEFAULT_PORT, idle=IDLE_SECONDS):
        self.state = state
        self.registry = Registry(state)
        self.idle = idle
        self.clients = []               # one queue.Queue per connected shell tab
        self.clients_lock = threading.Lock()
        self.waiters = 0                # in-flight /wait long-polls
        self.waiters_lock = threading.Lock()
        self.last_activity = _now()
        self.last_open = 0.0
        self.httpd = None
        self.port = port

    # -- SSE fan-out --
    def push(self, event):
        frame = ("data: " + json.dumps(event) + "\n\n").encode()
        with self.clients_lock:
            clients = list(self.clients)
        for q in clients:
            q.put(frame)
        return len(clients)

    def client_count(self):
        with self.clients_lock:
            return len(self.clients)

    def surface_event(self, s, op):
        self.push({"type": "surface", "op": op, "surface": s.to_meta()})

    # -- open policy: the ONE place a browser tab is born --
    def maybe_open(self, allow):
        self.last_activity = _now()
        if not allow or os.environ.get(ENV_NO_OPEN):
            return
        if self.client_count() > 0:
            return                       # a tab is live; the SSE push is the notification
        if _now() - self.last_open < 10:
            return                       # an open is already in flight; never double-tab
        self.last_open = _now()
        try:
            webbrowser.open(f"http://127.0.0.1:{self.port}/")
        except Exception:  # noqa: BLE001  (headless: the printed URL is the fallback)
            pass

    # -- request handler --
    def handler(self):
        hub = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _deny_foreign_host(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    self._text(403, "hub answers 127.0.0.1 only\n")
                    return True
                return False

            def _text(self, code, body, ctype="text/plain; charset=utf-8"):
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, obj, code=200):
                self._text(code, json.dumps(obj), "application/json")

            def _body(self):
                length = int(self.headers.get("Content-Length", 0))
                return self.rfile.read(length).decode("utf-8", "replace") if length else ""

            # ---- GET ----
            def do_GET(self):
                if self._deny_foreign_host():
                    return
                hub.last_activity = _now()
                path = urllib.parse.unquote(self.path.split("?")[0])
                if path == "/":
                    return self._text(200, shell_page(hub), "text/html; charset=utf-8")
                if path == "/events":
                    return self._events()
                if path == "/api/state":
                    return self._json({"hub": HUB_NAME, "port": hub.port,
                                       "clients": hub.client_count(),
                                       "surfaces": [s.to_meta() for s in hub.registry.ordered()]})
                m = re.match(r"^/s/([a-z0-9-]+)(/.*)?$", path)
                if m:
                    return self._surface_get(m.group(1), m.group(2) or "/")
                self._text(404, "not found\n")

            def _surface_get(self, sid, rest):
                s = hub.registry.by_id.get(sid)
                if s is None:
                    return self._text(410, "this surface is gone; the hub keeps only recent history\n")
                if rest in ("/", "/page.html", ""):
                    if s.status == "withdrawn":
                        # a withdrawn question must never read as a live one
                        return self._text(410, f"withdrawn: {s.reason or 'the session moved on'}\n")
                    page = os.path.join(hub.registry._dir(sid), "page.html")
                    try:
                        with open(page, "rb") as fh:
                            return self._text(200, fh.read(), "text/html; charset=utf-8")
                    except OSError:
                        return self._text(404, "page missing\n")
                if rest == "/wait":
                    return self._wait(s)
                if rest.startswith("/a/"):
                    return self._asset(s, rest[3:])
                self._text(404, "not found\n")

            def _wait(self, s):
                with hub.waiters_lock:
                    hub.waiters += 1
                try:
                    s.event.wait(timeout=25)
                finally:
                    with hub.waiters_lock:
                        hub.waiters -= 1
                hub.last_activity = _now()
                self._json({"status": s.status, "reason": s.reason, "sink": s.sink})

            def _asset(self, s, rel):
                if not s.asset_dir:
                    return self._text(404, "no assets registered for this surface\n")
                base = os.path.realpath(s.asset_dir)
                full = os.path.realpath(os.path.join(base, rel))
                if not full.startswith(base + os.sep) or not os.path.isfile(full):
                    return self._text(404, "not found\n")
                ctype = "application/octet-stream"
                for ext, t in ((".wav", "audio/wav"), (".mp3", "audio/mpeg"), (".png", "image/png"),
                               (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".svg", "image/svg+xml"),
                               (".json", "application/json"), (".txt", "text/plain"), (".mp4", "video/mp4")):
                    if full.lower().endswith(ext):
                        ctype = t
                        break
                size = os.path.getsize(full)
                rng = self.headers.get("Range")
                lo, hi = 0, size - 1
                code = 200
                if rng and rng.startswith("bytes="):
                    # single-range only: all a media element ever sends; seeks need this
                    lo_s, _, hi_s = rng[len("bytes="):].partition("-")
                    try:
                        lo = int(lo_s) if lo_s else max(0, size - int(hi_s))
                        hi = min(int(hi_s), size - 1) if (lo_s and hi_s) else size - 1
                        code = 206
                    except ValueError:
                        lo, hi, code = 0, size - 1, 200
                    if lo > hi or lo >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                if code == 206:
                    self.send_header("Content-Range", f"bytes {lo}-{hi}/{size}")
                self.send_header("Content-Length", str(hi - lo + 1))
                self.end_headers()
                try:
                    with open(full, "rb") as fh:
                        fh.seek(lo)
                        remaining = hi - lo + 1
                        while remaining > 0:
                            chunk = fh.read(min(65536, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass                 # media elements abort ranges constantly; normal

            def _events(self):
                q = queue.Queue()
                with hub.clients_lock:
                    hub.clients.append(q)
                hub.push({"type": "clients", "n": hub.client_count()})
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            frame = q.get(timeout=15)
                        except queue.Empty:
                            frame = b": keepalive\n\n"
                        self.wfile.write(frame)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with hub.clients_lock:
                        if q in hub.clients:
                            hub.clients.remove(q)
                    hub.last_activity = _now()

            # ---- POST ----
            def do_POST(self):
                if self._deny_foreign_host():
                    return
                hub.last_activity = _now()
                path = self.path.split("?")[0]
                raw = self._body()
                m = re.match(r"^/s/([a-z0-9-]+)/(submit|selection|answers)$", path)
                if m:
                    return self._submit(m.group(1), raw)
                try:
                    payload = json.loads(raw) if raw else {}
                except ValueError:
                    payload = {}
                if path == "/api/post":
                    return self._post_surface(payload)
                if path == "/api/update":
                    s = hub.registry.update_page(payload.get("id", ""), payload.get("html", ""))
                    if s is None:
                        return self._json({"ok": False, "error": "no such surface"}, 404)
                    hub.surface_event(s, "updated")
                    return self._json({"ok": True, "rev": s.rev})
                if path == "/api/withdraw":
                    return self._withdraw(payload)
                if path == "/api/push":
                    event = {"type": payload.get("kind", "toast"), "surface": payload.get("id"),
                             "text": payload.get("text", ""), "value": payload.get("value")}
                    return self._json({"ok": True, "clients": hub.push(event)})
                if path == "/api/shutdown":
                    self._json({"ok": True})
                    threading.Thread(target=hub.stop, daemon=True).start()
                    return
                self._text(404, "not found\n")

            def _post_surface(self, p):
                html = p.get("html") or ""
                if not html.strip():
                    return self._json({"ok": False, "error": "empty html"}, 400)
                if p.get("supersede_tag"):
                    for s in hub.registry.pending():
                        if s.tag == p["supersede_tag"] and s.session == p.get("session"):
                            hub.registry.resolve(s.id, "withdrawn", "superseded by a newer surface")
                            hub.surface_event(s, "withdrawn")
                s = hub.registry.add(
                    html,
                    title=(p.get("title") or "untitled")[:120],
                    kind=p.get("kind") or "ask",
                    session=p.get("session") or "",
                    tag=p.get("tag") or "",
                    sink=p.get("sink") or "",
                    asset_dir=p.get("asset_dir") or "",
                )
                hub.surface_event(s, "added")
                hub.maybe_open(allow=p.get("open", True))
                return self._json({"ok": True, "id": s.id,
                                   "url": f"http://127.0.0.1:{hub.port}/s/{s.id}/",
                                   "hub": f"http://127.0.0.1:{hub.port}/"})

            def _submit(self, sid, blob):
                s = hub.registry.by_id.get(sid)
                if s is None:
                    return self._json({"ok": False, "error": "no such surface"}, 404)
                if s.status == "withdrawn":
                    return self._json({"ok": False, "error": "withdrawn: " + (s.reason or "")}, 410)
                if s.sink:
                    tmp = s.sink + ".tmp"
                    os.makedirs(os.path.dirname(os.path.abspath(s.sink)) or ".", exist_ok=True)
                    with open(tmp, "w") as fh:
                        fh.write(blob)
                    os.replace(tmp, s.sink)
                first = s.status == "pending"
                hub.registry.resolve(sid, "answered")
                hub.surface_event(s, "answered")
                print(f"ANSWERED {sid} -> {s.sink or '(no sink)'}", flush=True)
                return self._json({"ok": True, "first": first})

            def _withdraw(self, p):
                targets = []
                if p.get("id"):
                    s = hub.registry.by_id.get(p["id"])
                    targets = [s] if s else []
                elif p.get("tag"):
                    targets = [s for s in hub.registry.pending() if s.tag == p["tag"]
                               and (not p.get("session") or s.session == p["session"])]
                done = []
                for s in targets:
                    if s and s.status == "pending":
                        hub.registry.resolve(s.id, "withdrawn", p.get("reason", "the session moved on"))
                        hub.surface_event(s, "withdrawn")
                        done.append(s.id)
                return self._json({"ok": True, "withdrawn": done})

        return H

    # -- lifecycle --
    def _reaper(self):
        while self.httpd is not None:
            time.sleep(30)
            now = _now()
            for s in self.registry.pending():
                if now - s.created > PENDING_TTL:
                    self.registry.resolve(s.id, "expired", "pending past its ttl")
                    self.surface_event(s, "expired")
            with self.waiters_lock:
                waiting = self.waiters
            if (self.idle and self.client_count() == 0 and waiting == 0
                    and not self.registry.pending()
                    and now - self.last_activity > self.idle):
                print("hub idle; exiting", flush=True)
                self.stop()
                return

    def serve(self):
        class _Quiet(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                exc = sys.exc_info()[1]
                if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
                    return
                super().handle_error(request, client_address)

        try:
            self.httpd = _Quiet(("127.0.0.1", self.port), self.handler())
        except OSError:
            self.httpd = _Quiet(("127.0.0.1", 0), self.handler())  # stable port taken: fall back
        self.port = self.httpd.server_port
        with open(_lock_path(self.state), "w") as fh:
            json.dump({"pid": os.getpid(), "port": self.port, "started": _now()}, fh)
        try:
            os.remove(_lock_path(self.state) + ".claim")   # the spawn is done; the lock takes over
        except OSError:
            pass
        print(f"HUB SERVING http://127.0.0.1:{self.port}/", flush=True)
        threading.Thread(target=self._reaper, daemon=True).start()
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            lock = _read_lock(self.state)
            if lock and lock.get("pid") == os.getpid():
                try:
                    os.remove(_lock_path(self.state))
                except OSError:
                    pass
        print("hub closed", flush=True)

    def stop(self):
        if self.httpd is not None:
            httpd, self.httpd = self.httpd, None
            httpd.shutdown()


# ---- the shell page --------------------------------------------------------------------------
SHELL_CSS = """
body{padding:0;margin:0;overflow:hidden}
.hubbar{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);
 background:var(--panel);flex-wrap:wrap}
.hubbar .brand{font-weight:700;letter-spacing:.2px}
.hubbar .brand .dot{display:inline-block;width:9px;height:9px;border-radius:99px;background:var(--accent);
 margin-right:7px;box-shadow:0 0 8px var(--glow)}
.chips{display:flex;gap:6px;flex-wrap:wrap;flex:1;min-width:0}
.chip-s{font:inherit;font-size:12.5px;padding:4px 11px;border-radius:999px;border:1px solid var(--border);
 background:var(--panel);color:var(--faint);cursor:pointer;display:flex;align-items:center;gap:6px;max-width:260px}
.chip-s .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip-s .st{width:8px;height:8px;border-radius:99px;flex:0 0 auto;background:var(--faint)}
.chip-s.pending .st{background:var(--warn)}
.chip-s.answered .st{background:var(--good)}
.chip-s.withdrawn .st,.chip-s.expired .st{background:var(--bad)}
.chip-s.focused{border-color:var(--accent);color:var(--fg);box-shadow:0 0 0 1px var(--accent)}
.chip-s.withdrawn .t,.chip-s.expired .t{text-decoration:line-through;opacity:.7}
.stage{position:relative;height:calc(100vh - 46px)}
.stage iframe{border:0;width:100%;height:100%;background:var(--bg)}
.banner{position:absolute;left:50%;top:14px;transform:translateX(-50%);background:var(--panel);
 border:1px solid var(--border);border-radius:10px;padding:8px 16px;font-size:13.5px;
 box-shadow:0 6px 24px var(--shadow);display:none;z-index:5}
.banner.show{display:block}
.banner.good{border-color:var(--good)} .banner.bad{border-color:var(--bad)}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 color:var(--faint);font-size:15px}
#themebtn{position:static}
"""

SHELL_JS = """
(function(){
var surfaces={}, focused=null, baseTitle=document.title, rev={};
var chips=document.getElementById('chips'), frame=document.getElementById('frame');
var banner=document.getElementById('banner'), empty=document.getElementById('empty');
function fmt(ts){var d=new Date(ts*1000);return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
function pendingCount(){var n=0;Object.values(surfaces).forEach(function(s){if(s.status==='pending')n++;});return n;}
function setTitle(){var n=pendingCount();document.title=(n?('('+n+') '):'')+baseTitle;}
function showBanner(text,kind){banner.textContent=text;banner.className='banner show '+(kind||'');
 clearTimeout(banner._t);banner._t=setTimeout(function(){banner.classList.remove('show');},3200);}
function focus(id){
 var s=surfaces[id];if(!s)return;focused=id;
 if(s.status==='withdrawn'||s.status==='expired'){
   frame.removeAttribute('src');frame.style.display='none';empty.style.display='flex';
   empty.textContent=s.status+': '+(s.reason||'the session moved on');
 }else{
   empty.style.display='none';frame.style.display='block';
   var want='/s/'+id+'/?rev='+(s.rev||1);
   if(frame.dataset.at!==want){frame.src=want;frame.dataset.at=want;}
   if(s.status==='answered')showBanner('answered at '+fmt(s.resolved)+'; the session has it','good');
 }
 render();
}
function render(){
 chips.innerHTML='';
 var list=Object.values(surfaces).sort(function(a,b){return a.created-b.created;});
 list.forEach(function(s){
   var b=document.createElement('button');
   b.className='chip-s '+s.status+(s.id===focused?' focused':'');
   b.innerHTML='<span class="st"></span><span class="t"></span>';
   b.querySelector('.t').textContent=s.title;
   b.title=s.kind+' · '+s.status+(s.session?(' · '+s.session):'');
   b.onclick=function(){focus(s.id);};
   chips.appendChild(b);
 });
 if(!list.length){empty.style.display='flex';empty.textContent='no surfaces yet; the session will post here.';
  frame.style.display='none';}
 setTitle();
}
function autoFocus(s){
 // a new pending surface takes the stage unless the human is mid-decision on another pending one
 var cur=surfaces[focused];
 if(!cur||cur.status!=='pending'||cur.id===s.id)focus(s.id);else render();
}
function apply(s,op){
 surfaces[s.id]=s;
 if(op==='added'){autoFocus(s);showBanner('new: '+s.title,'');}
 else if(op==='updated'&&s.id===focused){frame.dataset.at='';focus(s.id);}
 else if(op==='answered'&&s.id===focused){focus(s.id);}
 else if((op==='withdrawn'||op==='expired')&&s.id===focused){focus(s.id);}
 else render();
}
fetch('/api/state').then(function(r){return r.json();}).then(function(st){
 st.surfaces.forEach(function(s){surfaces[s.id]=s;});
 var pend=st.surfaces.filter(function(s){return s.status==='pending';});
 var last=st.surfaces[st.surfaces.length-1];
 render();
 if(pend.length)focus(pend[pend.length-1].id);else if(last)focus(last.id);
});
var es=new EventSource('/events');
es.onmessage=function(ev){var m;try{m=JSON.parse(ev.data);}catch(e){return;}
 if(m.type==='surface')apply(m.surface,m.op);
 else if(m.type==='toast')showBanner(m.text,'good');
 else if(m.type==='progress'){showBanner((m.text||'working')+' '+Math.round((m.value||0)*100)+'%','');}
};
})();
"""


def shell_page(hub):
    body = (
        '<div class="hubbar"><span class="brand"><span class="dot"></span>'
        + kit._esc(HUB_NAME) +
        '</span><div class="chips" id="chips"></div>'
        '<button id="themebtn" type="button"></button></div>'
        '<div class="stage"><div class="empty" id="empty">no surfaces yet.</div>'
        '<iframe id="frame" title="surface"></iframe>'
        '<div class="banner" id="banner"></div></div>'
    )
    return kit.page(HUB_NAME, body, extra_css=SHELL_CSS, extra_js=SHELL_JS, theme_button=False)


# ---- client side: ensure + verbs ----------------------------------------------------------------
def ensure(state_dir=None, port=None):
    """Return (port, url) of the live hub, starting one race-safely when none answers.

    The winner of the O_EXCL lockfile spawns the detached server and everyone else uses
    it. A stale lock (dead pid, no answer) is removed and the acquisition retried."""
    state = _state_dir(state_dir)
    want = int(port or os.environ.get("HUB_PORT") or DEFAULT_PORT)
    for _ in range(40):                                  # ~10 s worst case
        lock = _read_lock(state)
        if lock and _probe(lock.get("port", 0)):
            return lock["port"], f"http://127.0.0.1:{lock['port']}/"
        if lock and not _pid_alive(lock.get("pid")):
            try:
                os.remove(_lock_path(state))
            except OSError:
                pass
            lock = None
        if lock is None:
            claim = _lock_path(state) + ".claim"
            try:
                # a claim only serializes the spawn; one older than 10 s is a crashed
                # spawner's leftover, safe to steal (the real lock is the server's own)
                if os.path.exists(claim) and _now() - os.path.getmtime(claim) > 10:
                    os.remove(claim)
                fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, OSError):
                time.sleep(0.25)
                continue
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            log = open(os.path.join(state, "hub.log"), "ab")
            subprocess.Popen(
                [sys.executable, "-m", "webui.hub", "--state", state, "serve", "--port", str(want)],
                cwd=SPAWN_CWD, stdout=log, stderr=log, start_new_session=True)
        time.sleep(0.25)
    raise SystemExit(f"hub did not come up; see {os.path.join(state, 'hub.log')}")


def _session_id():
    return os.environ.get("CLAUDE_SESSION_ID", "")[:12] or f"pid{os.getppid()}"


def post(page_path, *, title=None, kind="ask", tag="", sink="", assets="",
         supersede_tag="", state_dir=None, open_tab=True):
    with open(page_path) as fh:
        html = fh.read()
    port, _ = ensure(state_dir)
    if os.environ.get(ENV_NO_OPEN) or os.environ.get("PICKER_NO_OPEN"):
        open_tab = False
    reply = _api(port, "/api/post", {
        "html": html, "title": title or os.path.basename(page_path), "kind": kind,
        "session": _session_id(), "tag": tag, "sink": os.path.abspath(sink) if sink else "",
        "asset_dir": os.path.abspath(assets) if assets else "",
        "supersede_tag": supersede_tag, "open": open_tab,
    })
    if not reply.get("ok"):
        raise SystemExit(f"hub refused the surface: {reply.get('error')}")
    return port, reply["id"], reply["url"]


def wait(port, sid, timeout=None, state_dir=None):
    """Block until the surface resolves; returns its final status string. Survives a hub
    restart (re-ensure + retry), so the waiting process stays the one reliable signal."""
    deadline = (_now() + timeout) if timeout else None
    while True:
        try:
            reply = _api(port, f"/s/{sid}/wait", timeout=35)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(1)
            try:
                port, _ = ensure(state_dir)
                continue
            except SystemExit:
                return "unreachable"
        if reply.get("status") != "pending":
            return reply["status"]
        if deadline and _now() > deadline:
            return "timeout"


# ---- CLI -------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="surface hub: one server, one tab, many surfaces")
    ap.add_argument("--state", default=None, help="state dir override (default: repo .scratch/hub)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the hub in the foreground (ensure() spawns this)")
    sp.add_argument("--port", type=int, default=DEFAULT_PORT)
    sp.add_argument("--idle", type=int, default=IDLE_SECONDS)

    sp = sub.add_parser("ask", help="post a surface and wait for its answer (exit-as-signal)")
    sp.add_argument("page")
    sp.add_argument("--sink", required=True, help="file the answer blob is written to")
    sp.add_argument("--title", default=None)
    sp.add_argument("--tag", default="")
    sp.add_argument("--assets", default="", help="directory served under the surface's a/ path")
    sp.add_argument("--supersede-tag", default="", help="withdraw my older pending surfaces with this tag")
    sp.add_argument("--timeout", type=float, default=None, help="seconds before giving up (exit 4)")

    sp = sub.add_parser("post", help="post a surface without waiting (status boards, reports)")
    sp.add_argument("page")
    sp.add_argument("--kind", default="status", choices=["ask", "status", "report"])
    sp.add_argument("--title", default=None)
    sp.add_argument("--tag", default="")
    sp.add_argument("--assets", default="")
    sp.add_argument("--sink", default="")
    sp.add_argument("--supersede-tag", default="")

    sp = sub.add_parser("update", help="replace a surface's page in place (same card, same tab)")
    sp.add_argument("id")
    sp.add_argument("page")

    sp = sub.add_parser("withdraw", help="resolve a pending surface as withdrawn")
    sp.add_argument("id", nargs="?", default="")
    sp.add_argument("--tag", default="")
    sp.add_argument("--reason", default="the session moved on")

    sp = sub.add_parser("push", help="toast or progress on the open shell")
    sp.add_argument("id", nargs="?", default="")
    sp.add_argument("--toast", default=None)
    sp.add_argument("--progress", type=float, default=None)
    sp.add_argument("--text", default="")

    sub.add_parser("status", help="list surfaces and client/waiter counts")
    sub.add_parser("open", help="reopen the browser tab on the live hub")
    sub.add_parser("stop", help="shut the hub down (surfaces persist)")

    args = ap.parse_args(argv)

    if args.cmd == "serve":
        state = _state_dir(args.state)
        lock = _read_lock(state)
        if lock and _probe(lock.get("port", 0)):
            print(f"hub already live on port {lock['port']}", flush=True)
            return
        HubServer(state, port=args.port, idle=args.idle).serve()
        return

    if args.cmd == "ask":
        port, sid, url = post(args.page, title=args.title, kind="ask", tag=args.tag,
                              sink=args.sink, assets=args.assets,
                              supersede_tag=args.supersede_tag, state_dir=args.state)
        print(f"ASKED {sid} {url}", flush=True)
        status = wait(port, sid, timeout=args.timeout, state_dir=args.state)
        sink = os.path.abspath(args.sink)
        if status == "answered":
            print(f"ANSWERED -> {sink}", flush=True)
            sys.exit(0)
        if status == "withdrawn":
            print(f"WITHDRAWN (no answer): {sid}", flush=True)
            sys.exit(3)
        if status in ("expired", "timeout"):
            print(f"EXPIRED (no answer): {sid}", flush=True)
            sys.exit(4)
        print(f"HUB UNREACHABLE; if the human submitted, the blob is at {sink}", flush=True)
        sys.exit(5)

    if args.cmd == "post":
        _, sid, url = post(args.page, title=args.title, kind=args.kind, tag=args.tag,
                           sink=args.sink, assets=args.assets,
                           supersede_tag=args.supersede_tag, state_dir=args.state)
        print(f"POSTED {sid} {url}", flush=True)
        return

    # every remaining verb needs a live hub
    state = _state_dir(args.state)
    lock = _read_lock(state)
    if not (lock and _probe(lock.get("port", 0))):
        if args.cmd in ("status", "stop"):
            print("no live hub", flush=True)
            return
        raise SystemExit("no live hub; post or ask first")
    port = lock["port"]

    if args.cmd == "update":
        with open(args.page) as fh:
            html = fh.read()
        reply = _api(port, "/api/update", {"id": args.id, "html": html})
        print(f"UPDATED {args.id} rev {reply.get('rev')}" if reply.get("ok")
              else f"update failed: {reply.get('error')}", flush=True)
    elif args.cmd == "withdraw":
        reply = _api(port, "/api/withdraw",
                     {"id": args.id, "tag": args.tag, "session": _session_id() if args.tag else "",
                      "reason": args.reason})
        print(f"WITHDRAWN {' '.join(reply.get('withdrawn', [])) or '(nothing pending matched)'}", flush=True)
    elif args.cmd == "push":
        if args.toast is not None:
            _api(port, "/api/push", {"kind": "toast", "id": args.id, "text": args.toast})
        if args.progress is not None:
            _api(port, "/api/push", {"kind": "progress", "id": args.id,
                                     "value": args.progress, "text": args.text})
    elif args.cmd == "status":
        st = _api(port, "/api/state")
        print(f"hub http://127.0.0.1:{port}/  clients={st['clients']}", flush=True)
        for s in st["surfaces"]:
            print(f"  {s['id']}  {s['status']:<9} {s['kind']:<7} {s['title']}"
                  + (f"  [{s['tag']}]" if s.get("tag") else ""), flush=True)
    elif args.cmd == "open":
        webbrowser.open(f"http://127.0.0.1:{port}/")
    elif args.cmd == "stop":
        try:
            _api(port, "/api/shutdown", {})
        except Exception:  # noqa: BLE001  (already going down is fine)
            pass
        print("hub stopped", flush=True)


if __name__ == "__main__":
    main()
