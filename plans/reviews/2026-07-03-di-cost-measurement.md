# DI cost measurement — networked libraries

Date: 2026-07-03. Read-only measurement pass. All numbers from the two
prebuilt unix-port binaries + `mpy-cross`; **no serial ports, no boards
touched**. Feeds a Fable synthesis pass — numbers first, judgment second.

## Headline

- **Flash — droppable-without-losing-function DI "ceremony" across the whole
  networked stack: ~3.2 KB `.mpy`** (`_get_adapter` dispatch + two
  `_adapters/__init__.py` shims + wifi `base.py` protocol + the five opt-in
  `sockets_factory.py` modules inlined). Against a ~800 KB-usable-flash board
  that is **~0.4 %**. Per-runtime adapter *bodies* (cp 3.5 KB / mp 4.2 KB mpy)
  are irreducible per-runtime code, not DI — and the deploy walker already
  ships only one.
- **Import heap — pure DI-module tax is 0.5–1.3 KB per library**, one-time, and
  only when the default factory is used. The core protocol modules that ride it
  cost **30–44 KB of heap to import** (mqtt 42 KB, websockets 44 KB on a
  264 KB-class board). DI is ~2 % of the heap of the thing it wires.
- **Hot path — 0 DI frames per runner tick.** The factory/connector fires
  **once per connect**; steady-state send/recv holds the raw socket and calls
  `self._socket.send/.recv_into` directly. DI adds exactly **1 extra Python
  frame per connect** (~0.06 µs/frame here; ~2–5 µs on a 133 MHz Pico, once).
- **What DI buys — 12 host fakes + ~256 injection call-sites** across the
  host test suites, full host-pytest without hardware, and *single-library
  integration*: `import chumicro_mqtt` / `chumicro_websockets` pull **zero**
  sockets code (verified). That last property — not flash/heap — is the whole
  payoff, and it costs almost nothing on-device.
- **Verdict input:** dropping DI reclaims a fraction of a percent of flash/RAM
  and no hot-path cycles, while forfeiting host testability and the
  bring-your-own-transport story. The cheap win, if any is wanted, is
  **alternative (c)**: keep DI in source, resolve it to direct calls at
  deploy time (the walker already selects per-runtime files) — zero device
  cost, testability intact.

## Architecture (what "DI" is here)

Two seams:

1. **Boundary libs `sockets` + `wifi`** carry per-runtime `_adapters/`
   (`cp.py`/`mp.py`/`cpython.py`). `sockets` dispatches via a memoized
   `_get_adapter()` (`sys.implementation.name`); `wifi` injects an adapter into
   `service.py` and declares an ABC in `_adapters/base.py`.
2. **Higher libs `mqtt`/`websockets`/`requests`/`ntp`/`http_server`** take a
   constructor-injected `socket=` and/or `connector_factory=`/`listener=`, plus
   an opt-in `sockets_factory.py` that wires `chumicro_sockets` by default.
   Each ships a `testing.py` of fakes riding those seams.

Deploy gating already in place (`workbench/deploy/src/chumicro_deploy/sources.py`):
- `file_targets_runtime` + `__chumicro_runtimes__` → **only one adapter of
  {cp,mp,cpython} lands on a device**; cpython adapter never ships.
- `is_test_support_module` + `__chumicro_test_support__` → **every `testing.py`
  is dropped; fakes are never flashed** (all 11 markers verified present).
- `read_skip_factories_marker` + `__chumicro_skip_factories__` (Decision 0093)
  → named `sockets_factory` modules dropped from the deploy graph.

## 1. Flash / source cost

Per-file, docstrings+comments stripped with the real deploy minifier
(`chumicro_deploy.source_minify.strip_source`), then compiled with the pinned
`mpy-cross` (bytecode v774; MP and CP mpy sizes are identical). Line counts are
useless as a "stripped" metric because the minifier *blanks* lines to preserve
line numbers — **stripped bytes and `.mpy` bytes are the flash proxies.**
chumicro deploys stripped `.py` (CircuitPython runs source; MicroPython may run
either); `.mpy` doubles as the import-RAM / compiled-code proxy.

**Per-library totals (bytes):**

