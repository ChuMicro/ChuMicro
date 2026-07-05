# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now


## Next


- [ ] **MQTT negative-testing suite — A-series hardware-validated on 3 of 4 bench boards.**  [workstreams/mqtt-negative-testing-suite.md](workstreams/mqtt-negative-testing-suite.md) — A1–A5 RAN/PASS 2026-07-04; A7 + A9 RAN/PASS 2026-07-05 (proxy gained `delay`/`freeze-existing`/half-open-hold; literal §3.1.4 ghost eviction observed on the wire); B2 router-cycle RAN/PASS 2026-07-05; compressed re-runs (A1+A3) PASS on lolin-s2-mp, pi-pico-w-cp, and the swapped s2-cp board 2026-07-05 — all four bench positions now carry hardware A-series validation.  Remaining: only the B2 open observation (wifi-down publish path dropped 3 queued messages — needs an instrumented run with console capture).
- [ ] **Device-matrix reliability: S3 pair + picos + drive-less CP transport (user call 2026-07-05).**  [workstreams/device-matrix-reliability.md](workstreams/device-matrix-reliability.md) — spike PROVED the MP raw-REPL file-write path works on CP-without-a-drive (measured on tinypico-cp); phases: serial-mode CP transport, feathers3-cp `WifiService` bring-up defect, many-volume drive-resolution hardening, first-association grace.
- [ ] **Re-evaluate Decision 0041 §8 — CP-rp2 TLS server ban — after CircuitPython 10.3.0 ships.**  Checked 2026-07-04: [adafruit/circuitpython#10339](https://github.com/adafruit/circuitpython/issues/10339) still open, milestone 10.3.0, latest release 10.3.0-alpha.3 (2026-06-24); bench pins 10.2.0.  Installing an alpha now was considered and skipped (user + agent call 2026-07-04): the fix hasn't landed in the alphas either, so an early flash would re-measure a known-unfixed substrate — the real gate is #10339 closing, not the release number.  When it does: re-bench `listen_tls` on Pico W CP; if the ban lifts, drop the platform check + update 0041 §8 + the `docs/guide.md` runtime-support table.
- [ ] **CI infrastructure workstream (unscoped — fires when CI is re-enabled).**  [workstreams/archive/audit-remediation-and-drift-mechanization.md](workstreams/archive/audit-remediation-and-drift-mechanization.md)
- [ ] **usage-path lens: contract-aware tracing.**  Replace name-grep with LSP find-references (retires `GENERIC_NAME_FILE_CAP = 15` — still 15 as of 2026-07-04 — which makes `tick`/`handle`/`run` untraceable), and prompt the judges toward risk-sampled contract-edge scenarios rather than enumerating every implementation of a generic name.  Deferred sub-idea: a POLICY_FACTS seed still needs a rethink — ADRs carry no structured invariant field to pre-populate from.
- [ ] **audit-code + audit-branch pipeline continuity.**  [workstreams/audit-pipeline-continuity.md](workstreams/audit-pipeline-continuity.md)
