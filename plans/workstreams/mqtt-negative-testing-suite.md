# Workstream: MQTT negative-testing suite

Status: **in progress.**  Surfaced 2026-05-23 during the Pi Pico W CP TLS bake investigation; inventory expanded 2026-05-23 from a 9-row table to a structured taxonomy.  Pairs with [`chumicro-mqtt-runner-cooperative-tick-convergence.md`](chumicro-mqtt-runner-cooperative-tick-convergence.md) — that workstream changes the library; this one validates the change (and the current code) against edge cases.

2026-07-04: the A-series (and B1) no longer need root.  The original design leaned on host firewall / traffic-shaping control (`pfctl`, `tc netem`), which needs `sudo` the bake host does not have.  It now runs through a controllable TCP proxy the board dials **instead of** the broker — `scripts/mqtt_negative_proxy.py` — with a load driver, `scripts/mqtt_qos1_flood.py`.  A1 (hard-kill) and A2 (graceful-TERM) ran on hardware 2026-07-04 against mqtt 0.23.0 (Pico W MP, convergence bake rows); the rest are host-smoke-validated or hardware-queued per the [execution table](#a-series-execution-the-root-free-tcp-proxy-harness-2026-07-04) below.

## Problem

The 5- and 9-minute happy-path bakes pass cleanly across the board matrix.  Real bugs live in the negative paths — broker drops, lost packets, retry storms, network outages, session-state surprises — and those paths have never been deliberately exercised against chumicro_mqtt + chumicro_runner.  The bake investigation surfaced *latent* defects (recv-into-zero swallowed, deadline checks downstream of I/O, no POLLERR/HUP) that the happy path can't reveal.  Negative testing is the discovery mechanism.

## Coverage matrix

Categories are grouped by where the failure originates: broker, network, TLS, client, baseline.  Each row is a separate bake variant.  All measured for: heap drift, fragmentation drift, message delivery, state transitions, recovery semantics.  Run on Pi Pico W CP custom firmware (10.2.0-dirty, the hardest target) and Pi Pico W MP (the comparison surface); add Lolin S2 boards once the convergence workstream lands.

### A. Broker-side failures

What the broker does wrong, with the network up and the client healthy.

| ID | Test | What it provokes | Expected | Failure means |
|---|---|---|---|---|
| A1 | **Broker hard-kill + restart** — `pkill -9 mosquitto` ~2 min in, restart 30s later | TCP RST or silent socket death | board detects within ack_timeout, transitions to `FAILED`, self-heal succeeds when broker returns; in_flight drains correctly | hung connection, leaked in_flight entries, no self-heal |
| A2 | **Broker graceful disconnect** — `mosquitto_ctrl ... disconnect <client_id>` | clean MQTT DISCONNECT from broker, then TCP FIN | board sees `recv_into() == 0`, transitions to `FAILED`, self-heal succeeds | recv-zero swallowed silently (defect closed 2026-05-23 by commit bb702f64; keep as regression guard) |
| A3 | **Broker drops a single PUBACK** — broker config force-suppress one PUBACK | client retransmits with DUP bit, eventually receives PUBACK or fails retry-limit | retry counter increments, in_flight deadline rearms, eventual PUBACK clears entry | retry never fires, in_flight leaks forever, heap grows |
| A4 | **Long broker outage** — broker down 10 minutes, restart while board is still publishing | retry-storm bound + memory growth during extended FAILED | board self-heal back-off (or fixed retry cadence) doesn't grow heap; in_flight either bounded or shed cleanly; no socket-factory thrash | self-heal hammers DNS / TCP at full tick rate; heap balloons; DNS resolver state corrupts |
| A5 | **Broker restart with `clean_session=False`** — broker dies with QoS 1 publishes in flight, restarts with persistent-session storage intact | session resumption: broker remembers the subscription set; client redelivers in-flight with DUP | session-present flag honoured on CONNACK; in-flight publishes redelivered with DUP=1; broker doesn't double-deliver retained messages | DUP not set on retry; retained messages double-delivered; subscriptions silently lost |
| A6 | **Broker FIN mid-publish** — broker disconnects while board is mid-`_drain_tx_queue` (partial send in flight) | partial-send state preserved or cleanly discarded on reconnect | `_partial_send` either replays on the new connection or is dropped; no orphaned bytes on the wire after FIN; next connect doesn't reuse `_partial_send` from the dead socket | `_partial_send = (packet, offset)` from dead connection sent on the new socket; broker sees garbage prefix and resets |
| A7 | **Stale `client_id` collision** — broker holds a half-open TCP from a prior session (broker hadn't yet detected the dead client), board reconnects with same `client_id` before the half-open dies | broker MUST_DISCONNECT_EXISTING_CLIENT per spec § 3.1.4 | first connect attempt either succeeds (broker evicts the ghost) or fails with reason code; either way, board eventually reaches CONNECTED with no orphaned state | board treats the FAILED CONNACK as terminal; or the ghost session's session-present flag confuses session resumption |
| A8 | **Subscription survival across reconnect** — board subscribes to `bake/+/cmd`, broker restarts, board self-heals | subscription contract on reconnect | with `clean_session=True`, board re-issues SUBSCRIBE in its connect path; with `clean_session=False`, broker remembers and replays retained messages; in either case, inbound traffic resumes | re-subscribe never fires; inbound is dead silently after self-heal |
| A9 | **Slow broker** — broker reachable but ack_timeout-tunable latency on the wire (real `tc netem delay 4s` on a Linux broker host, or a future `delay <ms>` command on `mqtt_negative_proxy.py` — the current blackhole/drop-puback surface can only *drop*, not *delay*, so it cannot model this one) | ack-timeout tuning + spurious-failure rate | publishes that take 4s for PUBACK don't false-positive into retry; tune `ack_timeout_seconds` accordingly | retry storm at ack-timeout boundary; client mistakes slow broker for dead broker |

### A-series execution: the root-free TCP proxy harness (2026-07-04)

The A-series was drafted around host firewall / traffic-shaping control (`pfctl`, `tc netem`) that needs root — unavailable on the bake host.  It now runs through a controllable TCP proxy the board dials **instead of** the broker: `scripts/mqtt_negative_proxy.py` (single-file, stdlib, CPython 3.11+).  Point the board's `broker_host` / `broker_port` at the proxy's listen port; the proxy forwards the board↔broker byte streams and exposes a line-oriented **TCP control port** for on-demand fault injection:

- `blackhole on|off` — receive-and-discard BOTH directions while keeping the sockets open (the NAT-silent-drop; replaces the B1 `pfctl` block).
- `drop-puback on|off` — forward everything except broker→client PUBACK frames.  Parses each frame's fixed-header type nibble + remaining-length varint to stay frame-aligned mid-stream (the A3 mechanism).
- `kill` — RST (SO_LINGER 0) both sockets of every active connection (the A1 abrupt death).
- `stat` / `reset-stats` — bytes + frames forwarded per direction, connection counts.

Reconnects are transparent: a self-healing client that abandons a dead socket and re-dials is accepted as a fresh connection with its own frame filter, so no A-scenario has to special-case recovery.  Load is generated by `scripts/mqtt_qos1_flood.py` — a stdlib MQTT 3.1.1 QoS-1 publisher holding one persistent connection at a configurable rate / size / count / topic, counting the returning PUBACKs so the acked-vs-sent gap is the headline signal (chosen over shelling out to `mosquitto_pub`, which either reconnects per message or hides the ack stream).

**Host smoke (2026-07-04, mosquitto 2.1.2, `listener 1883` + `allow_anonymous true`):** normal flood 20 sent / 20 acked / 20 delivered; `drop-puback on` → 15 sent / **0 acked** / 15 delivered (`pubacks_dropped=15` — publishes through, acks eaten); `blackhole on` → subscriber stream stalled with `conns_active=1` (socket open), resumed on `off`; `kill` → RST, subscriber self-healed into a fresh proxy connection one tick later.

**Expected client behavior (chumicro_mqtt 0.23.0)** is common to every A-row below: broker-death detection within one tick (recv-zero / RST / POLLERR on the connector socket); transition to `FAILED`; **paced** self-heal — exponential backoff 1→2→4→8→16→…→60 s cap (int tick math, mqtt 0.18.0) surfaced through `next_deadline` so `Runner.wait` parks on the retry instead of spinning; each attempt arms a **connect-attempt deadline** inheriting `ack_timeout_seconds` (no new knob), checked *before* the connector tick (deadlines-before-I/O), cancelling the connector and faulting to `FAILED` with the connector phase in `last_error` on expiry; SUBSCRIBE replay on CONNACK (mqtt, 2026-05-23) restores inbound after reconnect.

| ID | Proxy command sequence | Expected (mqtt 0.23.0) | 2026-07-04 status |
|---|---|---|---|
| A1 | `kill` (RST = hard death) → `blackhole on` to hold the outage window → `blackhole off` to "restart" | one-tick RST detect → FAILED → ~5 paced attempts across a 30 s hold (1-2-4-8-16 s), reconnect on the first attempt after `off`, in_flight drains | **RAN** — hardware-validated on Pico W MP via real `pkill -9 mosquitto` (convergence bake row): 5 paced SELF_HEAL attempts vs the ~470 full-tick-rate of the 2026-05-23 baseline.  Proxy form is the root-free host/CI equivalent; remaining boards queued. |
| A2 | broker-side `pkill -TERM` / `mosquitto_ctrl ... disconnect` for the graceful DISCONNECT+FIN; proxy `blackhole` holds the subsequent outage | recv-zero (`recv_into()==0`) detect → FAILED → same paced self-heal; CONNACK drains the pre-connect queue on reconnect | **RAN** — hardware-validated on the same build (convergence row): pre-connect queue drained (`in_flight 8 tx_queue 8` at reconnect), every drained publish acked.  Graceful-DISCONNECT is broker-side (a byte proxy can't synthesize it); the proxy covers only the outage hold. |
| A3 | `drop-puback on` (bounded window) → `drop-puback off`; drive with `mqtt_qos1_flood.py` | in_flight entry never clears → ack deadline expires → DUP=1 retransmit; a PUBACK after `off` clears it, else retry-limit → FAILED | **SMOKE** — host smoke proved the eat-acks / publishes-through split (`pubacks_dropped=15`, 0 acked).  Board retransmit-path bake queued. |
| A4 | `blackhole on` for 10 min → `blackhole off` (or `kill` then `blackhole`) | backoff caps at 60 s → ~1,2,4,8,16,32,60,60… cadence over the outage (not full tick rate); per-attempt heap footprint constant (E2); in_flight bounded / shed | **QUEUED** — needs the 10-min duration + heap / retry-counter instrumentation (harness extension). |
| A5 | harness sets `clean_session=False`; `kill` + `blackhole` for the outage; restart mosquitto with `persistence true` | session-present honoured on CONNACK; in-flight redelivered DUP=1; no double-delivered retained | **QUEUED** — needs the `clean_session` harness toggle + a persistent broker. |
| A6 | high-rate `mqtt_qos1_flood.py` to keep `_drain_tx_queue` busy, then `kill` mid-drain | `_partial_send` from the dead socket dropped, not replayed on the new socket; no orphaned prefix bytes on the wire | **QUEUED** — timing the kill against a partial send is easier on the board bake than the host smoke. |
| A7 | establish a connection → `blackhole on` to freeze it half-open → board re-dials (fresh conn) with the same `client_id` | broker MUST_DISCONNECT_EXISTING evicts the ghost; board reaches CONNECTED, no orphaned state | **QUEUED** — the eviction is broker behavior; `blackhole` supplies the half-open condition. |
| A8 | any reconnect-forcing sequence (`kill` then `blackhole on`/`off`), then publish to the subscribed topic and assert inbound resumes | SUBSCRIBE replayed from `_replay_subscriptions` on CONNACK → inbound resumes | **RAN (fix)** — SUBSCRIBE-replay hardware-validated 2026-05-23 (convergence: `received` 60→289 across two outages).  Proxy-driven re-run queued. |
| A9 | *not coverable by this control surface* — `blackhole` drops (doesn't delay) frames, so it can't inject the 4 s ack latency A9 needs | slow-broker ack latency without false-positive retry; tune `ack_timeout_seconds` | **QUEUED / extension** — needs a `delay <ms>` proxy command or real `tc netem` on a Linux broker host.  The one A-scenario the byte-drop proxy can't model. |

### B. Network-side failures

What the network does wrong, with broker and client both healthy.

| ID | Test | What it provokes | Expected | Failure means |
|---|---|---|---|---|
| B1 | **NAT-style silent drop** — proxy `blackhole on` (receive-and-discard both directions, sockets stay open), hold 60s, `blackhole off`.  Root-free replacement for the original `sudo pfctl` block; host-smoke-validated 2026-07-04 (subscriber stream stalled with `conns_active=1`, resumed on `off`) | TCP packets dropped without RST/FIN; board sees no data | board hits ack_timeout, transitions to `FAILED`, self-heal succeeds when block lifts | timeout never fires, deadline path doesn't fire because recv blocks first (convergence workstream concern) |
| B2 | **Wifi router power cycle** — physically toggle router off ~30s, on | board's wifi association drops; sockets become unwritable | board detects via send-error or ack-timeout; self-heal reconnects wifi if `chumicro-wifi` is wired in, then reconnects MQTT | unclear ownership: is wifi recovery a chumicro-wifi responsibility or chumicro-mqtt's?  Decision needed before running. |
| B3 | **DNS failure during self-heal** — wifi up, but broker hostname unresolvable (test DNS server returns NXDOMAIN, or block port 53 outbound) | socket-factory fails on `socketpool.getaddrinfo` | self-heal catches the OSError cleanly, stays in FAILED with last_error set to the DNS failure, retries on next tick | self-heal blocks the runner on DNS timeout; or retries DNS at full tick rate burning the CPU |
| B4 | **Wifi up but broker unreachable** — router associated, broker IP no longer routable (firewall change, broker moved, ISP outage) | TCP SYN times out | self-heal's `socket.connect` either fails fast (RST) or blocks; either way board reaches FAILED with a meaningful last_error; doesn't spam connect retries beyond a back-off | board hangs in connect indefinitely; or retries at tick rate without back-off |
| B5 | **Router reassigns broker IP** — board sees stale DNS, broker now at a different IP behind the same hostname | self-heal must re-resolve, not cache | next reconnect resolves the new IP and succeeds; cached IP doesn't pin the dead address forever | board pins the dead IP, never recovers without manual board reset |
| B6 | **Wifi credentials change mid-bake** — secrets.toml on-board file gets re-written (deploy mid-bake), wifi config now has wrong password | wifi-rejoin failure during self-heal | board surfaces the wifi failure as `last_error`; doesn't try to reconnect to MQTT before wifi is back | client tries MQTT-connect on a dead radio; self-heal layer doesn't distinguish wifi-down from broker-down |

### C. TLS-specific edges

What TLS does wrong, independent of broker / network primitives.

| ID | Test | What it provokes | Expected | Failure means |
|---|---|---|---|---|
| C1 | **TLS handshake failure on reconnect** — broker cert renewed with a different CA mid-bake, board still has old CA in `ssl_context` | TLS handshake fails with cert-validation error | self-heal catches the OSError cleanly, stays in FAILED with last_error pointing at cert validation; doesn't retry the handshake at tick rate burning CPU | board hangs in TLS handshake; or retries handshake at tick rate; or accepts a bad cert silently |
| C2 | **TLS cert renewal mid-session** — broker cert renewed BUT old session keeps running (mbedTLS renegotiation off, board doesn't notice the cert change) | session continues fine; reconnect after broker restart would fail | bake continues normally for the original session; only the next reconnect surfaces the new CA gap | board treats the in-session continuation as failure; or fails on reconnect without clear last_error |
| C3 | **TLS session resumption after broker restart** — same broker, same cert, board reconnects with TLS session ticket from previous session | broker may accept or reject the resumption ticket | client doesn't pin to ticket-only flow; falls back to full handshake on ticket rejection | board pins to resumed-session-only and fails when broker doesn't honour the ticket |

### D. Client-side failures

What the client does wrong, with broker and network both healthy.

| ID | Test | What it provokes | Expected | Failure means |
|---|---|---|---|---|
| D1 | **QoS 1 lost PUBLISH outbound** — inject error before TCP send | publish enqueued but never sent | deadline expires, retry attempts up to `publish_retry_max`, finally transitions to `FAILED` with last_error | retry counter wrong, transitions don't happen |
| D2 | **High-rate sustained burst** — 50 Hz publish for 60s, return to 1 Hz | tests recv-budget exhaustion, tx-queue saturation, partial-send path | rate sustained without backpressure errors; if `MQTTBackpressureError` raised, caller can retry; no leak; heap stable | tx_queue grows unboundedly, partial-send path leaks state |
| D3 | **Large-payload bursts** — single 4 KB PUBLISH every 10s for 5 min | exercises recv-buffer chunking + partial-recv path | each large packet decoded correctly, no in_flight leak, heap stable | partial-recv state lost between ticks, decoder buffer overflow |
| D4 | **Many concurrent QoS 1 when broker dies** — 20 publishes in_flight, broker FINs, restart 60s later | in_flight cleanup with `clean_session=True` vs persistence with `clean_session=False` | `clean_session=True`: in_flight reset on self-heal; `clean_session=False`: in_flight preserved + redelivered with DUP | in_flight leaks across reconnect; or wrong DUP behaviour |
| D5 | **Subscriber disconnect (one-sided silence)** — Mac driver dies mid-bake, broker keeps the board's TCP up | board continues publishing; broker queues / drops based on QoS | board doesn't notice and doesn't care (publishes don't require a subscriber); heap stable | board treats no-inbound as a failure signal and over-reacts |

### E. Baseline / leak detection

What grows slowly that the negative tests above won't catch.

| ID | Test | What it provokes | Expected | Failure means |
|---|---|---|---|---|
| E1 | **Long-duration baseline** — 30-min and 2-hour happy-path bake on CP custom firmware | sub-detection-threshold leaks | heap drift below noise across both durations | slow leak compounds; rate × time crosses detection threshold |
| E2 | **Self-heal retry-storm memory growth** — broker offline for 10 min while board hammers self-heal | per-attempt allocation growth | every reconnect attempt resets to the same heap footprint; no per-attempt accumulation | each self-heal leaks a few bytes; heap rises monotonically during outage |
| E3 | **Retained-publish queue under outage** — application enqueues 1 Hz publishes while broker is down for 5 min | `MQTTBackpressureError` rate + tx_queue cap behaviour | publishes past `max_tx_queue_size` raise `MQTTBackpressureError` cleanly; queue doesn't grow unbounded; no orphaned packets on reconnect | tx_queue grows past cap silently; or all 300 backlogged publishes flush on reconnect and overwhelm the broker |

## What the user explicitly asked about (2026-05-23)

- **"What if the mqtt server goes down and comes back up"** → A1 (broker hard-kill + restart) is the foundational version; A4 (long outage), A5 (session resumption), A6 (FIN mid-publish), A7 (stale client_id), A8 (subscribe survival) are the deeper edges.
- **"What if wifi goes down and back up"** → B2 (router power cycle) is the foundational version; B4 (wifi up but broker unreachable), B5 (router reassigns broker IP), B6 (wifi credentials change) are the variations that matter for the chumicro-wifi handoff.

## Where wifi-router cycle belongs

B2 / B6 ambiguously straddle `chumicro-mqtt` and `chumicro-wifi`.  Open question for the resumer: does chumicro-mqtt own "I see the underlying socket fail, retry"?  Or does chumicro-wifi own "the radio's down, services should pause"?  Decision belongs in an ADR before B2 / B6 land.  Leaving them here as the surfacing trigger; route the actual tests to `chumicro-wifi`'s test inventory once the boundary is decided.

## Harness reuse

The 2026-05-23 bake harness (`projects/mqtt_bake_diag*` in workspace-template, gitignored, local-only) is the right starting point — it already covers:

- per-10-sec window stats (iters, max_tick_ms, max_wait_ms, max_pub_ms)
- 30-sec heap checkpoints
- bidirectional 1 Hz QoS 1 traffic with sequence-gap detection
- `chumicro_timing.ticks` throughout (post-fix)
- pluggable `VARIANT` constant so multiple bakes coexist on the broker without crosstalk

The broker-kill / NAT-drop / PUBACK-drop toggles no longer live in the harness at all — they are provided out-of-process by `scripts/mqtt_negative_proxy.py`'s control port (`kill` / `blackhole` / `drop-puback`), which the board dials in place of the broker.  The harness keeps its stats + `--variant` / `--client-suffix` plumbing; the fault injection is a separate control connection the Mac driver (`.scratch/mqtt_bake_mac_driver.py`) opens to the proxy.

Concrete extensions needed for the new tests:

- **A4 / E2 / E3:** instrument the bake to log heap + retry-counter at every CHECKPOINT during an extended outage so growth shows.
- **A5 / A6 / D4:** add a `clean_session` toggle to the harness's `MQTTClient` construction; default True, opt-in False for session-resumption tests.
- **A7:** scriptable broker-side `client_id` collision via a second mosquitto on a different port that hijacks the same client_id.
- **A8:** add `subscribe_then_assert_inbound_resumes` flow that re-asserts inbound delivery after every reconnect.
- **A9:** the bake host is macOS (no `tc`); latency injection needs either a Linux broker host running `tc netem delay 4s` or a new `delay <ms>` command added to `mqtt_negative_proxy.py`.  The current proxy's blackhole/drop surface can only drop, not delay — A9 is the one A-scenario still without a root-free path.
- **B3 / B4 / B5:** scriptable DNS shaping via a per-test `/etc/hosts`-like override on the broker host (or a local CoreDNS).
- **C1 / C2 / C3:** per-test TLS cert generation script.

## What is not in scope

- Building chumicro-wifi's own negative test suite.  Reference here; that work belongs in chumicro-wifi.
- Cross-runtime negative testing for `chumicro_sockets` / `chumicro_runner` directly.  Those happen via the MQTT layer here; they get their own targeted tests later if signal warrants.
- Brownout / power-glitch tests.  These belong in a per-board hardware-stress workstream.
- Multi-broker failover (different `broker_host` mid-session).  Application-level concern; chumicro-mqtt is single-broker by design.
