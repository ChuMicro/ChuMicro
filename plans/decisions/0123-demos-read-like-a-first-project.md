# Decision 0123: Demo `app.py` reads like a first project, not like a fixture

Status: `accepted`
Date: `2026-08-18`
Summary: A demo's `app.py` imports only what it demonstrates, prints its own `NAME key=value` markers, opens with a learner-facing docstring, and never exits: it ends in a plain `while True`.
Related: Decision [0122](0122-demos-and-examples-write-the-loop-out.md) (demos write the main loop out), Decision [0090](0090-deploy-strips-docstrings-and-comments.md) (device deploys strip docstrings).

## Context

`demos/` exists to be read, in practice by an Adafruit-Learn beginner learning CircuitPython, MicroPython, and their tools at the same time as ChuMicro. Every demo `app.py` had drifted toward being a host-driven fixture instead: it imported `chumicro_test_harness.markers` and called `marker("WIFI_OK", ip=wifi.ip)` where a person writes `print`, its docstring opened with "Board-side of the X demo" and cross-referenced sibling demos before saying what the board does, its module constants carried the private-name underscore, and it carried a `_DEMO_DEADLINE_MS` and a `SystemExit` so it would terminate.

That last one is the load-bearing mistake. A board program does not end, and every example a beginner has seen elsewhere is a `while True` that runs until the power goes. A demo that self-terminates teaches the one thing about boards that is not true, and the deadline that made it terminate is duplicated host-side anyway: every driver already puts a timeout on every `wait_for`.

`marker()` was not gratuitous. The host parser drops the entire line when any value contains whitespace or `=`, and a demo once lost its `ECHO_RECEIVED` marker to exactly that and burned a ten-second wait budget with no diagnostic. `marker()` made the constraint structural: it hex-encodes bytes and raises at develop time on a value that would not survive the wire.

## Decision

A demo's `app.py` is written for the person reading it, and carries nothing that exists only to serve the harness.

- **Import only what the demo demonstrates.** No `chumicro_test_harness`, no workbench internals. (`driver.py` keeps its free run of the mono-repo; that rule is unchanged.)
- **Marker lines are plain `print` calls** in the parser's `NAME key=value` shape. Bytes are hex-encoded at the call site with `payload.hex()`, which shows the reader the encoding instead of performing it for them. Anything free-form — a URL that might carry a `?a=b` query string, a received message body — goes on its own indented line, which the parser ignores by design.
- **The docstring says what the board does and what you will see**, pastes the real output, and ends with something to try. Comparisons against sibling demos move to the demo's `README.md`.
- **The demo does not exit.** It prints `DEMO_COMPLETE` at the point the work is finished and then keeps turning the same four-line loop. No board-side deadline, no `SystemExit`, no completion flag threaded through the loop. `DeployedProject.shutdown()` is documented safe while the bootstrap is still running, so the driver sees its marker and tears the transport down.
- **Module constants drop the leading underscore**, and nothing exists in the file that only the harness needs.

## Rejected

- **Keeping `marker()` for its develop-time validation** — the validation is real, and it is bought by putting a test-harness import at the top of the first file a beginner opens. The demos' values are fixed-shape (an IP, a byte count, a hex payload, a route), the one genuinely variable value was moved off the marker line, and `demos/README.md` states the constraint for anyone adding a demo.
- **A board-side deadline that exits non-zero** — the drivers' `wait_for` timeouts already fail the run and dump captured stdout. The board-side copy bought nothing and cost a constant, a `Deadline`, a branch in the loop, and a `SystemExit`.
- **Lingering for a few seconds and then exiting** — tried first, and rejected on reading: it answered "exit later" with a second deadline, a `linger` sentinel, and a nested conditional in the loop, leaving the tail harder to read than the `run_until` it replaced. Not exiting at all is both simpler and more truthful.
- **A shared `demos/_marker.py` helper** — keeps the loud-on-bad-value guarantee, but puts the thing back one indirection away from the page and adds a second file to every demo deploy.

## Consequences

- The tail of every demo is four lines and identical across all nine.
- Nine demo `app.py` files carry no harness import. `chumicro_test_harness.markers.marker` now has no caller in the workspace outside its own test: either delete it with its lazy export in `chumicro_test_harness/__init__.py`, or keep it documented for people writing their own on-device tests. Separately, `markers.py` can now join `_DEMO_UNUSED_HARNESS_MODULES` in `deploy_api.py`, which is flash back on a 256 KB board.
- `SERVICE_FAULT` is a real marker now (`service=` / `error=`) with the repr on an indented detail line, rather than an uppercase line that never parsed. It is also how a dead generator surfaces, since nothing checks `handle.error` any more.
- `http_server_roundtrip`'s driver waited on `wait_for_completion()` (the board process ending) and now waits on the `DEMO_COMPLETE` marker. `mqtt_sensor_motor`'s driver checked for a retained `"offline"` published during a graceful shutdown; with the board still running it checks that availability still reads `"online"`, which is the more honest assertion — `"offline"` is the broker's job via the Last Will if the board ever really drops.
