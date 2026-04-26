# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **idle** — Phase 7 closed end-to-end; chumicro-mqtt + chumicro-sockets just landed a production-readiness sweep against patterns from the older `pythonProject3` MQTT impl.  Pick the next workstream phase or queued item from `plans/next-up.md`.  Phase 8 (application-level OTA via `chumicro-update`) is the next workstream phase but parked until Phase 7 has soak time in the field.
- **Last shipped:** `chumicro-mqtt` 0.1.4 — bounded recv-per-tick (1 KB default) so fat kernel TCP buffers can't starve LED / LCD / control-loop tasks; bounded tx queue (100 default) with `MQTTBackpressureError` on overflow; protocol-internal traffic (PUBACK, retransmits, PINGREQ) bypasses the cap; failed QoS-1 publish rolls back packet_id allocation.  `chumicro-sockets` 0.1.4 — `ssl_context_with_ca` defaults to `verify_mode = CERT_REQUIRED` (no more accidental blind trust) and supports multi-cert PEM bundles (multiple `BEGIN CERTIFICATE` blocks → concatenated DER).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/mqtt/src/chumicro_mqtt/{client,_wire,__init__}.py` (`recv_budget_per_tick`, `max_tx_queue_size`, `MQTTBackpressureError`, `_enqueue_user_tx` helper), `libraries/mqtt/tests/test_client.py` (8 new `TestBoundedRecvPerTick` + `TestTxQueueBackpressure` cases), `libraries/sockets/src/chumicro_sockets/_adapters/{mp,cp,cpython}.py` (CERT_REQUIRED default + multi-cert PEM handling in `_pem_to_der`), `libraries/sockets/tests/test_mp_adapter.py` (2 new cases), VERSION bumps to 0.1.4 each, `plans/learnings.md` (recv-loop starvation pattern), `plans/next-up.md` Done entry.

---

## Phase 7 closeout (this session)

The first end-to-end sensor thing — wifi → sockets → mqtt → kvstore → workspace — is shipping on a Pi Pico W RP2 with TLS-encrypted MQTT against a verified CA.  Five integration concerns surfaced and resolved during the workstream:

* **Thing-name validation** — `chumicro-workspace new <name>` refuses non-identifier / leading-underscore / keyword names up-front (commit `4841190`).
* **Import-graph submodule probing** — `ImportGraphSource` now probes `{module}.{alias_name}` for every `from foo import bar` so runtime-gated `from chumicro_sockets._adapters import mp` ships the named adapter (commit `157a865`).
* **Wifi-drop self-heal** — `MQTTClient` gains a `socket_factory` constructor arg + `_attempt_self_heal` so the client rebuilds its socket after a wifi drop without per-thing recovery boilerplate (commit `3f60ef4`, used by the example sensor thing).
* **MP socket default-blocking enforcement** — `MQTTClient` calls `setblocking(False)` on every socket it acquires; closes the Layer-3 hang on Pi Pico W (commit `1239378`).
* **TLS-with-CA-verification on MP rp2** — `_MpSocketWrapper.recv_into` handles the TLS-recv-returns-None contract (commit `67fb4e8`); `ssl_context_with_ca` converts PEM input to DER so `load_verify_locations` works on rp2 builds without `MBEDTLS_PEM_PARSE_C` (commit `94561f7`).

Two open follow-ons, two forward-looking items, two deferred items captured in [`plans/workstreams/phase-7-integration.md`](workstreams/phase-7-integration.md).  Cross-board lessons (MP rp2 mbedTLS PEM-parse-disabled, TLS recv-returns-None contract, setblocking-on-MP defaults) lifted to [`plans/learnings.md`](learnings.md) so the next library author doesn't re-walk the investigations.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
