# Handoff 2026-05-24 — test-harness-promotion Phase 1 + 2 landed; streaming-transport workstream surfaced + scoped

## What this session was about

Started after the previous handoff was retired (commit `676e6726`) — no in-flight work, working tree clean. User asked me to survey workstreams + next-up and recommend something to pick up. I recommended `test-harness-promotion-and-network-helper` Phase 1 (Decision 0082 directive, well-scoped, infrastructure other things benefit from). User picked it.

We landed Phase 1 (the `chumicro_test_harness.network` submodule), then went into Phase 2. Phase 2's mqtt + sockets + ntp + requests mechanical rewrites went fine (Slice 1). The wheels came off when I tried to design the http_server rewrite (Slice 2): I wrote Decision 0085 confidently, then discovered after-the-fact that the transport interface it depended on doesn't exist (`TransportProtocol.execute` is request/response, not streaming). User caught me flip-flopping under pressure on the recovery path. The eventual resolution: spin off a real `streaming-transport` workstream as its own piece of infrastructure, defer Slice 2, ship Slice 3 (fixture consolidation) which was independent.

User's parting framing: "these handoffs keep resulting in context loss that hurts the workstream." This handoff is deliberately verbose. Lift the *thinking* — the dead ends and the why — not just the punch list.

## What's in flight

Working tree at handoff write:

- `.idea/chumicro.iml` — modified, **pre-existing drift carried from before this session** (was already present at session start; same drift was noted in the previous 2026-05-23 handoff). Not load-bearing for any in-flight work; don't try to "fix."

