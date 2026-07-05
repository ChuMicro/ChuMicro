# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now


## Next


- [ ] **Device-matrix reliability (user call 2026-07-05).**  [workstreams/device-matrix-reliability.md](workstreams/device-matrix-reliability.md) — phases 1+2 SHIPPED same day (serial-mode CP transport hardware-proven on tinypico-cp; wifi 0.7.1 station-clear fix validated on tinys3-cp, demo sweep green).  Open: tinypico-cp CP-runtime corruption discriminator (swap the TinyPICO pair's runtimes), phase 3 many-volume drive-resolution hardening, phase 4 first-association grace, phase 5 `wifi.tx_power_dbm` knob (UM P4 mitigation), tinys3-cp on RF watch (P4-family, RSSI −82).
- [ ] **Re-evaluate Decision 0041 §8 — CP-rp2 TLS server ban — after CircuitPython 10.3.0 ships.**  Checked 2026-07-04: [adafruit/circuitpython#10339](https://github.com/adafruit/circuitpython/issues/10339) still open, milestone 10.3.0, latest release 10.3.0-alpha.3 (2026-06-24); bench pins 10.2.0.  Installing an alpha now was considered and skipped (user + agent call 2026-07-04): the fix hasn't landed in the alphas either, so an early flash would re-measure a known-unfixed substrate — the real gate is #10339 closing, not the release number.  When it does: re-bench `listen_tls` on Pico W CP; if the ban lifts, drop the platform check + update 0041 §8 + the `docs/guide.md` runtime-support table.
- [ ] **CI infrastructure workstream (unscoped — fires when CI is re-enabled).**  [workstreams/archive/audit-remediation-and-drift-mechanization.md](workstreams/archive/audit-remediation-and-drift-mechanization.md)
- [ ] **Library size cut — structural −40% on the heavy trio (user calls 2026-07-05).**  [workstreams/library-size-cut.md](workstreams/library-size-cut.md) — baseline measured (fleet import = 72% of a Pico W's heap; mqtt ≈ 9× umqtt.simple); size gate + audit-lens inversion landing now; campaign queued deliberately BEHIND CI stand-up so it runs protected.