| lib | CORE strip | CORE mpy | DI-factory strip | DI-factory mpy | DI-adapter strip | DI-adapter mpy | test-only strip (never flashed) |
|---|--:|--:|--:|--:|--:|--:|--:|
| sockets | 10049 | 4609 | 0 | 0 | 25771* | 11679* | 7532 |
| wifi | 6845 | 3071 | 0 | 0 | 5658* | 3015* | 2736 |
| mqtt | 57366 | 20070 | 832 | 588 | 0 | 0 | 2086 |
| websockets | 75586 | 29759 | 730 | 548 | 0 | 0 | 2325 |
| requests | 50066 | 18523 | 407 | 351 | 0 | 0 | 7992 |
| ntp | 6843 | 2960 | 191 | 216 | 0 | 0 | 0 |
| http_server | 36432 | 14217 | 1288 | 789 | 0 | 0 | 881 |

\* DI-adapter column sums **all** adapters; only one runtime's ships per device.

**DI-adapter breakdown (one ships):**

| file | strip B | mpy B | note |
|---|--:|--:|---|
| sockets `_adapters/__init__.py` | 9 | 82 | shim (ceremony) |
| sockets `_adapters/cp.py` | 7045 | 3542 | CP-only, irreducible impl |
| sockets `_adapters/mp.py` | 10203 | 4202 | MP-only, irreducible impl |
| sockets `_adapters/cpython.py` | 8514 | 3853 | **never ships to a board** |
| wifi `_adapters/__init__.py` | 10 | 78 | shim (ceremony) |
| wifi `_adapters/base.py` | 456 | 309 | ABC — **pure ceremony** (duck typing works) |
| wifi `_adapters/cp.py` | 1473 | 839 | CP-only, irreducible impl |
| wifi `_adapters/mp.py` | 3719 | 1789 | MP-only, irreducible impl |

**In-client injection plumbing** (always ships, not a separable file, not
strippable via opt-out): `from_config` auto-wiring `try/except` + constructor
`socket=`/`connector_factory=` guard + store/call: mqtt 31, requests 24,
http_server 19, websockets client 16 / server 10, ntp 8 lines — i.e.
**1–2.7 % of each file**, and partly irreducible (you still need *a* way to
accept a pre-connected socket).

**Droppable DI ceremony that forfeits no function, per device:**
`_get_adapter` dispatch (~0.3 KB) + two `_adapters/__init__.py` (0.16 KB) +
wifi `base.py` (0.31 KB) + the five `sockets_factory.py` if inlined
(0.216+0.351+0.548+0.588+0.789 = **2.49 KB**) ≈ **~3.2 KB mpy total** ≈ 0.4 %
of usable flash. The adapter bodies and protocol/`_wire` cores are not DI.

## 2. Import heap (gc.mem_free deltas, absolute KB)

Method: `micropython`/CircuitPython unix binaries; `MICROPYPATH` pointed at a
**fully stripped** copy of every `libraries/*/src` tree (deploy-representative);
`gc.collect()` bracketing each `__import__`; min-of-N over repeats to shed GC
granularity noise (MP frees in multi-KB chunks — treat sub-KB precision as
noise). Binaries:
`.tools/micropython-v1.26.0/ports/unix/build-standard/micropython`,
`.tools/circuitpython-10.2.0/ports/unix/build-standard/micropython`. (MP
discards docstrings at import, so raw-source and stripped-source deltas
converge within noise.)

**Core import (no factory), heap bytes:**

| lib | MP core | CP core |
|---|--:|--:|
| chumicro_sockets | 4960 | 4896 |
| chumicro_wifi | 14752 | 14624 |
| chumicro_mqtt | 42048 | 42240 |
| chumicro_websockets | 44640 | 44608 |
| chumicro_requests | 33760 | 37344 |
| chumicro_ntp | 7520 | 7520 |
| chumicro_http_server | 29856 | 29920 |

**Pure DI-module tax** (`sockets_factory` import with the sockets substrate +
config + timing *preloaded*, so the substrate — needed with or without DI — is
not double-counted). This is the real heap cost of the injection indirection:

| lib | MP pure factory | CP pure factory |
|---|--:|--:|
| chumicro_mqtt | 1216 | 1184 |
| chumicro_websockets | 1120 | 1024 |
| chumicro_requests | 608 | 576 |
| chumicro_ntp | 512 | 512 |
| chumicro_http_server | 1280 | 1248 |

Reading it: importing a networked lib costs 30–44 KB of a 264 KB board's heap;
the DI factory that wires its transport adds **0.5–1.3 KB on top, once**. The
naive "factory delta" (5–13 KB) seen when the substrate isn't preloaded is the
`chumicro_sockets` import that `requests`/`ntp`/`http_server` factories trigger
at module top — needed regardless of DI, not a DI cost.

