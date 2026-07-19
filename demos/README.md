# Demos

End-to-end first-impression artifacts that show ChuMicro libraries
working as a system, not just as code. Run a demo and the full round
trip lands on your screen in one command: no curl in another terminal,
no IP discovery, no setup beyond `secrets.toml` and a registered board
(`python scripts/run.py add-device`). One demo,
[`laptop_roundtrip`](laptop_roundtrip/), needs no board at all.

## What demos are (and aren't)

A demo is a self-contained directory under `demos/<name>/` with:

- `app.py`, the on-device code (deployed to a registered board,
  named to match the `ChuMicro-Workspace-Template/projects/<name>/app.py`
  convention so demos read like real projects).
- `driver.py`, the host-side script that deploys `app.py`, drives it,
  prints the round trip, and exits. Run with
  `python demos/<name>/driver.py`.
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
.venv/bin/python demos/<demo_name>/driver.py

# laptop_roundtrip has no driver.py; run its app directly:
cd demos/laptop_roundtrip && ../../.venv/bin/python app.py
```

Each demo's `driver.py --help` documents its options (which device
to target, timeouts, etc.). Most demos pick a sensible default
device from `devices.yml`.

## Adding a demo

1. Create `demos/<demo_name>/` with `README.md`, `app.py`,
   `driver.py`.
2. The `app.py` follows the standard board-file shape: bring wifi
   up, do the work, print marker lines for sync, exit on completion
   or deadline.
3. The `driver.py` deploys and runs the on-device code via
   `chumicro_workspace.deploy_api.deploy_project`, which returns a
   session; wait on the board's marker lines with `session.wait_for(...)`
   and use whatever fixture helpers it needs from
   `chumicro_pytest_device.fixtures.*` to drive the round trip.
4. `python scripts/run.py verify-demos` parses every `.py` under
   `demos/` and fails on syntax errors or empty files; preflight
   runs it automatically.
