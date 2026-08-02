#!/usr/bin/env python3
"""Put a rendered decision page in front of the human and loop Submit back to the session.

Default transport: the surface hub (surfaces/hub.py). The page is posted as a surface on the
repo's ONE hub, which owns the ONE browser tab: no per-question server, no new tab per
round, no port fights between concurrent sessions. This command then blocks until the
surface resolves, so the process completing is still the submit signal:

    SERVING <surface url>                       on post
    SELECTION RECEIVED -> <dir>/selection.txt   then exit 0    (answered)
    PICKER WITHDRAWN (no selection)             then exit 3    (this session moved on)
    PICKER EXPIRED (no selection)               then exit 4    (ttl or --timeout hit)
    HUB UNREACHABLE ...                         then exit 5

When the conversation negates a pending question, withdraw it instead of abandoning it:
`python3 -m surfaces.hub withdraw <id>` (the ASKED line names the id), or re-ask with
`--supersede` so the replacement retires the original in place. `--tag` groups a
session's rounds; re-asking with the same tag plus `--supersede` swaps the round the
human sees instead of stacking a second one.

`--oneshot` keeps the legacy transport (a private one-shot server and its own tab) for a
host with no hub or a flow that truly wants an isolated page; the stdout contract there
is unchanged (SERVING / SELECTION RECEIVED / PICKER CLOSED).

A stale page re-renders once before serving: when <dir>/spec.json (or the renderer) is
newer than picker.html, the page is rebuilt so the human never decides on an old render.

Usage: serve_picker.py <dir> [<page>] [--tag TAG] [--supersede] [--timeout SECS] [--oneshot]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo root, for the shared surfaces toolkit

RENDERER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_picker.py")


def rerender_if_stale(directory, page):
    spec_path = os.path.join(directory, "spec.json")
    page_path = os.path.join(directory, page)
    if not os.path.exists(spec_path):
        return
    try:
        page_mtime = os.path.getmtime(page_path) if os.path.exists(page_path) else 0
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
            print(f"RENDER FAILED (serving what exists): {tail}", flush=True)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description="serve a decision page and loop Submit back")
    parser.add_argument("directory")
    parser.add_argument("page", nargs="?", default="picker.html")
    parser.add_argument("--tag", default="picker", help="groups this session's rounds on the hub")
    parser.add_argument("--supersede", action="store_true",
                        help="withdraw my older pending surfaces with the same tag first")
    parser.add_argument("--timeout", type=float, default=None, help="seconds before giving up (exit 4)")
    parser.add_argument("--oneshot", action="store_true",
                        help="legacy transport: a private one-shot server and its own tab")
    args = parser.parse_args()

    directory = os.path.abspath(args.directory)
    rerender_if_stale(directory, args.page)
    page_path = os.path.join(directory, args.page)
    if not os.path.exists(page_path):
        print(f"refusing to serve: {page_path} does not exist", flush=True)
        raise SystemExit(2)
    sink = os.path.join(directory, "selection.txt")

    if args.oneshot:
        from surfaces.server import serve_oneshot
        serve_oneshot(directory, args.page, post_path="/selection", sink_name="selection.txt",
                      env_no_open="PICKER_NO_OPEN", label_received="SELECTION RECEIVED",
                      label_closed="PICKER CLOSED: selection saved to",
                      on_get=lambda: rerender_if_stale(directory, args.page))
        return

    from surfaces import hub
    title = "decision: " + os.path.basename(directory)
    spec_path = os.path.join(directory, "spec.json")
    if os.path.exists(spec_path):
        try:
            with open(spec_path) as handle:
                title = json.load(handle).get("title", title)
        except (OSError, ValueError):
            pass
    port, sid, url = hub.post(page_path, title=title, kind="ask", tag=args.tag, sink=sink,
                              assets=directory,
                              supersede_tag=args.tag if args.supersede else "")
    print(f"ASKED {sid}", flush=True)
    print(f"SERVING {url}", flush=True)
    status = hub.wait(port, sid, timeout=args.timeout)
    if status == "answered":
        print(f"SELECTION RECEIVED -> {sink}", flush=True)
        print(f"PICKER CLOSED: selection saved to {sink}", flush=True)
        sys.exit(0)
    if status == "withdrawn":
        print("PICKER WITHDRAWN (no selection)", flush=True)
        sys.exit(3)
    if status in ("expired", "timeout"):
        print("PICKER EXPIRED (no selection)", flush=True)
        sys.exit(4)
    print(f"HUB UNREACHABLE; if the human submitted, the blob is at {sink}", flush=True)
    sys.exit(5)


if __name__ == "__main__":
    main()
