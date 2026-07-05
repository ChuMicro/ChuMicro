# Workstream: device-matrix reliability — S3 pair, picos, drive-less CP transport

Status: **active.**  Opened 2026-07-05 (user call, same day as the 4-board bench expansion): "get both s3's working and the picos reliably, including the infra changes needed for circuitpython to work without a circuitpy drive."

## Goal

Every board on the bench deploys and sweeps green without hand-holding: the FeatherS3 pair (MP + CP), both picos, and a CircuitPython deploy path that does not require a mounted CIRCUITPY drive — which unblocks tinypico-cp (classic ESP32, no native USB, no drive possible) and removes the multi-volume UID-matching fragility on a bench that now mounts three CIRCUITPY drives at once.

## The load-bearing spike (2026-07-05, measured)

The user asked whether drive-less CP means a large new transport or whether the MP paths can be leveraged.  **Measured answer: the MP mechanics transfer.**  On the real tinypico-cp (CP 10.2.0 over a CP2104 serial bridge, no MSC anywhere), stock `mpremote exec` performed a file write, readback, and delete against `/`:

- CircuitPython implements the same raw REPL protocol the MP transport already speaks.
- On boards without native USB there is no USB host owning the filesystem, so the VM can write it freely — the exact property the MP transport's file-push depends on.

So phase 1 is a serial-mode CP transport that reuses the MP transport's raw-REPL file-write path, not a new subsystem.

## Phases

1. **Serial-mode CP transport (drive-less).**  Reuse `micropython_transport`'s raw-REPL file-write mechanics behind the CP transport interface.  CP-specific handling, all observed on-bench 2026-07-05: safe-mode detection (a board in safe mode gives a REPL but runs nothing — probe `supervisor.runtime.safe_mode_reason` and surface it instead of timing out), status-bar OSC escape sequences polluting console reads, soft-reboot semantics (raw-REPL soft reset does not run `code.py`; exiting to friendly REPL + ctrl-D does), and autoreload interplay during multi-file pushes.  Transport selection: probe-driven (no MSC → serial mode) with a devices.yml override.  First target: tinypico-cp (currently parked in devices.yml) — un-park it when this lands.
2. **feathers3-cp `WifiService` bring-up defect.**  Deploys fine; raw `wifi.radio.connect` joins the bench SSID in seconds from a clean REPL; the `sockets_runner_connector` demo never reaches `WIFI_OK` in 45 s (twice, post-calibration; the MP sibling passes in 23 s).  Suspect the CP adapter's connect path on ESP32-S3.  Needs console-captured bring-up on the board.
3. **Pico reliability hardening.**  Both picos are green today; the fragility class to retire is drive *resolution* on a many-volume bench (UID mismatch errors when several CIRCUITPY drives mount, observed during the 2026-07-05 sweep).  Phase 1's serial mode is also the escape hatch here: native-USB boards keep the drive path as primary, but a serial fallback needs the boot.py `storage.remount()` / `storage.disable_usb_drive()` handshake — deliberately phase-3 (optional) because it touches what ships on every board.
4. **First-association grace.**  A freshly-erased ESP32 does RF calibration on its first wifi join and blows the demo driver's 45 s marker budget once, then passes warm (measured on both new boards).  Either warm the join during `add-device`, or give first-run sweeps a longer budget.

## Bench notes riding this workstream

- 2026-07-05: bench grew tinypico-mp, tinypico-cp (parked), feathers3-mp (swept green), feathers3-cp (phase 2 defect).  MP boards flashed 1.28.0 (above the v1.27.0 baseline, permitted); CP boards 10.2.0.
- s2-cp board swapped by user 2026-07-05 after five wedges (user suspects the board, not the cable); replacement (uid 84722E749003, CP 10.2.0-rc.0 — reflash to release 10.2.0 when convenient) arrived with a corrupted-FAT deploy failure; `storage.erase_filesystem()` run; board pending a post-erase reset as of this writing.  A clean A1+A3 re-run on it over the same cable settles cable-vs-board.