## 3. Hot-path indirection (static trace + micro-bench)

**mqtt** `runner tick → client.handle(now) → …`:
- CONNECTED (steady state): `handle` → `_check_deadlines` → `_check_keepalive`
  → `_read_inbound` (→ **`self._socket.recv_into(view, cap)` direct**, client.py:1563)
  → `_drain_tx_queue` (→ **`self._socket.send(payload)` direct**, client.py:1484).
  **Zero factory / connector / adapter hops.**
- AWAITING_TRANSPORT (connect / self-heal only): `_advance_connector` →
  `connector.tick(now)`; the connector was built once by
  `self._connector = self._connector_factory()` (client.py:596/1323).

**websockets** `runner tick → client.handle(now)`: while `self._connector` is
live, `connector.tick(now)` (client.py:420); on ready,
`self._socket = self._connector.socket; self._connector = None` (client.py:284–285).
Steady I/O in `_session.py`: **`self._socket.send(chunk)` / `.recv_into(view, cap)`
direct** (lines 465/773/806). Connector discarded after connect.

**DI-attributable hops:** exactly **one extra Python frame per connect** — the
`connector_factory()` closure that a hard-wired build would replace with a
direct `tcp_client_connector(host, port)`. The `_get_adapter()` runtime dispatch
inside `chumicro_sockets` is memoized (once per process) and lives in the
sockets substrate whether or not higher libs use DI. **Per tick: nothing.**

**Micro-bench (unix binaries, 200 000 iters):** a bare
attribute-lookup+bound-method call (the hot-path shape `self._socket.send(x)`)
= **0.059 µs** (MP) / 0.057 µs (CP). One extra frame of closure indirection
= **~0.063 µs** (MP) / 0.073 µs (CP). Desktop is ~30–50× a Pico, so budget
~2–4 µs per frame on-device — paid **once per connect**, invisible against a
DNS/TCP/TLS round-trip. Qualitatively: MP/CP frame setup is cheap; the DI
concern is not cycles, it's whether the code ships at all.

## 4. What DI buys, concretely

**Fakes riding the seams (12), all `__chumicro_test_support__` → never flashed:**
sockets `FakeSocket`/`FakeUDPSocket`/`FakeSocketConnector`; wifi
`FakeWifiAdapter`/`FakeWifi`; websockets `FakeConnection`/`FakeListener`;
requests `_ScriptedCall`/`FakeHttpClient`; http_server `FakeListener`; mqtt
`canned_*_bytes` + `new_client(sock, ticks)` + `drive` helpers; ntp injects a
scripted UDP socket via the factory seam.

**Injection call-sites across the seven host suites** (`grep` of constructor
kwargs): **108 `ticks=`, 72 `socket=`, 63 `connector_factory=`, 13 `listener=`
≈ 256 sites.** Test files touching a seam/fake: sockets 15/16, mqtt 17/20,
requests 18/25, websockets 13/25, http_server 5/8, wifi 3/4, ntp 1/3.

**Where injection does real work vs ceremony:**
- *Real work* — `sockets`/`wifi` `_adapters` (genuinely different substrate per
  runtime: `socketpool`+`radio` on CP vs stdlib `socket` on MP/CPython);
  higher-lib `socket=`/`connector_factory=` enabling **host pytest with no
  board** and **self-heal reconnect** after wifi-drop (the factory is re-invoked
  to rebuild transport); `ticks=` for deterministic time in tests.
- *Real work, strategic* — bring-your-own-transport: `import chumicro_mqtt`
  pulls **0** sockets modules (verified: `chumicro_sockets not in sys.modules`),
  so the lib drops into an existing codebase with a foreign socket.
- *Ceremony* — wifi `_adapters/base.py` ABC (duck typing suffices); the
  `_adapters/__init__.py` shims; the separate `sockets_factory.py` file
  boundary (could be an inline default).

## 5. Alternatives, costed

**(a) Status quo.** Flash: one adapter/device + optional `sockets_factory`
(0.2–0.8 KB mpy). Heap: +0.5–1.3 KB/lib at connect. Hot path: +1 frame/connect.
Testability: **full** (256 sites, 12 fakes, host-only). Integration:
single-lib works. — *Baseline.*

