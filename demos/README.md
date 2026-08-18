# Demos

End-to-end first-impression artifacts that show ChuMicro libraries
working as a system, not just as code. Run a demo and the full round
trip lands on your screen in one command: no curl in another terminal,
no IP discovery, no setup beyond `secrets.toml` and a registered board
(`chumicro-workspace add-device`). Two exceptions: the mqtt demos need
`mosquitto` on PATH (`brew install mosquitto`), and
`sockets_tls_roundtrip` needs `pip install cryptography`. One demo,
[`laptop_roundtrip`](laptop_roundtrip/), needs no board at all.

## What demos are (and aren't)

A demo is a self-contained directory under `demos/<name>/` with:

- `app.py`, the on-device code (deployed to a registered board,
  named to match the `ChuMicro-Workbench-Template/projects/<name>/app.py`
  convention so demos read like real projects).
- `driver.py`, the host-side script that deploys `app.py`, drives it,
  prints the round trip, and exits. Run with
  `.venv/bin/python demos/<name>/driver.py`.
- `README.md`: what this demo shows, how to run it, what to expect.

`laptop_roundtrip` is the exception to the pair: its `app.py` runs
entirely on the host (`python app.py` from its directory), so there is
no `driver.py` and no board in the loop. Its README explains the split.

**Demos break the examples' import rule on purpose.** A demo's
`driver.py` is allowed to reach into `workbench/`,
`chumicro_pytest_device.fixtures.*`, internal helpers, anywhere in
the mono-repo. Demos are mono-repo native artifacts that demonstrate
how the pieces fit together; constraining them to "library imports
only" would defeat the point.

**Demos are not published.** They live in this repo, are run from a
clone, and are never packaged or pushed to PyPI. The audience is
someone evaluating the ecosystem, or a contributor who wants to see a
library working end-to-end against real hardware.

## What's the difference between a demo and an example?

| | Example | Demo |
|---|---|---|
| Purpose | Read this to learn a library | Run this to be impressed |
| Location | `libraries/<lib>/examples/` | `demos/<name>/` (root) |
| Spans libraries | No, one library at a time | Often: wifi + http_server + msgpack ... |
| Imports allowed | Just the library being demoed | Anything in the mono-repo |
| Runs on | Board (host just tails serial) | Board + host (`laptop_roundtrip`: host only) |
| Shipped to PyPI | Yes, with the library | No, mono-repo only |

## When to add a demo vs. just enhance an example docstring

If the library is **client-side** and the user can replicate the
other end on their laptop with a one-liner (`curl ...`,
`python -m http.server`, `nc -ul ...`), a docstring "Try it locally"
section in the example file is usually enough.

If the library is **server-side** (`http_server`,
`websockets`-server) or **needs non-trivial host infrastructure**
(an MQTT broker, a websocket server, an orchestrated multi-step
handshake), a demo carries its weight: the demo's `driver.py` packs
the discovery, the setup, and the assertions so the user doesn't
have to compose any of it.

## Running a demo

```bash
.venv/bin/python demos/<name>/driver.py

# laptop_roundtrip has no driver.py; run its app directly:
cd demos/laptop_roundtrip && ../../.venv/bin/python app.py
```

Each demo's `driver.py --help` documents its options (which device
to target, timeouts, etc.). Most demos pick a sensible default
device from `devices.yml`.

## Adding a demo

1. Create `demos/<name>/` with `README.md`, `app.py`,
   `driver.py`.
2. Write `app.py` for someone learning, because that is who reads
   it. Four rules, all of them things a reader would otherwise trip
   over:

   **The docstring says what the board does and what you will see.**
   Open with the behaviour, paste the actual output, and end with
   something to try. Comparisons to sibling demos go in this
   `README.md`, not in the file a beginner opens first.

   **Only import what the demo is demonstrating.** No
   `chumicro_test_harness`, no workbench internals. Marker lines are
   plain `print` calls:

   ```python
   print(f"WIFI_OK ip={wifi.ip}")
   print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
   ```

   The host parser reads `NAME key=value` and drops the whole line if
   any value contains a space or an `=`, so hex-encode bytes and keep
   anything free-form (a URL with a query string, a message body) on
   its own indented line. Indented and lowercase lines are ignored by
   the parser, so they are free for the human.

   **The demo does not exit.** It ends the way every board program
   ends, which is that it doesn't:

   ```python
   while True:
       now_ms = runner.tick()
       runner.wait(now_ms)
   ```

   Print `DEMO_COMPLETE` at the point the work is actually finished,
   then let the loop carry on. No board-side deadline and no
   `SystemExit`: the driver already has timeouts on every `wait_for`,
   and `session.shutdown()` is safe while the board is still running.
   A demo that self-terminates teaches the one thing about boards that
   is not true.

   **No scaffolding beyond that.** No timeout constants, no completion
   flags, no state dicts. If a demo needs something to prove the loop
   is shared, a one-second heartbeat is enough:

   ```python
   def heartbeat(now_ms):
       """Runs once a second, whatever else is going on."""
       print("  ...still ticking")
   ```

3. The `driver.py` deploys and runs the on-device code via
   `chumicro_workspace.deploy_api.deploy_project`, which returns a
   session; wait on the board's marker lines with `session.wait_for(...)`
   and use whatever fixture helpers it needs from
   `chumicro_pytest_device.fixtures.*` to drive the round trip.
4. `python scripts/run.py verify-demos` parses every `.py` under
   `demos/` and fails on syntax errors or empty files; preflight
   runs it automatically.
