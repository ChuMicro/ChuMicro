# Decision 0028: Deploy modes — RAM and flash

Status: `accepted`
Date: `2026-04-18`
Related: Decision 0027

## Context

Decision 0027 established the device testing infrastructure with two transport strategies per runtime: RAM-based execution for fast test iteration, and flash-based deployment for persistent code.  Both strategies were validated on hardware but the implementation only exposed the RAM path for CircuitPython and conflated mount/copy mode semantics in MicroPython.

Users need a clear `--deploy-mode ram|flash` flag to choose between:

- **RAM mode** — for running tests.  Fast, no flash wear, no persistence.
- **Flash mode** — for deploying projects or tests that require persistence.

The flash deployment path also lays groundwork for a future `chumicro-deploy` pip package that helps users deploy their own projects (not just tests) to boards.

## Decision

### Unified deploy mode flag

`test-device` accepts `--deploy-mode ram|flash` (default: `ram`).

The flag maps to runtime-specific transport modes:

| `--deploy-mode` | MicroPython | CircuitPython |
|-----------------|-------------|---------------|
| `ram` | `mount` (stream from host) | `inline` (raw REPL exec, no flash) |
| `flash` | `copy` (`mpremote fs cp -r`) | `usb` (copy to CIRCUITPY drive) |

The per-device `transport_mode` field in `devices.yml` remains as a device-level default.  `--deploy-mode` overrides it when specified.

### CircuitPython flash transport

`CircuitpythonTransport` gains a `mode` parameter (`"ram"` default, `"flash"`).

Flash mode in `stage()`:

1. Send `import supervisor; supervisor.runtime.autoreload = False` via raw REPL.
2. Copy staged files to the CIRCUITPY USB drive path (from `circuitpy_drive_path` config).
3. Wait for filesystem sync.

Flash mode in `execute()`:

- Files are on flash, so the bootstrap uses standard `import` statements — no class-as-module injection needed.

Flash mode in `disconnect()`:

- Re-enable autoreload via `supervisor.runtime.autoreload = True`.
- Trigger reload via `supervisor.reload()`.

### CircuitPython drive path configuration

A new optional `circuitpy_drive_path` field in `devices.yml` specifies where the CIRCUITPY USB drive is mounted on the host (e.g. `/Volumes/CIRCUITPY`).  Required for flash mode; ignored for RAM mode.

Auto-detection is deferred — explicit configuration avoids ambiguity with multiple boards.

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
- `--deploy-mode` becomes the user-facing flag; `transport_mode` remains for device-level defaults.
- Flash mode for CircuitPython requires `circuitpy_drive_path` in the device config.
- The transport API's `stage()`/`execute()`/`disconnect()` protocol remains stable — mode is an internal concern.
- The `chumicro-deploy` package and project template are recorded as future work in `open-questions.md`.

