# Decision 0028: Deploy modes — RAM and flash

Status: `accepted`
Date: `2026-04-18`
Related: Decision 0027, Decision 0029

## Context

Decision 0027 established the device testing infrastructure with two transport strategies per runtime: RAM-based execution for fast test iteration, and flash-based deployment for persistent code.  Both strategies were validated on hardware but the implementation only exposed the RAM path for CircuitPython and conflated mount/copy mode semantics in MicroPython.

Users need a clear `--deploy-mode ram|flash` flag to choose between:

- **RAM mode** — for running tests.  Fast, no flash wear, no persistence.
- **Flash mode** — for deploying projects or tests that require persistence.

The flash deployment path also lays groundwork for a `chumicro-deploy` pip package that helps users deploy their own projects (not just tests) to boards — the full project-workspace scope (template repo, UID-based identity, onboarding, import-graph deploy, REPL TUI) is defined in [Decision 0029](0029-project-workspace.md), with the package split itself handled in [Decision 0032](0032-workbench-host-tools.md).

## Decision

### Unified deploy mode flag

`test-libraries-functional` accepts `--deploy-mode ram|flash` as a per-run override. When the flag is omitted, each selected device uses its own `deploy_mode` from `devices.yml`, falling back to `defaults.deploy_mode` and then `ram`.

The flag maps to runtime-specific transport modes:

| `--deploy-mode` | MicroPython | CircuitPython |
|-----------------|-------------|---------------|
| `ram` | `mount` (stream from host) | `inline` (raw REPL exec, no flash) |
| `flash` | `copy` (`mpremote fs cp -r`) | `usb` (copy to CIRCUITPY drive) |

The per-device `deploy_mode` field in `devices.yml` sets the device-level default (``"ram"`` when omitted).  Both MicroPython and CircuitPython entries support `deploy_mode`.  `--deploy-mode` on the CLI overrides it when specified.

### CircuitPython flash transport

`CircuitpythonTransport` gains a `mode` parameter (`"ram"` default, `"flash"`).

Flash mode in `stage()`:

1. Send `import supervisor; supervisor.runtime.autoreload = False` via raw REPL.
2. Copy staged files to the CIRCUITPY USB drive — resolved at deploy time by scanning mounted `CIRCUITPY*` volumes and UID-matching the connected board against each `boot_out.txt` (see "CircuitPython drive path resolution" below).
3. Wait for filesystem sync.

Flash mode in `execute()`:

- Files are on flash, so the bootstrap uses standard `import` statements — no class-as-module injection needed.

### Large CircuitPython RAM-mode payloads

Some functional tests inline multiple ChuMicro libraries plus the test harness and test file into the CircuitPython raw REPL. Sending that entire payload in one submission can destabilize the USB connection on lower-memory boards instead of producing a normal traceback.

To avoid that failure mode, CircuitPython RAM mode now probes live free heap from the connected board with `gc.mem_free()` after `gc.collect()`, removes comments and docstrings from staged inline library and harness source, derives a conservative per-script budget from that measurement, and splits the inline bootstrap into multiple raw-REPL chunks. The transport runs those chunks sequentially, collecting garbage between them. If a single required chunk still exceeds the measured RAM budget, the run fails early with guidance to use flash deploy mode.

Flash mode in `disconnect()`:

- Pure teardown: re-enter raw REPL (idempotent — the Ctrl-C×2 inside
  interrupts any code still running from a killed-mid-execute session),
  then Ctrl-B to exit raw REPL, then close the serial port.  No autoreload
  manipulation and no soft-reboot at this site — both were removed in the
  later deploy-audit pass after the ESP32-S2 USB-CDC double-reboot wedge
  surfaced.  The autoreload-off issued in `stage()` is implicitly
  restored on the production `deploy_files` path (its mid-method Ctrl-D
  resets `supervisor.runtime.autoreload` to default-on as a side effect)
  and intentionally left off on the functional-test path (the harness
  drove the raw REPL session itself; `code.py`-style reload-on-edit
  isn't relevant during or after the session).

### MicroPython flash transport

`MicropythonTransport.deploy_files` accepts a `follow: Literal["exec", "soft_reboot"]` kwarg that selects how the staged entrypoint is run + how its output is captured.  Both modes write files via `mpremote fs cp -r`; they differ only in what happens after the copy.

**`follow="exec"` (the default)** runs the entrypoint synchronously through raw REPL: `self._serial.exec_raw(script, timeout=_EXECUTE_IDLE_TIMEOUT)` where `_EXECUTE_IDLE_TIMEOUT` is the inter-byte idle timeout passed to mpremote's `follow()` → `read_until`.  Right for return-bounded scripts (test-harness `test_*.py` files): the script runs, prints, returns, and raw REPL emits the EOF (`\x04`) marker that ends `exec_raw` cleanly.  Wrong for app-code with `while True: ...` because the EOF never fires.

**`follow="soft_reboot"`** mirrors `CircuitpythonTransport`'s flash mode.  After the copy, the transport sends Ctrl-B + Ctrl-D from the persistent serial connection (with a prompt-sync wait between them — bench-tested as necessary on Pi Pico W MP because back-to-back writes raced the firmware's raw-REPL exit), lets MicroPython auto-run `/main.py`, and reads serial output via `read_until(b"\r\n>>> ")` bounded by `self.timeout` (default 10 s, matching `CircuitpythonTransport.timeout`).  The friendly-REPL `>>> ` prompt is the MP analog of CP's `Code done running.` end marker; for `while True` bodies it never appears and the read returns whatever accumulated.  `_extract_main_py_output` syncs on the `MPY: soft reboot` start marker and trims the trailing friendly-REPL banner + prompt, so callers see just user stdout.