Untracked (.scratch/, gitignored — won't reach git):

- `.scratch/preflight.log` — last preflight run output, debugging aid only.
- `.scratch/mqtt-probe-config/` + `.scratch/mqtt-probe-certs/` — from a much earlier session (pre-session-start); mosquitto still running against this config as of write (see Gotchas).

Nothing committed-but-pending. Nothing mid-edit.

## What got done

Six commits this session, oldest first. All pushed to `main`.

- `676e6726` — retired the stale 2026-05-23 mqtt-convergence handoff. Its punch list had been overtaken by subsequent work; durable signal already in the convergence workstream + memory entries.
- `4613ff0d` — **Phase 1 of test-harness-promotion-and-network-helper.md.** New `support/test_harness/src/chumicro_test_harness/network.py` (`wifi_up` + `runtime_config` + inline msgpack decoder) lifted from the canonical `http_server/examples/helpers.py` body. Cross-runtime test file with 11 tests at 97% coverage. `support/test_harness/pyproject.toml` literal version 0.0.0 → 0.1.0. [VERIFIED: preflight green at coverage 94 across CPython + MP + CP runtimes, all 3 runtimes pass test-all-runtimes]
- `3b46b6bf` — appended Phase 1 entry to the test-harness workstream's Validation history.
- `8c3c109f` — **Phase 2 Slice 1.** Eight functional-test files swapped to `chumicro_test_harness.network` + Category 1 / 2 declarations: mqtt/test_real_broker.py (Cat 1), sockets/test_real_{udp,tcp,tls,tls_matrix}.py (Cat 1 / 2 / 2 / 2), ntp/test_real_ntp.py (Cat 2), requests/test_real_{get,get_tls}.py (Cat 2). `support/test_harness/tests/test_assertions.py` switched from `import pytest` to self-circular harness `raises` (no marker workaround needed). [VERIFIED: preflight green; all functional-test files lint clean; CHU006 caught the initial `(Decision 0083)` ADR refs and I stripped them.]
- `11ff6a5f` — **Decision 0085** (board-to-host sync via stdout markers). Status `accepted`. Body designs the marker protocol; subsequent edit added the streaming-transport prerequisite section.
- `a601961f` — **streaming-transport workstream surfaced.** New `plans/workstreams/streaming-transport.md`. Decision 0085 substrate-prereq note + cross-link. `plans/next-up.md` queues it at the top of `## Next`. test-harness workstream validation history records Slice 1 + the ADR + the Slice 2 deferral pointer.
- `e959b5c1` — **Phase 2 Slice 3.** `chumicro_pytest_device.fixtures.{lan,mosquitto,udp_echo}` submodule lifts the host-side fixture helpers out of mqtt + sockets conftests. Conftests shrink ~140 LOC combined. pytest-device 0.10.1 → 0.11.0. 8 new unit tests cover the testable surface; network-touching paths pragma-no-cover (exercised by the functional tests that consume them). [VERIFIED: preflight green at coverage 94]

What's NOT done: **Phase 2 Slice 2** (http_server/test_real_serve.py rewrite). Deferred. Blocked on `streaming-transport` workstream landing. Re-enters this workstream as a follow-up slice. The current `test_real_serve.py` is still the broken-on-Pi-Pico-W self-loopback variant — I did not touch it.

## Decisions made (not yet captured in ADRs)

**Decision 0085 + streaming-transport workstream — already in ADR + workstream files**, no need to re-document the protocol or implementation roadmap here. What ISN'T in those files but matters for next session:

### Why streaming-transport is its own workstream, not a Phase 2 sub-task

I initially tried to slot the streaming-transport work as "Slice 2 of Phase 2 of test-harness-promotion." Wrong scope. Streaming-transport is real infrastructure (~3 sessions of focused work across mp + cp + Fake transports + chumicro_pytest_device dispatcher) with multiple named consumers (see workstream file). Bundling it under test-harness Phase 2 would have hidden it; surfacing it as a standalone workstream with its own roadmap is the honest scope. test-harness Phase 2 is "wrap the rest of Phase 2 cleanly, defer Slice 2 with a pointer." [VERIFIED: workstream file at `plans/workstreams/streaming-transport.md` lists the consumers (http_server, mqtt second-client inbound-delivery, live bake output, future websockets server, future Category 3)]

### Why we're not dropping the http_server functional test

I floated this as a path forward when the substrate gap surfaced. User correctly pushed back: **"we only have one [server-side] test due to complexity. we can and will have more, and in other situations, mqtt could benefit from this too by asking some second client to publish or otherwise interact with the client on the board for example."** The mqtt-second-client use case is the load-bearing one — today's mqtt test only does publish-then-subscribe loopback on the board; verifying inbound delivery from an *external* publisher needs exactly the marker-dispatch substrate. That's a real consumer, not hypothetical. So: streaming-transport ships, http_server rework follows, mqtt inbound-delivery coverage follows.

### Wifi-maintenance regression — accepted, with a specific rationale

The functional-test rewrites dropped the `wifi.check(_ticks_ms()); wifi.handle(_ticks_ms())` calls from main loops (the harness `wifi_up` is one-shot bringup, not a `WifiService`-style maintained connection). User asked "is there a better way?" Three options surfaced (accept + reframe rationale, add `wifi_is_connected()` poll, retry decorator at pytest-device layer). User picked accept + reframe. The reframe is: **functional tests run 10-30 seconds — too short for wifi maintenance to matter. Long-running bake tests that genuinely need WifiService keep importing chumicro_wifi directly; those are a different test category** (Decision 0083 Category 3 deferred / the wifi-recovery-bake next-up item). This isn't a "regression we tolerate"; it's "the test category doesn't need maintenance." [VERIFIED: rationale recorded in commit `8c3c109f` message body; the test-harness workstream validation history points at this commit]

### Workstream-vs-reality drifts I found + fixed inline

The test-harness workstream's Phase 2 description has several factual errors against actual code state. I worked from reality, not the workstream prose. Next-session note: if you re-read the workstream Phase 2 description, it'll claim things that aren't true. The CODE is the source of truth.

- Workstream said "5 networking libraries" — there are actually 6 (websockets has a `helpers.py` too). Phase 2 covered the 5 the workstream named; websockets was deliberately left for a separate slice. [VERIFIED: `find libraries -name "helpers.py" -path "*/examples/*"` shows 6 copies]
- Workstream said "sockets/test_real_udp.py (+ test_real_tcp.py if present) → already Category 1." False — `test_real_tcp.py` uses `example.com:80` (Category 2, public endpoint). `test_real_tls.py` and `test_real_tls_matrix.py` also Category 2 (Let's Encrypt + badssl). Only `test_real_udp.py` is Category 1 (host echo fixture). I declared each correctly per actual endpoint. [VERIFIED: read each file's target host; declarations in commit `8c3c109f`]
- Workstream said "Bump support/test_harness/VERSION accordingly." That file doesn't exist; test_harness uses a static `version = "0.0.0"` literal in pyproject.toml. I bumped the literal to 0.1.0. Phase 4 (tree move to libraries/) is where the VERSION-file convention switch should land. [VERIFIED: `support/test_harness/` has no VERSION file; peer libraries do]
- Workstream Phase 1 description says "Cross-runtime test file covers the helper at the harness level." Realized after writing tests that wifi_up's CP/MP wifi-connect bodies + runtime_config's file-read success path can't be unit-tested on host (require hardware or filesystem state). Used `# pragma: no cover - <reason>` on those branches; tested decoder + error paths thoroughly. Cleanest workable interpretation. [VERIFIED: network.py covers 99% on CPython; the 1% is the if-isinstance line in runtime_config]

### test_assertions.py: the better fix wasn't the obvious fix

User initially asked me to "fix the import pytest issue" in `support/test_harness/tests/test_assertions.py`. My first instinct was to add `__chumicro_runtimes__ = ("cpython",)` marker (host-only opt-down). User followed up with **"doesn't the harness itself re-invent raises"** — pointing out the four `pytest.raises` calls in test_assertions.py could all be replaced with the harness's own `raises` (self-circular but self-consistent: if `raises` is broken, both inner and outer misbehave detectably). That's what I did. No marker needed; file runs cross-runtime like its peers.

**Lesson for future-me:** when the obvious fix is "add a workaround marker," look for a fix that doesn't need a workaround. The harness having tests that USE the harness is more honest than the harness having tests that import the thing it replaces.

## What was learned

### `TransportProtocol.execute` is request/response, not streaming

I assumed (wrongly) that `chumicro_pytest_device` had some live-stdout mechanism. It doesn't. Looking at the signature at `workbench/deploy/src/chumicro_deploy/protocol.py:312`:

```python
def execute(self, bootstrap_script: str) -> str:
    """Run *bootstrap_script* on the device and return captured stdout."""
```

That's it. Board runs to completion, then the host gets the whole captured string. `result_parser.py` does post-hoc line parsing on the returned string. No callback hook anywhere. [VERIFIED: read protocol.py + result_parser.py; grepped for "stdout_callback" / "on_line" / "stream" — zero matches in chumicro_deploy and chumicro_pytest_device]

Implications: any test design that needs board-side code and host-side code to coordinate mid-execution requires lifting this interface to streaming first. The streaming-transport workstream's Phase 1 is exactly this: add an `on_line: Callable[[str], None] | None = None` parameter to `execute`. The mpremote subprocess (`Popen(stdout=PIPE)` → `iter(p.stdout.readline, '')`) already reads line-by-line; the cp pyserial transport reads byte-by-byte and buffers — both can support the streaming hook without changing how they capture bytes, just by adding a per-line dispatch callback alongside the existing buffer-append.

### `chumicro_test_harness/tests/test_runner.py` + `test_discovery.py` were already cross-runtime

They reference `__chumicro_runtimes__` in strings (error messages, etc.) but don't `import pytest`. Only `test_assertions.py` had the violation. Easy to miss; would be wrong to "fix" them. [VERIFIED: `grep -n "import pytest\|__chumicro_runtimes__" support/test_harness/tests/*.py` — only test_assertions.py imported pytest]

### The audit-comments skill is a real reference

I read it once mid-session at the user's prompt. The dimensions that mattered for Phase 2:

- §1 says-what-it-does-plainly-first (the Category declarations are docstring openers; they should be statements, not title-fragments)
- §3 provenance noise (the `(Decision 0083)` refs I initially added are exactly the kind of "provenance pointer" §3 calls out, and CHU006 enforces it for shipped libraries — caught me)
- §7 concrete subject + real verb (I rewrote `_send_all`'s docstring from "Write every byte through the protocol's non-blocking `send`, re-offering the tail on EAGAIN" → "Write every byte through `send`, re-offering the tail on EAGAIN or short writes" — same content, dropped abstract subject)
- §8 stance: no defensive padding (the original test docstrings had "Verifies the LED-blink invariant on a real board" prose that I kept — it's actually load-bearing)

Worth re-reading the skill at the start of any prose-heavy session.

## Riskiest assumption

**That the streaming-transport workstream's Phase 1 implementation cost is "~3 sessions."** I made this estimate in a question-option label. I haven't actually opened the transport implementations to scope it. The mpremote side is genuinely easy (subprocess line iteration is one or two lines of glue). The pyserial side might not be — it has an existing intricate raw-REPL byte-parser that accumulates `OK<stdout>\x04<stderr>\x04>` markers from `Ctrl-A → bootstrap → Ctrl-D` interactions. Adding per-line dispatch to that without breaking the framing is the unknown.

[HYPOTHESIS: cheapest test = read `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py` `execute` implementation (around line 999) and identify the read-loop. If it's a "read until prompt token, then split into stdout/stderr" pattern, adding a per-newline dispatch inside the read loop is mechanical. If it's "read whole output then split," the streaming hook needs more thought.]

## To re-research / verify next session

1. **If picking up `streaming-transport` Phase 1:** read `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py` around line 999 to see how the raw-REPL byte stream is currently collected. The streaming hook needs to fire per `\n` *inside* the stdout section, before the `\x04` terminator. Verify the framing assumption.
2. **If picking up `streaming-transport` Phase 1:** `workbench/deploy/src/chumicro_deploy/micropython_transport.py:495` for the mpremote side. Subprocess PIPE-based, should be straightforward (`iter(process.stdout.readline, '')`).
3. **Decision 0085's marker syntax doesn't collide with existing result_parser markers.** The existing parser at `workbench/pytest-device/src/chumicro_pytest_device/result_parser.py` matches `PASS`/`FAIL`/`SKIP`/`SUMMARY`/`HEAP` line prefixes; sync markers use uppercase identifiers like `SERVER_READY`. The two enums are disjoint at write — but the streaming-transport workstream's Phase 2 should add a non-colliding parser pass and confirm. [HYPOTHESIS: cheapest test = grep for the existing marker tokens to confirm no overlap with anything resembling sync-marker names]
4. **Phase 4 of test-harness-promotion** (tree move `support/test_harness/` → `libraries/test_harness/`) will need the VERSION-file convention. When that lands, the `support/test_harness/pyproject.toml` static `version = "0.1.0"` should switch to a `VERSION` file + `dynamic = ["version"]` + hatchling (matching peer libraries). Don't pre-do this in any Phase 2 follow-up; it belongs in Phase 4.
5. **websockets functional tests still carry their own conftest** (`libraries/websockets/functional_tests/conftest.py`). Phase 2 deliberately left websockets out per the workstream's "5 libraries" wording. A follow-up slice could extend Phase 2's mechanical swap + Category declarations to websockets. Low priority but worth tracking.
6. **mosquitto running as PID 63126 [VERIFIED: `pgrep -lf mosquitto` returns it as of write].** This is from a much earlier session, predates this one. If next session needs it for mqtt work, it's already up against `.scratch/mqtt-probe-config/mosquitto.conf`. Otherwise leave it.

## Dead ends

- **Pre-resolved board IP in devices.yml as the http_server sync mechanism.** I labeled this "Recommended" initially. User pushed back: DHCP renewals, router reboots, firmware reflashes (new MAC → lost reservation) all silently break it. Correct critique. Don't revisit unless the test infrastructure adds a real "this board has a permanent IP" guarantee (it doesn't today).
- **127.0.0.1 self-loopback on the board.** Considered as a way to test http_server without host-driver coordination. Two strikes: (a) unverified on CP — Pi Pico W's lwIP might or might not route 127.0.0.1 internally; (b) even if it works, packets don't traverse the radio, so it doesn't catch socketpool/mbedTLS-integration regressions. Not a real integration test.
- **Dropping the http_server functional test entirely.** I floated this as the pragmatic option after the streaming-substrate gap surfaced. User correctly pushed back: test count is downstream of infrastructure availability (you don't write tests that need infrastructure you don't have). Naming mqtt-second-client as a concrete second consumer made the streaming workstream's standalone value visible.
- **`__chumicro_runtimes__ = ("cpython",)` marker on test_assertions.py.** My first reach for the pytest-import issue. The harness's own `raises` could replace pytest's `raises` self-referentially; no marker needed. User caught it.
- **Adding `(Decision 0083)` ADR refs to functional-test module docstrings.** CHU006 lint caught it: ADR references shouldn't be in shipped library code. The Category declaration alone (`Category 1 — host-side Mosquitto fixture.`) is what the audit-library lint reads; the ADR ref is provenance noise.
- **Estimating cost-benefit on streaming-transport based on current test count.** Bad math: I argued "only one server-side test exists, infrastructure cost too high for ratio." User pointed out the test count is suppressed BY the missing infrastructure. Future-me, watch for this pattern: when something looks "rarely needed," ask whether its rarity is consequence rather than evidence.

## How to rebuild context fast

Read in this order:

- **This handoff** (just confirmed).
- **`git --no-pager log --oneline -10`** — shows the six session commits (`676e6726` → `e959b5c1`) plus what was main-tip at session start (`1dc7be82`).
- **`plans/workstreams/streaming-transport.md`** — the next big workstream's roadmap + named consumers. If picking it up, this is the directive.
- **`plans/decisions/0085-board-to-host-sync-stdout-markers.md`** — the marker protocol spec. Its "Substrate prerequisite" section names what streaming-transport needs to land first.
- **`plans/decisions/0083-functional-test-endpoint-taxonomy.md`** — the Category 1/2/3 taxonomy that drove Phase 2's docstring declarations. Edited inline this session to point at 0085 + correct the "start an HTTP server" wording.
- **`plans/workstreams/test-harness-promotion-and-network-helper.md`** — Phase 2 done modulo Slice 2 deferred. Validation history at the bottom records what shipped + the deferral.
- **`support/test_harness/src/chumicro_test_harness/network.py`** — Phase 1 deliverable. Lifted from `libraries/http_server/examples/helpers.py` (the canonical body).
- **`workbench/pytest-device/src/chumicro_pytest_device/fixtures/`** — Slice 3 deliverable. Three submodules: `lan.py`, `mosquitto.py`, `udp_echo.py`. mqtt + sockets conftests now import from here.
- **`libraries/{mqtt,sockets,ntp,requests}/functional_tests/test_real_*.py`** — Slice 1 rewrites (8 files). Each module docstring opens with a Category declaration; harness imports replace chumicro_wifi/config.
- **`workbench/deploy/src/chumicro_deploy/protocol.py:312`** — the `TransportProtocol.execute(bootstrap) -> str` signature streaming-transport Phase 1 is lifting.
- **`workbench/deploy/src/chumicro_deploy/circuitpython_transport.py:999`** + **`workbench/deploy/src/chumicro_deploy/micropython_transport.py:495`** — the two implementations to extend.

Search terms for tracking down related context:

- `chumicro_test_harness.network` — Phase 1 module
- `chumicro_pytest_device.fixtures` — Slice 3 submodule
- `wifi_up` / `runtime_config` — harness helper functions (replace chumicro_wifi + chumicro_config in tests)
- `start_mosquitto_broker` / `start_udp_echo_server` / `detect_lan_ip` — fixture helpers
- `SERVER_READY` / `SERVER_REQUEST_OBSERVED` — Decision 0085's marker names
- `parse_marker` / `MarkerQueue` / `wait_for` — streaming-transport workstream's planned API surface (not yet implemented)
- `Category 1` / `Category 2` — functional-test docstring declarations

## Gotchas

- **mosquitto running as PID 63126 from before this session.** `pgrep -lf mosquitto` confirms. Config at `.scratch/mqtt-probe-config/mosquitto.conf`. Two listeners (PLAIN 1883, TLS 8883). Not from anything we did today — survives from an earlier session.
- **`.idea/chumicro.iml` shows modified** but it's pre-existing drift from before this session, carried in every recent handoff. Same shape as the previous handoff noted. Don't try to fix in the next session unless explicitly asked.
- **Pi Pico W CP custom firmware** (`10.2.0-dirty`, `/dev/cu.usbmodem112301`): supervisor.ticks_ms seeded near rollover (memory: `project_pico_w_cp_custom_fw_ticks_wrap`); native msgpack stripped (memory: `project_pico_w_cp_custom_fw_msgpack_strip`). Same gotchas as previous handoff.
- **Test-harness workstream Phase 2 description is partially wrong** against actual code — see "Workstream-vs-reality drifts" in Decisions section above. If next-session re-reads the workstream Phase 2 prose, treat it as a writeup that drifted, not as a directive. Reality is the deliverables that landed: Slices 1 + 3 shipped, Slice 2 blocked on streaming.
- **`http_server/test_real_serve.py` is still self-loopback via `chumicro_requests`** — untouched this session. It's the canonical example of "test that breaks on Pi Pico W defaults" and will stay that way until the streaming-transport workstream lands. Don't be tempted to "fix" it in isolation; the fix is the streaming substrate.
- **`websockets/functional_tests/conftest.py` still has its own host-side fixture machinery** (presumably similar shape to mqtt's). Phase 2 deliberately scoped websockets out. If a future slice extends Phase 2 to websockets, it should also consolidate websockets' host fixture into `chumicro_pytest_device.fixtures` alongside `mosquitto.py` + `udp_echo.py`.
- **The "Substrate prerequisite" section in Decision 0085 is what makes the ADR status `accepted` rather than `proposed`.** Reasoning: the design itself is sound — the marker protocol works, the syntax is well-defined, the rejected-alternatives still hold. What's pending is the substrate that runs it. ADR status is about design soundness, not substrate availability. If next-session disagrees, the demote-to-`proposed` option was explicitly offered to the user and rejected in favor of in-place note.
- **`support/test_harness/pyproject.toml` uses static `version = "0.1.0"` literal** (not a `VERSION` file like peer libraries). This is the test_harness convention today and stays this way until Phase 4 of test-harness-promotion (tree move to `libraries/test_harness/`) which is where the convention switch belongs. Bumped 0.0.0 → 0.1.0 this session for the new `network` submodule. Don't pre-emptively add a VERSION file.
- **The user's parting framing — "these handoffs keep resulting in context loss that hurts the workstream" — is the load-bearing signal for the next session.** If anything in this handoff is unclear or seems to be missing context, that's the problem the user has flagged repeatedly. Err toward asking the user "what did the previous session intend here?" rather than guessing.
