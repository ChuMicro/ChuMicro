#!/usr/bin/env python3
"""Serve a rendered decision page over localhost and loop its Submit button back to the session.

A page from render_picker.py carries a selection bar whose blob the human can always
copy and paste back into the session. Served over http, the same bar also shows a
**Submit to session** button: it POSTs the blob here, and this server writes it to
<dir>/selection.txt, prints one `SELECTION RECEIVED -> <path>` line, and **shuts down**,
since a picker session is one submission. Run it in the background; the process *completing*
is itself the submit signal (read selection.txt then), so no separate stdout watch is
needed. Off-server, Copy/paste is the no-server fallback. The server is transport only:
it never parses or applies a selection.

Binds 127.0.0.1 on a free port. Tries to auto-open the page unless PICKER_NO_OPEN is
set, a convenience for a human running this directly. An orchestrating session sets
PICKER_NO_OPEN=1 and runs `open <url>` on the printed SERVING line itself: from a
sandboxed background process the auto-open either fails silently or lands late as a
duplicate tab, so the session must be the only opener.

A refresh always shows the current spec: on each GET of the page, when <dir>/spec.json
or render_picker.py is newer than the rendered page, the server re-renders before
serving and prints one `RERENDERED <path>` line.

Usage: serve_picker.py <dir> [<page>]      (default page: picker.html)
Stdout: `SERVING <url>` once on start, `RERENDERED <path>` per stale-refresh, then on
the (single) submit `SELECTION RECEIVED -> <path>` and `PICKER CLOSED …`, then exit.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo root, for the shared webui toolkit
from webui.server import serve_oneshot

RENDERER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_picker.py")


def main():
    directory = os.path.abspath(sys.argv[1])
    page = sys.argv[2] if len(sys.argv) > 2 else "picker.html"
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

    # the picker's surface of the shared one-shot server; on_get re-renders a stale page
    serve_oneshot(directory, page, post_path="/selection", sink_name="selection.txt",
                  env_no_open="PICKER_NO_OPEN", label_received="SELECTION RECEIVED",
                  label_closed="PICKER CLOSED: selection saved to", on_get=rerender_if_stale)


if __name__ == "__main__":
    main()
