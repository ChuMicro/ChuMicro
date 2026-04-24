# Decision 0028: Deploy modes — RAM and flash

Status: `accepted`
Date: `2026-04-18`
Related: Decision 0027, Decision 0029

> **Note:** See also [Decision 0029](0029-project-workspace.md) which extends the "future `chumicro-deploy` package" section with the full project-workspace scope (template repo, UID-based identity, onboarding, import-graph deploy, REPL TUI).

## Context

Decision 0027 established the device testing infrastructure with two transport strategies per runtime: RAM-based execution for fast test iteration, and flash-based deployment for persistent code.  Both strategies were validated on hardware but the implementation only exposed the RAM path for CircuitPython and conflated mount/copy mode semantics in MicroPython.

Users need a clear `--deploy-mode ram|flash` flag to choose between:

- **RAM mode** — for running tests.  Fast, no flash wear, no persistence.
- **Flash mode** — for deploying projects or tests that require persistence.

The flash deployment path also lays groundwork for a future `chumicro-deploy` pip package that helps users deploy their own projects (not just tests) to boards.

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
2. Copy staged files to the CIRCUITPY USB drive path (from `circuitpy_drive_path` config).
3. Wait for filesystem sync.

Flash mode in `execute()`:

- Files are on flash, so the bootstrap uses standard `import` statements — no class-as-module injection needed.

### Large CircuitPython RAM-mode payloads

Some functional tests inline multiple ChuMicro libraries plus the test harness and test file into the CircuitPython raw REPL. Sending that entire payload in one submission can destabilize the USB connection on lower-memory boards instead of producing a normal traceback.

To avoid that failure mode, CircuitPython RAM mode now probes live free heap from the connected board with `gc.mem_free()` after `gc.collect()`, removes comments and docstrings from staged inline library and harness source, derives a conservative per-script budget from that measurement, and splits the inline bootstrap into multiple raw-REPL chunks. The transport runs those chunks sequentially, collecting garbage between them. If a single required chunk still exceeds the measured RAM budget, the run fails early with guidance to use flash deploy mode.

Flash mode in `disconnect()`:

- Re-enable autoreload via `supervisor.runtime.autoreload = True`.
- Trigger reload via `supervisor.reload()`.

### CircuitPython drive path configuration

A new optional `circuitpy_drive_path` field in `devices.yml` specifies where the CIRCUITPY USB drive is mounted on the host (e.g. `/Volumes/CIRCUITPY`).  When omitted, `find_circuitpy_drive()` auto-detects the drive by checking common mount points on macOS (`/Volumes/CIRCUITPY`) and Linux (`/media/<user>/CIRCUITPY`, `/run/media/<user>/CIRCUITPY`).  Explicit paths take precedence and are recommended when multiple boards are connected.

### Future: `chumicro-deploy` pip package

The transport layer in `support/device_transport/` is shaped for eventual extraction into a standalone pip-installable package.  The envisioned package would:

- Deploy user projects (from any repo) to MicroPython and CircuitPython boards.
- Handle library dependency resolution from ChuMicro bundle repos.
- Optionally compile `.mpy` bytecode when mpy-cross is available.
- Provide a CLI: `chumicro-deploy flash --runtime circuitpython --port /dev/cu.usbmodem1234 ./my-project/`.

This is intentionally deferred.  The current work shapes the transport API to make extraction straightforward when the time comes.  A project template repo (`chumicro-project-template`) is a natural companion but is also deferred.

## Consequences

- `CircuitpythonTransport` gains `mode` and `circuitpy_drive_path` parameters.
- `DeviceEntry` gains a `circuitpy_drive_path` field.
- `--deploy-mode` becomes the user-facing CLI override; `deploy_mode` in `devices.yml` is the per-device default, with `defaults.deploy_mode` as the workspace-wide fallback.
- Flash mode for CircuitPython uses `circuitpy_drive_path` from device config, falling back to auto-detection via `find_circuitpy_drive()`.
- Oversized CircuitPython RAM-mode submissions are chunked using a live free-heap probe instead of static board-family metadata. If even the chunked path cannot fit, the run fails early and directs the user to flash mode.
- The transport API's `stage()`/`execute()`/`disconnect()` protocol remains stable — mode is an internal concern.
- The `chumicro-deploy` package split is handled by Decision 0032; a serial-only CircuitPython flash workflow that would remove the CIRCUITPY drive dependency remains tracked under the "drive mode toggle" entry in `plans/open-questions.md`.
