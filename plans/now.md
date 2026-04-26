# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **beginner-onramp** Steps 1, 2, 3, 4, 5 all shipped 2026-04-26 — the full UX backbone is complete.  A fresh user can run `chumicro-workspace bootstrap --with-demo` and see code execute on their hardware in one command.  Remaining: Step 6 (`chumicro-requests` library), Step 7 (`chumicro-http-server` library), Step 8 (examples organization + two-thing demo).  See `plans/workstreams/beginner-onramp.md`.
- **Last shipped:** Step 4 — `chumicro-workspace bootstrap` end-to-end onboarding wizard.  Pick port → probe with auto-runtime-inference → display detected runtime + version + machine → firmware-floor warn → pick device id (suggestion derived from probed machine string) → register → optional `--with-demo`.  Three flags (`--port`, `--device-id`, `--with-demo`) skip prompts; passing all three runs end-to-end non-interactively.  Single port detected → silent auto-pick; multiple ports → numbered list + prompt.  Reuses Steps 1-3+5 helpers, no second probe, no policy duplication.
- **In flight:** beginner-onramp workstream Step 6+ — `chumicro-requests` is the next major slice (new device library, modeled on `chumicro-mqtt`'s non-blocking shape on top of `chumicro-sockets`).  See `plans/workstreams/beginner-onramp.md` library design notes.
- **Blocked on:** —
- **Last touched:** `workbench/workspace/src/chumicro_workspace/cli.py` (added `_cmd_bootstrap`, `_resolve_bootstrap_port`, `_resolve_bootstrap_device_id`, `_suggest_device_id`, `_stdin_prompt`, parser registration), `workbench/workspace/tests/test_cli.py` (16 new tests across `TestBootstrapHelpers` + `TestBootstrapWizard`), `plans/workstreams/beginner-onramp.md` Step 4 status log entry, `plans/next-up.md`.

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
