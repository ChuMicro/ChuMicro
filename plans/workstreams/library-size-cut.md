# Workstream: library size cut — structural −40% on the heavy trio, fleet-wide diet

Status: **scoped, gated, queued behind CI stand-up** (user calls 2026-07-05: cut depth = structural with all features retained; gate lands NOW at baseline; audit north star inverts for `libraries/`; CI first, then this campaign).

## Why

Libraries ship to boards with ~100–200 K free heap and ~800 K usable flash, yet the 2026-07-05 measured baseline (real Pico W pair, Decision-0090 stripped source, repo mpy-cross) shows:

- Importing all 14 libraries costs **142,672 B of MP heap — 72 % of a Pico W** (rest heap 201,344 B).  The heavy trio (requests + websockets + mqtt) alone ≈ 80 K on either runtime.
- Fleet flash: **145,338 B of mpy** from 349,785 B stripped source (816 KB raw; strip removes 58 %).
- Calibration: chumicro_mqtt ≈ **9× umqtt.simple** (stripped), ≈ 8× (mpy), ≈ 7× (import heap); chumicro_requests ≈ 10× micropython-lib requests.  Honesty note: those references cannot run on CircuitPython at all (`import socket`), so part of our multiple buys CP portability, async, and payload guards — the achievable band with features retained is judged 4–6×, not 1×.
- The growth mechanism is a ratchet: budgets exist only for the unstripped test lanes, and each feature bump is individually "justified" (live specimen: 2026-07-05's attempted mqtt 240 K → 256 K bump for one new method — rejected same day by splitting suite files instead).

## Decisions taken (2026-07-05)

1. **Cut depth: structural, target ≈ −40 % on the heavy trio; every feature stays.**  Deep feature-triage and minimal-first rewrites were considered and deferred.
2. **Size gate at today's baseline** — committed `size-budgets.toml` (per-library stripped-bytes + mpy-bytes ceilings, +small noise margin), fast host-side `check-size` preflight phase, ceilings ratchet DOWN as cuts land, raises need measured justification in the commit.  On-device import heap is a sweep-layer measurement, not a preflight gate.  (Built 2026-07-05, see gate commit.)
3. **Audit north star inverted for `libraries/`**: audit-embedded's lens (flash, import RAM, allocations, class/def/exception count, string weight) is primary; standards lenses advisory there.  Standards remain primary for scripts/, workbench/, webui/, skills.  (Landed 2026-07-05, see inversion commit.)
4. **Sequencing: CI stands up first**, so the whole campaign runs with CI + the size gate protecting it.

## Baseline (2026-07-05, per library: stripped B / mpy B / MP import heap B / shipped classes / defs)

| library | stripped | mpy | MP heap | classes | defs |
|---|--:|--:|--:|--:|--:|
| websockets | 77,027 | 31,048 | 26,352 | 24 | 131 |
| mqtt (pre-0.26.0) | 57,886 | 20,821 | 25,264 | 16 | 89 |
| requests | 54,845 | 20,254 | 27,504 | 15 | 99 |
| http_server | 47,654 | 19,533 | 17,984 | 19 | 91 |
| sockets | 33,494 | 16,276 | 4,128 | 15 | 91 |
| runner | 19,895 | 6,811 | 13,888 | 8 | 42 |
| wifi | 13,354 | 6,919 | 3,888 | 6 | 39 |
| kvstore | 12,958 | 7,171 | 3,776 | 10 | 41 |
| msgpack | 10,221 | 4,611 | 5,312 (CP: 624 — native module) | 0 | 18 |
| ntp | 7,025 | 3,414 | 4,288 | 3 | 16 |
| logging | 5,070 | 2,388 | 3,984 | 3 | 22 |
| config | 4,702 | 2,609 | 2,576 | 4 | 12 |
| timing | 4,226 | 2,575 | 3,424 | 3 | 18 |
| compat | 1,428 | 908 | 240 | 1 | 3 |

The full measurement report (methods, dep-closure ordering, CP columns, calibration rows) lives in the 2026-07-05 session record; `check-size` re-derives current numbers on every preflight.

## Cut targets (what the bytes say — comments are NOT on this list; 0090 already strips them)

- **Exception taxonomies**: requests carries 6 exception classes in `_wire.py`, websockets 7, http_server 9 — each a type object + qstrs.  Consolidate toward one base + code/reason field per library where handling doesn't genuinely fork.
- **Class/def diet**: websockets ships 24 classes / 131 defs; state-holder micro-classes and one-call helpers merge.  Every def is a code object + qstr; every class a type + dict.
- **File merges**: per-module import overhead; sockets ships 9 files, wifi 7.
- **Error-string diet**: f-string prose lives in flash post-strip; long diagnostic messages shrink to terse code-bearing forms (the guide can carry the prose).
- **Biggest single files first**: `mqtt/client.py` (40 K stripped, 56 defs), `requests/client.py` (25 K), `requests/_wire.py` (24 K), `websockets/_wire.py` (27 K), `websockets/_session.py` (22 K), `http_server/server.py` (22 K).
- **runner MP/CP asymmetry**: 13,888 B MP import vs 6,224 B CP — find the MP-only weight.
- **Speculative/ceremonial API**: pure-passthrough properties, ABC-ish base shells (`_adapters/base.py`), knobs without consumers — audit-library already flags these; now they cost score.
- **NOT dead weight (verified, leave alone)**: `testing.py` fakes never ship (both deploy walkers skip the `__chumicro_test_support__` marker); msgpack on CP binds the native module (624 B) — keep that path.

## Density analysis (2026-07-05 follow-up) — reframes the levers

Bytes-per-def says the fleet is not fat per feature: chumicro_requests is within 12 % of ulib-requests' stripped density (553 vs 468 B/def) and identical in mpy density (204 = 204); mqtt runs ~30 % denser per def but ships 89 defs to umqtt.simple's 13.  The 8–10× multiple is feature count.  Raw-line criticism also overstates shipped weight ~5.6× (816 KB raw → 145 KB mpy; fakes never ship, strip removes 58 %).  So the campaign's highest-leverage moves are structural and behavior-free, in this order:

1. **Ship `.mpy`, not stripped `.py`** — fleet flash drops 350 KB → 145 KB with zero library edits; `prepare-mpy-cross` exists, the gap is the deploy walker.  (Deploy-pipeline change, campaign phase 0.)
2. **Lazy `__init__` re-exports** — websockets already lazy-loads via module `__getattr__`; **mqtt, requests, http_server eagerly import their 25–40 KB client/server modules at package import**.  Applying websockets' pattern defers the big files until first touch: same API, pay-per-use heap, attacks the real scarcity (import RAM) directly.  (Tiny per-library diffs, campaign phase 1.)
3. **Consolidate the four parallel `_wire.py` layers** — requests/_wire and http_server/_wire both parse HTTP; websockets/_wire parses the upgrade handshake.  `/audit-integration` seam, behavior-preserving.
4. **Class/def/exception diet + error-string diet** — the original structural list, now ranked after the three above.
5. **Frozen-bytecode option for known deployments** — firmware-level; the mpy table is its input.  Future.

Success metric refined accordingly: per-library **import heap** and **mpy flash** (what boards feel), gated by check-size; the −40 % stripped-bytes trio target stays as the structural-diet goal but the levers above may beat it on the metrics that matter without touching a feature.

## Fragmentation + import-floor measurements (2026-07-05, real Pico W, MP, stripped .py)

Bench answer to "does lazy loading help or hurt fragmentation":

- **On-device compilation is fragmentation-tolerant.**  mqtt imported into a heap shredded to ~15 K largest contiguous block; websockets and kvstore+ntp into ≤10 K holes.  The lexer streams and the parser allocates small chunks — a lazy import essentially never fails *because* of fragmentation.
- **The import floor is total transient headroom and tracks the largest single file, not library size.**  mqtt: 28.0 K persistent cost but a ~92–97 K free-heap floor (client.py = 40.4 K stripped).  websockets: 29.1 K persistent, ~66–76 K floor (_wire.py = 27.3 K).  Rule of thumb: floor ≈ persistent + ~1.6× largest file's stripped bytes.
- **Lazy `__getattr__` re-exports (lever 2) are confirmed pure-win when first touch is at boot** (same packing as eager, pay-per-use).  Mid-runtime first touch has two costs: the full floor must be free at that moment, and the ~28 K of immovable objects scatter into existing holes (no compacting GC).  Ship the pattern with one line of doc guidance: *instantiate clients during startup*.
- **New top-tier lever: split `mqtt/client.py`** (largest file in the fleet by a wide margin) into 3–4 modules along existing class boundaries (MQTTClient / in-flight+pending tracking / ProtocolState+inbound types).  While we ship `.py` source, every boot recompiles on-device and that one file sets a ~95 K floor — half a Pico W's heap.  Splitting drops the floor toward ≤70 K with zero API change.  Next candidates, already near-tolerable: requests/client.py (25.4 K), websockets/_wire.py (27.3 K).

## Phase 1 SHIPPED (2026-07-05 evening) — lazy `__init__` re-exports

mqtt / requests / http_server now defer their heavy client/server module via websockets' PEP-562 `__getattr__` pattern (cheap `_wire` symbols stay eager).  Measured on the MP unix proxy (fresh interpreter, full dep closure; websockets as unchanged control):

| library | package-import heap before | after | delta |
|---|--:|--:|--:|
| mqtt | 40,992 B | 15,616 B | **−61.9 %** |
| requests | 38,592 B | 19,808 B | **−48.7 %** |
| http_server | 32,800 B | 14,496 B | **−55.8 %** |

Cost: ~+180 B stripped per `__init__` (the `__getattr__` body), within budget margins — no ceilings bumped.  All lanes green (1080 CPython / 2070 MP / 2070 CP); PEP-562 smoke-verified on both pinned unix binaries.  Guides gained one startup-construction line each.  Real Pico W import-heap numbers land at the next bench sweep.  Remaining phases: 0 (ship `.mpy` from the deploy walker), the mqtt `client.py` split (import-floor lever), then the structural diet.

## Campaign shape (after CI)

Per library, heavy trio first (websockets → requests → mqtt → http_server): an audit-embedded-led cut pass → apply → full preflight + on-device sweep + `check-size` ratchet-down commit.  Bakes re-run on mqtt after its pass (the negative-suite fakes pin behavior).  Fleet-wide passes (exception consolidation, error-string diet) follow as cross-library sweeps.  Success = trio ≈ −40 % stripped/mpy with all features and all tests green, budgets ratcheted to the new floor.