**(b) Hard per-runtime dispatch at import (`sys.implementation` branch).**
Collapse `_get_adapter` + separate adapter modules into one module with a
top-level `if sys.implementation.name == …:` inlining each runtime.
- Flash: saves the shim+dispatch (~0.4 KB) **but ships every runtime's branch in
  one file** — the deploy walker can no longer strip wrong-runtime code by file
  marker → **net ≈ +3–4 KB/device** unless a new dead-branch eliminator is
  added. Heap: negligible. Stack: unchanged.
- Breaks: **host testability of the boundary libs.** Tests swap the `_adapter`
  module binding / import a specific adapter; a hard `sys.implementation` branch
  can't be redirected from CPython pytest → the CP path becomes unreachable off
  a CP unix-port. Higher-lib tests (inject `socket=`/factory) survive; sockets'
  `test_cp_adapter`/`test_mp_adapter` don't.

**(c) Deploy-time static adapter resolution.** The walker **already** selects
per-runtime files, strips `testing.py`, and honors `skip_factories`. Extend it
with an AST pass that rewrites `_get_adapter().m(...)` → `_adapters.<rt>.m(...)`
and inlines the default factory — DI becomes a **host-side illusion**.
- Flash: saves dispatch + shim + the resolved `sockets_factory` (~1–3 KB mpy
  across the stack). Heap: saves the 0.5–1.3 KB/lib factory module + the adapter
  cache global. Stack: −1 frame/connect. **Device cost of DI → ~0.**
- Testability: **preserved** — source keeps every seam; only the *artifact* is
  de-injected. Best-of-both.
- Breaks/cost: new AST-rewrite pass in deploy needing a `strip_source`-style
  parse-tree equivalence guard + line-number preservation; deployed source
  diverges from repo source (slightly harder on-device tracebacks). Engineering,
  not runtime, risk. **Recommended if any device saving is wanted.**

**(d) Hybrid — DI only at the sockets boundary.** Keep injection in
`chumicro_sockets`; higher libs `import chumicro_sockets` directly and call
`tcp_client_connector(...)` inline instead of taking `connector_factory=`;
retain `socket=`.
- Flash: saves the five `sockets_factory.py` (~2.5 KB mpy total), minus ~10
  inlined lines/lib. Heap: saves 0.5–1.3 KB/lib.
- Breaks: the **63 `connector_factory=` test sites** must re-express through
  `socket=` or a boundary fake; **self-heal** (rebuild transport after
  wifi-drop) currently *needs* a factory — without it higher libs either lose
  auto-reconnect or **hard-depend on `chumicro_sockets`**, which **forfeits
  single-library integration** (the exact tension the user named:
  drop-one-lib-into-existing-codebase vs chumicro-is-the-whole-codebase). Small
  flash win, real strategic loss.

## Bottom line for synthesis

On-device, DI costs **~3 KB of flash and ~1 KB of connect-time heap across the
entire networked stack, and zero hot-path cycles** — sub-1 % of a 264 KB /
~800 KB board. It buys host-testability (256 injection sites, 12 never-flashed
fakes) and *single-library integration* (networked libs import no sockets code
until you ask). "Are chumicro libs unique enough to merit DI?" — the flash/heap
ledger says the cost is already near-noise, so the decision is a **product
choice about single-library integration**, not a resource choice. If a device
saving is still wanted, **(c) deploy-time resolution** captures it (~1–3 KB,
~1 KB/lib heap) without giving up the test seams; **(b)/(d)** trade testability
and integration for less than they cost.

## Re-run methodology

- Binaries: `.tools/{micropython-v1.26.0,circuitpython-10.2.0}/ports/unix/build-standard/micropython`.
  Cross-compilers: `.tools/*/mpy-cross/build/mpy-cross` (bytecode v774).
- Strip = `chumicro_deploy.source_minify.strip_source` (the deploy minifier,
  Decision 0090); flash proxy = stripped bytes and `mpy-cross` output.
- Import heap: `MICROPYPATH` → a `strip_source`-processed copy of all
  `libraries/*/src`; `gc.collect()` bracket `__import__`; min-of-N runs.
  Pure-DI-module figure preloads `chumicro_sockets`+`config`+`timing` first.
- Hot path: static trace of `client.py`/`_session.py` (line refs inline above)
  + a 200k-iter `time.ticks_us` micro-bench (bound-method call vs +1 closure
  frame) on both binaries.
- Scratch (temp copies, probes, stripped trees) under
  a scratch job directory outside the repo — not committed.