`Deployer.deploy_diff` and `Deployer.deploy` opt into `follow="soft_reboot"` automatically when `(transport, deploy_mode, entrypoint) == (MICROPYTHON, FLASH, "/main.py")`.  Other paths (CP, MP RAM, MP flash with non-`/main.py` entrypoints) keep transport defaults — CP doesn't accept `follow` at all, and MP RAM / test-harness deploys want `follow="exec"` because their entrypoints return cleanly.  Constraint enforced inside `MicropythonTransport.deploy_files`: `follow="soft_reboot"` requires `mode="copy"` + entrypoint `/main.py` (MP's auto-run convention) and raises `MicropythonTransportError` early on either mismatch.

### CircuitPython drive path resolution

The CIRCUITPY drive is resolved at deploy time — there is no `devices.yml` field for it.  `_circuitpy_volume_candidates()` scans common mount points on macOS (`/Volumes/CIRCUITPY*`) and Linux (`/media/<user>/CIRCUITPY*`, `/run/media/<user>/CIRCUITPY*`) and returns every mounted CIRCUITPY volume.  `CircuitpythonTransport._verify_drive_for_board` probes the connected board's `microcontroller.cpu.uid` and compares it against `boot_out.txt` UID lines on each candidate, then picks the matching drive.  On multi-board hosts where macOS assigns `/Volumes/CIRCUITPY` versus `/Volumes/CIRCUITPY 1` in mount order, this is what routes each deploy to the right physical board.  Pinning a path in `devices.yml` would only be a source of staleness — the UID match already handles every multi-board scenario it could solve.

### Future: `chumicro-deploy` pip package

The transport layer is shaped for eventual extraction into a standalone pip-installable package.  Done in [Decision 0032](0032-workbench-host-tools.md): code lives in `workbench/deploy/` and ships as `chumicro-deploy`.

## Consequences

- `CircuitpythonTransport` gains a `mode` parameter.
- `--deploy-mode` becomes the user-facing CLI override; `deploy_mode` in `devices.yml` is the per-device default, with `defaults.deploy_mode` as the workspace-wide fallback.
- Flash mode for CircuitPython resolves the CIRCUITPY mount at deploy time by scanning every mounted `CIRCUITPY*` volume and UID-matching against `boot_out.txt`.
- Oversized CircuitPython RAM-mode submissions are chunked using a live free-heap probe instead of static board-family metadata. If even the chunked path cannot fit, the run fails early and directs the user to flash mode.
- The transport API's `stage()`/`execute()`/`disconnect()` protocol remains stable — mode is an internal concern.
- MicroPython flash transport supports two follow modes via the `follow` kwarg on `MicropythonTransport.deploy_files`: `"exec"` (raw-REPL `exec_raw`, for return-bounded test-harness scripts) and `"soft_reboot"` (Ctrl-B + Ctrl-D from the persistent serial connection, for `while True` app code that would never emit the raw-REPL EOF marker).  `Deployer.deploy_diff` / `Deployer.deploy` auto-route to `"soft_reboot"` for `(MP, FLASH, /main.py)` deploys; everything else stays on `"exec"`.
- The `chumicro-deploy` package split is handled by Decision 0032; a serial-only CircuitPython flash workflow that would remove the CIRCUITPY drive dependency remains tracked under the "drive mode toggle" entry in `plans/open-questions.md`.
