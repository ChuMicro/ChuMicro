# Workstream: MQTT negative-testing suite

Status: **proposed.**  Surfaced 2026-05-23 during the Pi Pico W CP TLS bake investigation.  Pairs with [`chumicro-mqtt-runner-cooperative-tick-convergence.md`](chumicro-mqtt-runner-cooperative-tick-convergence.md) — that workstream changes the library; this one validates the change (and the current code) against edge cases.

## Problem

The 5- and 9-minute happy-path bakes pass cleanly across the board matrix.  Real bugs live in the negative paths — broker drops, lost packets, retry storms, network outages — and those paths have never been deliberately exercised against chumicro_mqtt + chumicro_runner.  The bake investigation surfaced *latent* defects (recv-into-zero swallowed, deadline checks downstream of I/O, no POLLERR/HUP) that the happy path can't reveal.  Negative testing is the discovery mechanism.

## Test inventory

Each row is a separate bake variant.  All measured for: heap drift, fragmentation drift, message delivery, state transitions, recovery semantics.  Run on Pi Pico W CP custom firmware (10.2.0-dirty, the hardest target) and Pi Pico W MP (the comparison surface); add Lolin S2 boards once the convergence workstream lands.

| Test | What it provokes | Expected behaviour | What a failure means |
|---|---|---|---|
| **Broker hard-kill mid-bake** — `pkill -9 mosquitto` ~2 min in, restart 30s later | TCP RST or silent socket death | board detects within ack_timeout, transitions to `FAILED`, self-heal succeeds when broker returns; in_flight drains correctly | hung connection, leaked in_flight entries, no self-heal |
| **Broker graceful disconnect** — `mosquitto_ctrl ... disconnect <client_id>` | clean MQTT DISCONNECT from broker, then TCP FIN | board sees `recv_into() == 0`, transitions to `FAILED`, self-heal succeeds | recv-zero swallowed silently (already-known defect; covered by convergence workstream) |
| **NAT-style silent drop** — `sudo pfctl -e -f` block rule on broker port from board IP, hold 60s, release | TCP packets dropped without RST/FIN; board sees no data | board hits ack_timeout, transitions to `FAILED`, self-heal succeeds when block lifts | timeout never fires, deadline path doesn't fire because recv blocks first (convergence workstream concern) |
| **Wifi router power cycle** — physically toggle router off ~30s, on | board's wifi association drops; sockets become unwritable | board detects via send-error or ack-timeout; self-heal reconnects wifi if `chumicro-wifi` is wired in, then reconnects MQTT | unclear ownership: is wifi recovery a chumicro-wifi responsibility or chumicro-mqtt's?  Decision needed before running. |
| **QoS 1 retry path — broker drops PUBACK** — broker config force-suppress single PUBACK | client retransmits with DUP bit, eventually receives PUBACK or fails retry-limit | retry counter increments, in_flight entry's deadline rearms, eventual PUBACK clears the entry | retry never fires, in_flight leaks forever, heap grows |
| **QoS 1 lost PUBLISH — board side drops outbound** — inject error before TCP send | publish enqueued but never sent | deadline expires, retry attempts up to `publish_retry_max`, finally transitions to `FAILED` with last_error | retry counter wrong, transitions don't happen |
| **High-rate sustained burst** — 50 Hz publish for 60s, return to 1 Hz | tests recv-budget exhaustion, tx-queue saturation, partial-send path | rate sustained without backpressure errors; if `MQTTBackpressureError` raised, caller can retry; no leak; heap stable | tx_queue grows unboundedly, partial-send path leaks state |
| **Large-payload bursts** — single 4 KB PUBLISH every 10s for 5 min | exercises recv-buffer chunking + partial-recv path | each large packet decoded correctly, no in_flight leak, heap stable | partial-recv state lost between ticks, decoder buffer overflow |
| **Long-duration baseline** — 30-min and 2-hour happy-path bake on CP custom firmware | sub-detection-threshold leaks | heap drift below noise across both durations | slow leak compounds; rate × time crosses detection threshold |

## Where wifi-router cycle belongs

The wifi-cycle test ambiguously straddles `chumicro-mqtt` and `chumicro-wifi`.  Open question for the resumer: does chumicro-mqtt own "I see the underlying socket fail, retry"?  Or does chumicro-wifi own "the radio's down, services should pause"?  Decision belongs in an ADR before the test runs.  Leaving this here as the surfacing trigger; route the actual test to `chumicro-wifi`'s test inventory once the boundary is decided.

## Harness reuse

The 2026-05-23 bake harness (`projects/mqtt_bake_diag*` in workspace-template, gitignored, local-only) is the right starting point — it already covers:

- per-10-sec window stats (iters, max_tick_ms, max_wait_ms, max_pub_ms)
- 30-sec heap checkpoints
- bidirectional 1 Hz QoS 1 traffic with sequence-gap detection
- `chumicro_timing.ticks` throughout (post-fix)
- pluggable `VARIANT` constant so multiple bakes coexist on the broker without crosstalk

Add per-test toggles (broker-kill, NAT-drop, etc.) by extending the harness rather than building separate apps.  The Mac driver (`.scratch/mqtt_bake_mac_driver.py`) already takes `--variant` and `--client-suffix` flags.

## What is not in scope

- Building chumicro-wifi's own negative test suite.  Reference here; that work belongs in chumicro-wifi.
- Cross-runtime negative testing for `chumicro_sockets` / `chumicro_runner` directly.  Those happen via the MQTT layer here; they get their own targeted tests later if signal warrants.
