"""Smoke test for the webui kit + the session server.

Pure stdlib, no browser, no external imports (webui stays a neutral top-level package).
Run: `python3 -m webui.check_kit`  (exit 0 = green). Covers:
  1. the one palette passes the dark-override contract + light/dark have identical keys;
  2. `page()` emits a self-contained, dark-clean doc with the theme toggle, and the SSE
     client only when `live=True`;
  3. `content_key` is stable for identical content and differs for different content;
  4. a full session round-trip: an SSE client connects, a `/push` reload reaches it, a
     `/selection` post writes the sink, and `/canvas` serves the current page.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# Run-anywhere: importable both as `python3 -m webui.check_kit` and as a bare gate script
# (`<venv>/python webui/check_kit.py`). Put the repo root on the path either way.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webui import kit
from webui.session import SessionServer, push_to


def _check(name, cond, detail=""):
    if not cond:
        raise SystemExit(f"FAIL [{name}] {detail}")
    print(f"  ok  {name}")


def _palette():
    _check("palette/keys-match",
           set(kit.PALETTE_LIGHT) == set(kit.PALETTE_DARK),
           f"light={sorted(kit.PALETTE_LIGHT)} dark={sorted(kit.PALETTE_DARK)}")
    verified = kit.assert_full_dark_override(kit.palette_css(), label="kit-palette")
    _check("palette/dark-override", len(verified) == len(kit.PALETTE_LIGHT),
           f"verified {verified}")


def _page():
    html = kit.page("Demo", "<div class='wrap'><h1>hi</h1></div>")
    _check("page/self-contained", html.startswith("<!doctype html>") and "<style>" in html and "</html>" in html)
    _check("page/theme-toggle", "id=\"themebtn\"" in html and kit.THEME_KEY in html)
    _check("page/no-sse-when-static", "EventSource" not in html)
    live = kit.page("Demo", "<div class='wrap'>x</div>", live=True)
    _check("page/sse-when-live", "EventSource" in live and "/events" in live)


def _content_key():
    a = kit.content_key("alpha")
    b = kit.content_key("alpha")
    c = kit.content_key("beta")
    _check("content_key/stable", a == b, f"{a} != {b}")
    _check("content_key/sensitive", a != c, f"{a} == {c}")
    _check("content_key/prefix", kit.content_key("x", prefix="picker").startswith("picker:"))


def _read_until(url, target, timeout=6):
    """Connect to an SSE stream and collect `data:` lines until one contains `target`."""
    res = {"hit": False, "lines": [], "err": None}

    def run():
        try:
            stream = urllib.request.urlopen(url, timeout=timeout)
            deadline = time.time() + timeout
            for raw in stream:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    res["lines"].append(line)
                    if target in line:
                        res["hit"] = True
                        return
                if time.time() > deadline:
                    return
        except Exception as exc:  # noqa: BLE001 - record it, the assert reports it
            res["err"] = str(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, res


def _session():
    with tempfile.TemporaryDirectory() as tmp:
        server = SessionServer(tmp).start()
        try:
            with open(f"{tmp}/canvas.html", "w") as handle:
                handle.write(kit.page("Canvas v1", "<div class='wrap'>one</div>", live=True))

            base = f"http://127.0.0.1:{server.port}"
            reader, res = _read_until(f"{base}/events", "reload")

            # wait until the SSE client is actually registered (push reports the client count)
            for _ in range(40):
                if push_to(server.port, {"type": "ping"}).get("clients", 0) >= 1:
                    break
                time.sleep(0.1)
            _check("session/sse-connected", res["err"] is None, f"sse error: {res['err']}")

            pushed = push_to(server.port, {"type": "reload"})
            _check("session/push-reaches-client", pushed.get("clients", 0) >= 1, f"{pushed}")
            reader.join(6)
            _check("session/reload-received", res["hit"], f"err={res['err']} lines={res['lines']}")

            # the picker posts /selection to the canvas sink (latest wins)
            req = urllib.request.Request(f"{base}/selection", data=b"picked-x",
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                _check("session/selection-ok", resp.status == 200)
            with open(server.sink) as handle:
                _check("session/selection-sink", handle.read() == "picked-x")

            # /canvas serves the current page
            with urllib.request.urlopen(f"{base}/canvas", timeout=5) as resp:
                _check("session/canvas-served", b"Canvas v1" in resp.read())
        finally:
            server.stop()


def _canvas_cli():
    """The live-canvas CLI: `show --wrap` writes a live page and pushes reload into the open tab."""
    import types

    from webui import session
    with tempfile.TemporaryDirectory() as tmp:
        server = SessionServer(tmp).start()
        try:
            with open(f"{tmp}/{session.PORT_FILE}", "w") as handle:
                handle.write(str(server.port))
            reader, res = _read_until(f"http://127.0.0.1:{server.port}/events", "reload")
            for _ in range(40):
                if push_to(server.port, {"type": "ping"}).get("clients", 0) >= 1:
                    break
                time.sleep(0.1)
            body = f"{tmp}/body.html"
            with open(body, "w") as handle:
                handle.write("<div class='wrap'><h1>live canvas</h1></div>")
            session._cmd_show(types.SimpleNamespace(directory=tmp, file=body, wrap=True, title="t"))
            reader.join(6)
            _check("canvas/show-pushes-reload", res["hit"], f"{res}")
            shown = open(f"{tmp}/canvas.html").read()
            _check("canvas/page-is-live", "EventSource" in shown and "live canvas" in shown)
        finally:
            server.stop()


def _hub():
    """The surface hub: post a surface, read it back, submit to its sink, watch the wait
    release, withdraw a second surface and see its page answer 410."""
    import json

    from webui.hub import HubServer, _state_dir

    with tempfile.TemporaryDirectory() as tmp:
        # the hub owns its state layout; never hardcode its store subdir here
        state = _state_dir(os.path.join(tmp, "state"))
        server = HubServer(state, port=0, idle=0)
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        for _ in range(50):
            if server.httpd is not None and server.port:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        base = f"http://127.0.0.1:{server.port}"
        try:
            sink = os.path.join(tmp, "answer.txt")
            payload = json.dumps({"html": "<html><head><title>q</title></head><body>hub-q</body></html>",
                                  "title": "hub check", "kind": "ask", "session": "check",
                                  "sink": sink, "open": False}).encode()
            req = urllib.request.Request(f"{base}/api/post", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                reply = json.loads(resp.read())
            _check("hub/post", reply.get("ok") and reply.get("id"), f"{reply}")
            sid = reply["id"]
            with urllib.request.urlopen(f"{base}/s/{sid}/", timeout=5) as resp:
                _check("hub/page-served", b"hub-q" in resp.read())
            req = urllib.request.Request(f"{base}/s/{sid}/selection", data=b"picked", method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                _check("hub/submit-ok", json.loads(resp.read()).get("ok") is True)
            with open(sink) as handle:
                _check("hub/sink-written", handle.read() == "picked")
            with urllib.request.urlopen(f"{base}/s/{sid}/wait", timeout=5) as resp:
                _check("hub/wait-released", json.loads(resp.read()).get("status") == "answered")
            payload = json.dumps({"html": "<html><head><title>x</title></head><body>2</body></html>",
                                  "title": "stale", "kind": "ask", "session": "check",
                                  "open": False}).encode()
            req = urllib.request.Request(f"{base}/api/post", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                sid2 = json.loads(resp.read())["id"]
            req = urllib.request.Request(f"{base}/api/withdraw",
                                         data=json.dumps({"id": sid2, "reason": "negated in chat"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5):
                pass
            try:
                with urllib.request.urlopen(f"{base}/s/{sid2}/", timeout=5) as resp:
                    code = resp.status
            except urllib.error.HTTPError as error:
                code = error.code
            _check("hub/withdrawn-410", code == 410, f"got {code}")

            # the upload lane: raw bytes in -> absolute path back -> the file is on disk,
            # byte-identical; a resolved surface refuses further uploads (409)
            asset_dir = os.path.join(tmp, "assets")
            os.makedirs(asset_dir, exist_ok=True)
            with open(os.path.join(asset_dir, "tone.m4a"), "wb") as handle:
                handle.write(b"m4a-bytes")
            payload = json.dumps({"html": "<html><head><title>u</title></head><body>3</body></html>",
                                  "title": "upload check", "kind": "ask", "session": "check",
                                  "asset_dir": asset_dir, "open": False}).encode()
            req = urllib.request.Request(f"{base}/api/post", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                sid3 = json.loads(resp.read())["id"]
            req = urllib.request.Request(f"{base}/s/{sid3}/upload?name=probe.txt",
                                         data=b"upload-bytes", method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                reply = json.loads(resp.read())
            _check("hub/upload-ok", reply.get("ok") and reply.get("name") == "probe.txt", f"{reply}")
            with open(reply["path"], "rb") as handle:
                _check("hub/upload-on-disk", handle.read() == b"upload-bytes", reply["path"])
            # an empty body is refused loud (400), never written
            try:
                req = urllib.request.Request(f"{base}/s/{sid3}/upload?name=empty.txt",
                                             data=b"", method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    code = resp.status
            except urllib.error.HTTPError as error:
                code = error.code
            _check("hub/upload-empty-400", code == 400, f"got {code}")
            # a duplicate filename allocates a numbered sibling; the first file stays intact
            req = urllib.request.Request(f"{base}/s/{sid3}/upload?name=probe.txt",
                                         data=b"second-bytes", method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                second = json.loads(resp.read())
            _check("hub/upload-dedup-name", second.get("name") == "probe-1.txt", f"{second}")
            with open(reply["path"], "rb") as handle:
                _check("hub/upload-first-intact", handle.read() == b"upload-bytes")
            with open(second["path"], "rb") as handle:
                _check("hub/upload-second-bytes", handle.read() == b"second-bytes")
            # a hostile filename is sanitized to a basename inside the surface's in/ dir
            req = urllib.request.Request(f"{base}/s/{sid3}/upload?name=" + urllib.parse.quote("../../escape.txt"),
                                         data=b"contained", method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                hostile = json.loads(resp.read())
            in_dir = os.path.join(state, "surfaces", sid3, "in")
            _check("hub/upload-name-sanitized",
                   os.path.dirname(hostile["path"]) == in_dir and ".." not in hostile["name"],
                   f"{hostile}")
            # the new media MIME coverage: an .m4a asset serves as audio/mp4
            with urllib.request.urlopen(f"{base}/s/{sid3}/a/tone.m4a", timeout=5) as resp:
                _check("hub/asset-m4a-mime", resp.headers.get("Content-Type") == "audio/mp4",
                       f"got {resp.headers.get('Content-Type')}")
            # a page's OWN relative ref must resolve too: the renderer stages media under
            # assets/ and the page says src="assets/x", so /s/<id>/assets/x serves the file
            # (the 2026-08-01 round-3 breakage: only the a/ route worked and every artifact
            # on a hub-served page 404ed)
            os.makedirs(os.path.join(asset_dir, "assets"), exist_ok=True)
            with open(os.path.join(asset_dir, "assets", "pic.png"), "wb") as handle:
                handle.write(b"png-bytes")
            with urllib.request.urlopen(f"{base}/s/{sid3}/assets/pic.png", timeout=5) as resp:
                _check("hub/asset-page-relative",
                       resp.status == 200 and resp.headers.get("Content-Type") == "image/png",
                       f"{resp.status} {resp.headers.get('Content-Type')}")
                _check("hub/asset-page-relative-bytes", resp.read() == b"png-bytes")
            req = urllib.request.Request(f"{base}/api/withdraw",
                                         data=json.dumps({"id": sid3, "reason": "check done"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5):
                pass
            try:
                req = urllib.request.Request(f"{base}/s/{sid3}/upload?name=late.txt",
                                             data=b"too late", method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    code = resp.status
            except urllib.error.HTTPError as error:
                code = error.code
            _check("hub/upload-refused-after-resolve", code == 409, f"got {code}")
        finally:
            server.stop()


def main():
    print("webui kit + session smoke:")
    _palette()
    _page()
    _content_key()
    _session()
    _canvas_cli()
    _hub()
    print("GREEN: webui kit + re-serve session server + live-canvas CLI + surface hub")


if __name__ == "__main__":
    main()
