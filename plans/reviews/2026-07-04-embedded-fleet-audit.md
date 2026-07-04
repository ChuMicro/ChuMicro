# Embedded fleet audit — "is any code longer than necessary; are there excessive files?"

Date: 2026-07-04
Scope: `libraries/{timing,config,msgpack,kvstore,logging,wifi,ntp,sockets,requests,http_server}/src`
— ten libraries under the `/audit-embedded` rubric (flash footprint, import-time
RAM, hot-path allocation, fragmentation, runtime quirks, docs-vs-code drift).
runner + websockets (2026-06 deep review) and mqtt
(`2026-07-04-mqtt-bloat-review.md`) are EXCLUDED from deep re-reads but
INCLUDED in the fleet file-structure table. READ-ONLY pass; no commits.

Method: stripped bytes via the real deploy minifier
(`chumicro_deploy.source_minify.strip_source` — the same tool the mqtt bloat
review used); docstring density via AST walk; import-time heap via fresh
MicroPython v1.26.0 unix-port processes
(`.tools/micropython-v1.26.0/ports/unix/build-standard/micropython`),
`gc.mem_alloc()` bracketed per the `scripts/benches/_harness.py` idiom; consumer
greps across BOTH repos (this one + `ChuMicro-Workspace-Template`), excluding
each library's own tests when judging "real consumer."

HEAD pinned: `8c45a766686234ae0eaf8123dde516a58a81ef13` (branch `main`). The
working tree was clean at measurement time; concurrent agents began editing
`libraries/wifi` and `libraries/mqtt` mid-pass, so every wifi/mqtt number below
was re-derived from `git show HEAD:` and matches the clean-tree measurement
exactly. Line references for wifi are HEAD-pinned.

---

## Honest denominators, up front

Two denominators run through everything below (the mqtt bloat review's
lesson):

1. **Docstrings are not flash on real boards.** Decision 0090 strips
   docstrings + comments at deploy. The fleet is 34 % doc lines; stripping
   takes 848 KB of raw `.py` to 370 KB. Doc density findings charge to
   **unix-test-lane heap and reader time**, not device flash — except for
   `.py`-side `mip`/`circup` installs, which do ship raw source.
2. **Import-heap numbers include the dependency subtree.** `import
   chumicro_requests` at 40 KB is requests + sockets + timing + runner-shape
   deps, not requests alone. Comparing that number against requests' own line
   count would overclaim; the honest comparison is subtree-vs-subtree.

---

## 1. Fleet file-structure table

Measured at HEAD. `code` ≈ total − blank − comment − docstring (approximate to
±2 on files whose docstrings interleave); `strip` = bytes after
`strip_source` (what a real-board deploy flashes); `imp` = retained heap after
`import chumicro_<lib>` + `gc.collect()` in a fresh MP 1.26 unix process
(includes dep subtree); `<50L` = files under 50 lines.

| library | files | lines | code | doc (density) | raw B | strip B | <50L | imp B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| timing | 5 | 379 | 120 | 171 (45 %) | 14 548 | 5 418 | 1 | 4 512 |
| config | 3 | 270 | 136 | 63 (23 %) | 9 083 | 4 899 | 0 | 4 768 |
| msgpack | 2 | 579 | 227 | 188 (32 %) | 21 049 | 10 221 | 0 | 8 608 |
| kvstore | 8 | 865 | 335 | 312 (36 %) | 31 309 | 14 797 | 2 | 14 496 |
| logging | 3 | 441 | 159 | 189 (43 %) | 15 771 | 6 128 | 1 | 6 464* |
| wifi | 8 | 1 121 | 340 | 505 (45 %) | 42 849 | 15 239 | 2 | 17 536 |
| ntp | 3 | 452 | 157 | 183 (40 %) | 17 501 | 7 070 | 2 | 7 680 |
| sockets | 10 | 3 013 | 874 | 1 406 (47 %) | 124 239 | 40 966 | 1 | 3 968† |
| requests | 6 | 3 494 | 1 602 | 1 141 (33 %) | 142 829 | 65 392 | 1 | 40 128 |
| http_server | 6 | 2 649 | 1 228 | 755 (29 %) | 105 620 | 48 535 | 0 | 30 688 |
| runner ‡ | 5 | 1 387 | 452 | 566 (41 %) | 61 181 | 21 265 | 2 | 16 224 |
| websockets ‡ | 7 | 3 722 | 1 882 | 953 (26 %) | 148 528 | 79 352 | 0 | 44 704 |
| mqtt ‡ | 5 | 3 087 | 1 377 | 948 (31 %) | 133 973 | 59 767 | 2 | 42 464 |
| **fleet** | **71** | **21 459** | **8 889** | **7 380 (34 %)** | **868 480 (848 KB)** | **379 049 (370 KB)** | **14** | — |

`*` logging's *pre-collect* import cost is 18 272 B — see Finding L-1.
`†` sockets is cheap to import because its runtime adapters lazy-load
per-function (the correct pattern); the adapters land on first use.
`‡` fleet-table-only; deep re-reads excluded per scope.

**Per-file detail** — files under 50 lines (FAT cluster: each costs one full
512 B / 1 024 B cluster regardless of content):

| file | lines | strip B | role |
|---|---:|---:|---|
| timing/`__init__.py` | 17 | 247 | re-export |
| kvstore/`__init__.py` | 40 | 245 | re-export |
| kvstore/`_backends/__init__.py` | 6 | 6 | package marker (docstring only) |
| logging/`__init__.py` | 49 | 397 | re-export |
| wifi/`__init__.py` | 46 | 229 | re-export |
| wifi/`_adapters/__init__.py` | 10 | 10 | package marker |
| ntp/`__init__.py` | 16 | 145 | re-export |
| ntp/`sockets_factory.py` | 18 | 191 | opt-in DI wiring |
| sockets/`_adapters/__init__.py` | 9 | 9 | package marker |
| requests/`sockets_factory.py` | 31 | 356 | opt-in DI wiring |
| runner/`__init__.py` | 42 | 516 | re-export |
| runner/`generators.py` | 47 | 304 | re-export shim |
| mqtt/`__init__.py` | 39 | 547 | re-export + gc boundaries |
| mqtt/`sockets_factory.py` | 43 | 694 | opt-in DI wiring |

**File-count verdict:** no consolidation warranted. The 14 sub-50-line files
split into three structural classes, none cuttable:

- **Package markers** (3 files, 6–10 stripped bytes each): required by the
  import machinery for the `_adapters`/`_backends` subpackages. ~3 clusters of
  waste total (~1.5–3 KB at 512 B–1 KB clusters) — the price of keeping
  runtime-specific adapters out of the always-loaded path. Cheaper than the
  alternative (eager cross-runtime imports crash the wrong runtime).
- **Re-export `__init__.py`s**: the workspace convention; every library needs
  one.
- **`sockets_factory.py` DI shims** (4 in-scope + mqtt/websockets): these are
  deliberately *separate* files so apps that inject their own transport never
  pull `chumicro_sockets` into the deploy graph (each file's own docstring
  states this; ntp's README repeats it). 10+ sister-repo projects import them.
  The naming drifts across libraries (`chumicro_sockets_factory` vs
  `chumicro_sockets_connector_factory` vs `chumicro_sockets_listener`, with and
  without a `config` positional) — an `/audit-integration` note, not fleet
  fat.

Total fleet cluster overhead: 71 files ≈ 36 KB at 1 KB clusters against
370 KB of stripped source (~10 %) — dominated by structurally necessary
files, not by gratuitous splits. The one historical bad pattern (mqtt's
four-file `_wire` split, ~16 KB waste) was already merged.

---

## 2. Docstring density triage

Fleet doc density is 34 % (7 380 of 21 459 lines). Per the rubric, >30 % on a
*small* library flags a trim candidate — but with Decision 0090 both numbers
matter:

| claim | .py-install / test-lane | real-board deploy (stripped) |
|---|---:|---:|
| fleet prose cost | 489 KB of raw source is doc+comment+blank | **0 flash bytes** |
| worst-density module | sockets/`__init__.py` 71 % (340 of 476 lines) | strips to 3 379 B |
| runner-up | msgpack/`__init__.py` 65 %, timing/`waits.py` 61 % | 1 110 B / 1 098 B |

High-density modules and their character:

- `sockets/__init__.py` — 476 lines, 40 code. This is the package's entire
  public API (13 functions incl. 4 SSL-context builders) with a 43-line module
  docstring and heavy per-function docs. The rubric's ">100-line `__init__`
  doing real work" flag technically trips (cohort median is ~42 lines), but
  the *work* is thin — it is on-ramp documentation on the fleet's most
  imported seam. Splitting would add files (cluster cost) to save nothing on
  device. **KEEP; density-only.**
- `timing/waits.py` (61 %), `timing/deadline.py` (56 %), `wifi/config.py`
  (57 %), `wifi/_adapters/base.py` (57 %), `msgpack/__init__.py` (65 %) —
  contract-documentation on small surfaces. All strip to ≤1.9 KB.
- The fleet's docstrings cost the **unix test lanes** real heap (they import
  unstripped), and `.py`-side `mip`/`circup` installs do flash them. A
  `/audit-comments` density pass on the >50 % modules would save ~15–20 KB of
  raw source fleet-wide; zero real-board flash. **Not a structural finding.**

---

## 3. Fleet-wide mechanical sweeps (all ten in-scope libraries)

All run at HEAD across `libraries/{ten}/src`:

- **Wrapper-doubling** (`def \w+_raw(` / `_unencoded(` / `_unprefixed(` /
  `raw_\w+(`): **one hit** — `kvstore/testing.py:107 raw_payload`, a
  test-support property with no unsuffixed sibling (CPython-only, never
  flashed). **Not wrapper-doubling. Fleet clean.**
- **`__slots__`**: zero hits. Clean (prior audits removed them).
- **`from typing` / `from __future__`**: zero hits in `src/`. Clean.
- **Bare `raise TimeoutError`**: zero hits. Clean.
- **Runtime markers**: every runtime-specific import
  (`socketpool`/`machine`/`esp32`/`wifi`) sits in a file carrying the right
  `__chumicro_runtimes__` marker (9 marked files verified). Clean.
- **`gc.collect()` placement**: every hit is the sanctioned import-boundary /
  post-handshake pattern — **except logging** (Finding L-1). No hot-path
  `gc.collect()` anywhere.

---

## 4. Import-time RAM spot measurement

Fresh MP 1.26 unix process per library; `gc.collect(); mem_alloc()` before,
`import`, then measured both pre-collect (peak incl. compile scratch) and
post-collect (retained):

| library | pre-collect B | retained B | scratch reclaimed |
|---|---:|---:|---:|
| timing | 4 800 | 4 512 | 288 |
| config | 4 896 | 4 768 | 128 |
| msgpack | 9 280 | 8 608 | 672 |
| kvstore | 14 656 | 14 496 | 160 |
| **logging** | **18 272** | **6 464** | **11 808** |
| wifi | 17 568 | 17 536 | 32 |
| ntp | 9 184 | 7 680 | 1 504 |
| sockets | 5 216 | 3 968 | 1 248 |
| requests | 40 416 | 40 128 | 288 |
| http_server | 31 232 | 30 688 | 544 |
| runner | 16 288 | 16 224 | 64 |
| websockets | 45 664 | 44 704 | 960 |
| mqtt | 45 376 | 42 464 | 2 912 |

The near-zero "scratch reclaimed" column on 12 of 13 libraries is the
end-of-`__init__.py` `gc.collect()` doing its job (field-reality: +33 KB
contiguous on Pi Pico W for the mqtt chain). The 11.8 KB logging outlier is
Finding L-1.

### Finding L-1 — logging is missing the import-boundary `gc.collect()` — HIGH

`ram-imp` `libraries/logging/src/chumicro_logging/__init__.py:49` (EOF)

Every other library in the fleet ends its `__init__.py` with `import gc` +
`gc.collect()` (the load-bearing pattern from the mqtt TLS-fragmentation hunt;
field-reality measured removing it at −1 117 blocks ≈ −18 KB contiguous).
logging does not — and the measurement shows exactly the predicted signature:
18 272 B at import, of which **11 808 B (65 %) is unreclaimed compile
scratch** left interleaved with the library's persistent objects until the
next allocation-pressure event. logging is a decoration library no chumicro
library imports (policy, verified by grep), but apps import it directly, and
on a 256 KB board that scratch sits in the worst possible place — between the
app's early long-lived state.

Fix: 2 lines, mirroring the other twelve libraries. This is an *add*, not a
cut, but it is the single largest measured import-RAM defect in scope.

---

## 5. Per-library findings

### timing — clean; one zero-consumer function on the eager path

- **CUT-NOW** `flash`/`ram-imp` `deadline.py:56` — `earliest()` has **zero
  consumers** anywhere: grep across demos, all libraries, timing's own
  examples, and every sister project/example finds no real call (the 3 raw
  hits are an unrelated http_server test method name, an mqtt comment, and a
  test docstring); only `tests/test_deadline.py` exercises it. It rides the
  eager import path (`__init__.py` re-export), so it charges every board that
  imports timing, and its varargs tuple is the module's only per-call
  allocation. ~8 code lines + docstring + `__all__` entry.
- **KEEP-cheap (tests-only method surface)** `flash` —
  `Deadline.remaining()` (`deadline.py:46`), `Deadline.reset()` (`:51`),
  `Rate.reset()` (`:126`), `Signal.clear()` (`waits.py:51`): all tests-only
  by grep, all 1–3 lines, all coherent with their value objects' documented
  lifecycles. Bundle-review if timing ever needs a diet.
- **Protocol note** — `Signal.ready()`/`next_deadline()` look dead to a
  literal grep but are driven by the runner's duck-typed
  `getattr(wait, "ready", None)` seam (`runner/_generator.py:148,217`).
  KEEP; recorded so a future audit doesn't cut them on a grep.
- **Hot path clean** `heap` — ticks/deadline/waits per-tick paths are pure
  masked-int arithmetic, zero allocation; `wait_for`'s "allocates nothing per
  tick" docstring claim verified against the code.

**Verdict: clean once `earliest()` is cut.**

### config — cleanest in scope

- **BUNDLE (unused public export)** `imports` `runtime.py:9` +
  `__init__.py:52-55` — `DEFAULT_RUNTIME_CONFIG_PATH` is publicly exported
  through a dedicated PEP-562 lazy `__getattr__` branch with zero external
  consumers (config's own tests only; the internal default read at
  `runtime.py:24` doesn't need the export). Drop from `__all__` + the lazy
  branch at the next config touch; keep the module constant.
- **CLEAN** — no dead cap-knobs; `load_section`'s one real consumer
  (`wifi/config.py:110-111,145-146`) overrides both `required=`/`optional=`
  (earning kwargs, not demote candidates); accessors allocation-free; the
  per-key f-string in `load_section` runs once per section at boot, not on a
  tick.

**Verdict: clean.**

### msgpack — clean; carries the fleet's reference hot-path patterns

- **CLEAN (positive findings)** `heap` — `_pure.py:17-31` `_append_packed` +
  `_ZERO2`/`_ZERO4` pre-extended `pack_into` (the field-reality encoder
  pattern, −50 % per pack); `str(data[a:b], "utf-8")` decode at
  `_pure.py:214,273,280` (the −25 % pattern); error-guidance dict built
  inside the error path, not at module top (`_pure.py:309`). This library is
  the reference implementation for both patterns.
- **KEEP (inherent, flagged honestly)** `heap` — `_decode`'s
  `(value, new_offset)` 2-tuple per decoded element and `unpack_from`'s
  1-tuple per multi-byte scalar are the decode path's real allocation cost;
  removing them means offset-as-state, a large refactor no consumer demands.
  The 2026-07-03 hot-path audit reached the same verdict (one-shot API; the
  steady-buffer pattern legitimately doesn't apply).
- **KEEP (PyPI parity) / TRIM docstrings** `flash`/`docs` — stream
  `pack()`/`unpack()` (`_pure.py:433,448` + native twins in `__init__.py`)
  have zero device consumers (only the example that demos them); they stay
  for msgpack 4-function API parity (SKILL §1 exception 1), but their
  ~15-line caveat docstrings are the module's one trim target.

**Verdict: clean.**

### logging — the code is fine; the library has no adopter

- **ESCALATE (workspace decision)** `abstraction` — `chumicro_logging` has
  **zero import sites in either repo** outside its own tests and its own
  example: grep across every demo, library, script, webui, and all sister
  projects/examples/packages finds no `chumicro_logging` import (apparent
  hits are false positives — http_server's `_StreamHandlerError`,
  `runner.handler_errors`). Decision 0042's policy is "no library depends on
  logging; apps wire `logger=`" — but no app wires it either. 441 lines /
  6.1 KB stripped of 100 %-speculative surface. Keep/defer is a workspace
  call, not an in-lib cut.
- **HIGH (see Finding L-1)** `ram-imp` `__init__.py:49` — missing
  import-boundary `gc.collect()`; 11.8 KB measured unreclaimed compile
  scratch, the fleet's largest import-RAM defect.
- **BUNDLE** `heap` `core.py:141` — `Logger.log` allocates a
  handlers-snapshot `tuple(self._handlers)` on every emit past the level
  gate, guarding add-/remove-during-emit — exotic on a single-threaded
  cooperative runtime. Iterate directly (or snapshot only when >1 handler)
  when the library gains a consumer.
- **KEEP-cheap** — tests-only introspection (`dropped`/`buffered`/`capacity`
  accessors, `handlers` property); `BufferedHandler.check`/`handle` verified
  allocation-free; `StreamHandler.emit`'s two-write shape (avoiding a
  `line + "\n"` concat) is correct.

**Verdict: code clean, adoption zero — the finding is the library, not its
lines.**

### kvstore — clean; prior regressions verified fixed

Real consumers (both repos, tests excluded): 3 files
(`libraries/kvstore/examples/boot_counter.py`, workspace functional-test
fixture, sister `projects/example_sensor/app.py`); surface touched:
`KVStore(backend="auto")`, `get`, `__setitem__`/`__getitem__`, `commit`,
`commit_if_changed`, `bytes_used`, `capacity`, `backend_name`.

- **CLEAN (regression verified fixed)** `ram-imp`
  `_backends/mp_nvs.py:43,51,73` — the field-reality "16 KB pinned buffer"
  finding is resolved at HEAD: `DEFAULT_CAPACITY = 512`, `__init__` allocates
  nothing, the `bytearray(capacity)` read buffer is transient inside `load()`
  (construction + explicit `reload()` only, never the commit hot path).
- **CLEAN (no dead cap-knobs)** — every `capacity` is read and enforced:
  `core.py:233`, `memory.py:47`, `cp_nvm.py:84,104`, `mp_nvs.py:73,96`,
  `mp_littlefs.py:88`. The mqtt `max_message_bytes` pattern has no kvstore
  equivalent.
- **KEEP (backend honesty)** `abstraction` `core.py:69-89` — all four backends
  reachable via runtime auto-detect (cp→nvm, mp+esp32→nvs, mp→littlefs,
  cpython→memory); none orphaned. Backends lazy-import inside
  `_resolve_backend` — correct, keeps `esp32`/`microcontroller` off the
  cross-runtime import graph. The explicit string selectors
  (`"memory"`/`"nvm"`/`"nvs"`/`"littlefs"`, `core.py:98-110`) have zero real
  consumers (everyone uses `"auto"`) but are the documented escape hatch —
  cheap, keep.
- **KEEP (tests-only dict surface)** `flash` `core.py:251-293` —
  `__delitem__`/`__contains__`/`__iter__`/`__len__`/`keys`/`items`/`values`/
  `pop`/`clear`/`update` are exercised only by kvstore's own tests. A mapping
  type earning its shape; each is 1–3 lines. Cutting would save ~40 stripped
  code lines but break the "it's a dict" contract. Bundle-review if kvstore
  ever needs a diet; not now.
- **DOCS** `docs` `testing.py:3` — module docstring claims "Downstream
  consumers import `FakeKVStore` rather than inventing ad-hoc mocks"; grep
  finds **zero** importers outside kvstore's own tests in either repo. Soften
  the claim (or land a consumer). No device cost (test-support never
  deploys).
- **Hot path clean** `heap` — `commit_if_changed` short-circuits on
  `not self._dirty` (`core.py:218`), so the every-tick schedule allocates
  nothing while clean; the per-dirty-commit `packb` is inherent. No
  front-of-buffer churn anywhere.

**Verdict: clean.** One docstring claim to fix; nothing to cut.

### ntp — clean but one dead kwarg

Real consumers: `libraries/ntp/examples/ntp_query.py` +
`functional_tests/test_real_ntp.py`; surface touched: `from_config`, `query`,
`check`, `handle`, `.socket`, result `.done`/`.error`/`.unix_seconds`.

- **CUT-NOW** `flash` `sockets_factory.py:11,18` — the `broadcast: bool =
  False` kwarg is a dead pass-through: its only non-default use is
  `tests/test_ntp_pytest.py:45`; the one real caller passes `radio=` only, and
  the docstring itself concedes "NTP itself doesn't need it." Anyone wanting
  broadcast calls `chumicro_sockets.udp_socket(broadcast=True)` directly.
  Savings: ~4 code lines + kwarg surface + the README row that documents it
  (`libraries/ntp/README.md:59`). Break: one test updates. Free under 0092.
- **CLEAN (regression verified fixed)** `shape` `core.py:25-38` — the four
  protocol constants are now public `const()`-wrapped (`NTP_TO_UNIX =
  const(2208988800)`, `PACKET_SIZE`, `CLIENT_FIRST_BYTE`, `SERVER_MODE`) per
  the field-reality underscore-rename rule.
- **Hot path clean** `heap` `core.py:283,342,375,66-113` — 48 B recv buffer
  pre-allocated once and reused; parse via byte-indexing on a memoryview (no
  `bytes(view[a:b])`, no struct); error f-strings only on the raise path.
  Optional micro-shape: cache `memoryview(self._recv_buffer)` in `__init__`
  (`core.py:391` builds one per successful datagram — once per query, not per
  tick; negligible).
- **KEEP** `abstraction` — `cancel()` (`core.py:407`) and `busy`
  (`core.py:285`) have zero real consumers but are small, documented runner
  affordances. `sockets_factory.py` as a separate 18-line file is deliberate
  (keeps `chumicro_sockets` out of custom-transport deploys) and live.
- **DOCS (adjacent, one line)** `docs` `sockets/testing.py:198` — a docstring
  example constructs `NTPClient(sock=...)`; the real kwarg is `socket=`. A
  cold reader copy-pasting hits `TypeError`. One-word fix, belongs to sockets.

**Verdict: clean once `broadcast=` is cut.**

### wifi — one dead method; otherwise clean

Wifi `file:line` refs are **HEAD-pinned** (`8c45a76`) — a concurrent agent is
editing wifi's working tree; measurements above were re-derived from
`git show HEAD:` and match the clean-tree read exactly.

- **CUT-NOW** `flash` `_adapters/base.py:77`, `_adapters/cp.py:94`,
  `_adapters/mp.py:238`, `testing.py:79` — `WifiAdapter.disconnect()` is
  implemented in all three adapters plus the base stub and called by
  **nobody**: `WifiService` never invokes it (the reconnect path uses only
  `is_linked`/`connect`), and no demo/example/script/sister-project calls
  `wifi.adapter.disconnect()`. ~10 code lines + 4 docstrings across 4 files.
  Break: none.
- **CLEAN (no dead cap-knobs)** — all six `WifiConfig` knobs are read:
  `connect_timeout_ms` (`service.py:230`, `cp.py:83`),
  `reconnect_backoff_start_ms` (`service.py:106,290`),
  `reconnect_backoff_max_ms` (`service.py:273`), `reconnect_max`
  (`service.py:258-259`), `power_save` (`mp.py:155`, CYW43-only by documented
  design), `hostname` (`cp.py:63`, `mp.py:152`).
- **KEEP (adapter shape honest)** `abstraction` — `_select_adapter()`
  (`service.py:43-63`) lazy-imports one adapter per runtime at construction;
  `base.py`'s class-attr defaults (`connect_blocks`, `radio`) are load-bearing
  (`service.py:223` reads `connect_blocks`), so the base class is not
  ceremony.
- **Hot path clean** `heap` — `check()`/`handle()` steady state has no
  f-strings, no dict/list literals, no logging, no status-dict rebuild.
- **DOCS** `docs` `testing.py:126` — `FakeWifi` docstring claims downstream
  consumers import it; grep finds zero outside `libraries/wifi/`. Same
  false-claim shape as kvstore's `FakeKVStore`. No device cost
  (test-support).

**Verdict: clean once `disconnect()` is cut.**

### sockets — lean core, one latent heap-DoS, a convenience layer worth naming

The cheap import (3 968 B for a 3 013-line library) is real and structural:
`_get_adapter()` (`__init__.py:86-105`) resolves the runtime adapter on first
factory call and memoizes; nothing substrate-specific loads at import.
`_ca_bundle.py` is likewise already optimal — it is a *loader* that reads the
sibling `.der` file into a function-scoped buffer dropped on return
(`_ca_bundle.py:57-76`), not a module-pinned bytes literal.

- **HIGH (latent heap-DoS)** `heap` `generators.py:269` — `recv_exact`
  allocates `bytearray(byte_count)` with no upper bound (`:266` only checks
  `> 0`). Its sibling `recv_until` *requires* `max_bytes` precisely to bound
  peer-driven allocation (`:178,239`); `recv_exact` has no equivalent. Today
  it is latent — `recv_exact` has **zero non-test consumers** — but the first
  caller that wires a peer-controlled length (Content-Length, remaining-length)
  into it gets an unbounded allocation on a 256 KB board. Fix: add a
  `max_bytes`-shaped cap or a docstring contract, before a consumer appears.
- **BUNDLE (convenience layer, name it honestly)** `flash`
  `generators.py` (288 lines) + `waits.py` (76 lines) — 364 lines /
  ~4.2 KB stripped that ship to flash, and **none of the five downstream
  network libraries import them**: requests/http_server/mqtt/websockets roll
  their own recv/send loops; consumers are demos + runner examples only.
  `waits.py` has exactly one non-test importer (`generators.py:40`) — a tight
  A→B chain; merging `waits.py` into `generators.py` drops a file + cluster.
  Within `generators.py`, `recv_exact` (`:243`) is tests-only surface.
  Keep the layer (documented app convenience) but stop treating it as
  foundational plumbing; fold `waits.py` in at the next sockets wave.
- **BUNDLE (tests-only public surface)** `flash` `__init__.py:253`
  `ssl_context_with_cert_and_key` (bytes variant — zero real consumers;
  http_server uses the `_paths` variant; on CP it only raises) and
  `__init__.py:445` `set_default_ca_bundle` (zero consumers outside sockets'
  own tests). Each is a deliberate escape hatch; revisit at the next wave.
- **KEEP** `abstraction` — `ssl_context_no_verify` (`__init__.py:427`) has
  real sister-repo diagnostic consumers (`mqtt_bake*`, `mqtt_tls_probe`,
  `frag_probe`). `listener(backlog=4)` (`__init__.py:186`) is never
  overridden outside tests — weak demote-to-constant candidate.
- **Hot path clean** `heap` — `send_all`/`recv_until` re-slice a single
  memoryview only on progress; connector `check`/`handle`/`io_interest`
  allocate nothing steady-state; adapter recv paths are all caller-buffer
  (`recv_into`/`readinto`), no sender-sized allocation. The
  `_adapters/cpython.py:168` per-tick `select.select([],[sock],[],0)` list
  churn is host-only (never a device path) — noted, not flagged.

**Verdict: core is lean and correct; the punch items are one latent
allocation guard and honest labeling of the convenience layer.**

**Cross-repo evidence caveat (API-churn signal, same shape as the mqtt
review's):** several sister-repo projects reference a *removed* sockets API
(`tcp_client_socket` / `tls_client_socket` / `tcp_listening_socket` /
`pollable_of` in `frag_probe`, `runner_reactor_probe`, `two_board_test/server`)
and a nonexistent `WifiConfig.from_dict` (`projects/wifi_only/app.py:63`).
Those files would fail at runtime; zero-consumer claims above lean on the main
repo plus sister files that track the current API. Fix belongs to the template
repo; noted as read-only evidence that the sockets/wifi construction surface
has churned under its most-visible consumers.

### requests — clean; the "clean" is itself the finding

The two highest-yield dimensions come back clean, with the grep evidence to
back the verdict:

- **CLEAN (no dead cap-knobs)** — every knob has a functional threshold read,
  not just a message-string interpolation: `_max_body_bytes`
  (`_wire.py:994,1084,1181,1235`), `_max_header_bytes` (`_wire.py:803`),
  `_recv_budget_per_tick` (`client.py:1139` loop bound),
  `_stream_buffer_size` (`client.py:1084` allocation size),
  `_default_timeout_ms` (`client.py:1036`), `_default_max_redirects`
  (`client.py:1024`), `_when_oversized` (`client.py:1304,1307` policy
  branch), `_user_agent` (`client.py:1067`). No mqtt-`max_message_bytes`
  equivalent exists.
- **CLEAN (no unbounded peer-sized allocation)** `heap` — every
  sender-controlled `bytearray(N)` is cap-gated *before* allocation:
  `bytearray(content_length)` (`_wire.py:1019`) behind the
  `HttpOversizedError` check at `:994`; the chunked/length-unknown grow
  (`_wire.py:1240`) clamped to `_max_body_bytes` at `:1235-1239`; the
  length-unknown tail (`:1033`) enforced at `:1181`.
- **CLEAN (hot path)** `heap`/`frag` — read-cursor + amortized halfway
  compaction (`_wire.py:696-706`, no `buf = buf[N:]`); chunk-body absorb via
  memoryview + slice-assign (`:1113,1207`); `str(line, "ascii")` line decode
  (`:885,927,1053`); every f-string sits on a `_fail`/error branch. The
  2026-07-03 D2 chunked-O(n²) finding is confirmed fixed at HEAD. Minor
  residue: `_live_slice` (`_wire.py:689-694`) returns a fresh bytearray copy
  per parsed *line* (status/header/chunk-size) — per-line not per-byte, low
  churn, defensible portability choice. KEEP.
- **KEEP (tests-only-but-documented surface)** `flash` —
  `put`/`patch`/`delete` (PyPI-requests convention, SKILL §1 exception 1),
  `stream=True`/`read_body_into`/`cancel`/`on_done=`/`max_redirects=`
  (documented + functional-tested behaviors with no first-party consumer
  yet), wire primitives re-exported from `__init__` (`parse_url`,
  `encode_request`, `ResponseParser` — internally live). No
  zero-consumer-AND-zero-test surface exists.
- **BUNDLE (weak)** `shape` — constructor-only knobs never set outside tests:
  `recv_budget_per_tick`, `when_oversized`, `stream_buffer_size`. Genuine
  tuning knobs; demoting saves ~0 stripped bytes. Note only.
- **Docs clean** — `docs/guide.md` defaults all match code (64 KB body cap,
  1024 stream buffer, 1024 recv budget, 5 redirects); exception names
  consistent. One shape asymmetry, not drift: `max_header_bytes` is
  parser-only — an `HttpClient` user cannot tune the 16 KB header cap
  (`client.py:1081-1091` builds the parser without it), unlike http_server
  which exposes its equivalent end-to-end. Flag for awareness.

**Verdict: clean.**

### http_server — clean; speculative surface correctly quarantined

- **CLEAN (no dead cap-knobs)** — all nine knobs functionally read:
  `_max_body_bytes` (`_wire.py:685`), `_max_request_line_bytes`
  (`_wire.py:555,566`), `_max_headers_bytes` (`_wire.py:620`),
  `_max_request_body_bytes` (`server.py:1084`), `_recv_budget`/`_send_budget`
  (`server.py:388,485` loop bounds), `_max_connections` (`server.py:1043`),
  `_request_timeout_ms` (`server.py:1076`), `_stream_buffer_size`
  (`streaming.py:402`).
- **CLEAN (no unbounded peer-sized allocation)** `heap` —
  `bytearray(content_length)` (`_wire.py:703`) behind the 413
  `ServerOversizedError` check at `:685`; chunked request bodies rejected
  outright (`:660-667`); the streaming buffer is config-sized, not
  peer-sized.
- **CLEAN (hot path)** `heap` — same read-cursor pattern
  (`_wire.py:456-466`); recv/send through memoryview windows
  (`server.py:401,488`); `streaming.py`'s per-chunk framing genuinely
  allocation-free as advertised (hex size line written into a reserved head
  region by indexed byte assignment, `streaming.py:106-124,223,433`);
  module-scoped terminal-state tuples (`_wire.py:318`,
  `server.py:254-268`) avoid per-tick rebuilds. Same minor `_live_slice`
  per-line copy as requests (`_wire.py:449-454`). KEEP.
- **KEEP (streaming has no first-party consumer — but costs nothing)**
  `abstraction` — `StreamingResponse`/`build_streaming_response` are
  tests-only today, yet `streaming.py` is lazy-imported from `server.py` only
  when a handler actually returns a `.source`-bearing object
  (`server.py:435,476,515`) — a minimal deploy never parses its 8.4 KB. This
  is the correct quarantine shape for speculative surface; contrast with
  logging, where the speculation is the whole always-loaded library.
- **KEEP (tier-1 parser path the server never engages)** `abstraction`
  `_wire.py:360-361,380-394` — `RequestParser`'s steady-state
  `body_buffer`/`body_buffer_view` params are never used by `_Connection`
  (which deliberately omits them, `server.py:305-309`, with a
  fragmentation-rationale comment); the tier is tests-only for the shipped
  server, though requests' `HttpClient` does use its twin. Keep (public
  standalone parser), noted.
- **BUNDLE (weak)** `shape` — `recv_budget_per_tick`/`send_budget_per_tick`
  are the only knobs not plumbed through `from_config` and never set outside
  tests. Note only.
- **Docs clean** — `docs/guide.md:122-129` matches code exactly (4
  connections, 10 s timeout, 16 KB body, 1 KB line, 4 KB headers); 413/414/431
  map to the right exception subclasses (`_wire.py:114-150`). The
  `CaseInsensitiveDict`/`parse_charset` duplication vs requests is
  deliberate and `# noqa: CHU027`-marked with the "don't pull the 2 K-line
  client onto server-only boards" rationale (`_wire.py:8-15`).

**Verdict: clean.**

**Cross-repo drift (consumer bug, not library fat):** sister
`projects/two_board_test/server/app.py:121` calls
`HttpServer(listener_factory=...)` but the parameter is `transport_factory`
(`server.py:707`) — a `TypeError` at runtime, stale across a rename. Same
API-churn signal class as the mqtt review's factory-kwarg note; fix belongs to
the template repo.

---

## 6. Reconciliation with prior reviews (excluded-scope libraries)

- **mqtt** — `2026-07-04-mqtt-bloat-review.md` stands as written; nothing
  here contradicts it. Its CUT-NOW items (`root_topic` prefix scheme,
  `_topic_levels_match`) remain the mqtt punch list; a sibling agent is
  actively editing `client.py` as of this pass.
- **requests chunked-body O(n²)** (hot-path audit D2, 2026-07-03) — the grow
  path was reworked at HEAD: `_try_consume_chunk_data` now writes through the
  steady-state buffer with memoryview windows and in-place compaction
  (`_wire.py:1101-1131`), and the 2026-07-04 streaming-body design review
  owns the remaining whole-body-buffering question. Not re-flagged here.
- **websockets D1/D3/D6/D7** (per-message double-copy, header scratch churn)
  — owned by the 2026-06/07 websockets stream of work; excluded from re-read
  per scope.

---

## 7. Ranked punch list

### FIX-NOW (measured, highest value — one is an add, not a cut)

1. **logging: add the import-boundary `gc.collect()`**
   (`logging/__init__.py` EOF; Finding L-1). Two lines, mirrors the other
   twelve libraries. **11 808 B of measured unreclaimed compile scratch** —
   the fleet's largest import-RAM defect, and the exact fragmentation
   signature the mqtt TLS hunt bisected (+33 KB contiguous on device for
   that chain).
2. **sockets: bound `recv_exact`'s `bytearray(byte_count)`**
   (`generators.py:269`). Unbounded peer-shaped allocation with only a
   `<= 0` guard; its sibling `recv_until` requires `max_bytes` for exactly
   this reason. Zero non-test consumers today, so the fix is free — add the
   cap before the first consumer wires a peer-controlled length into it.

### CUT-NOW (zero-consumer, free under 0092)

3. **timing: delete `earliest()`** (`deadline.py:56` + `__init__.py`
   re-export). Zero consumers in either repo incl. timing's own examples;
   rides the eager import path. ~8 code lines ≈ 330 stripped B + the eager
   namespace entry; break = one test file.
4. **wifi: delete `WifiAdapter.disconnect()`** (`_adapters/base.py:77`,
   `cp.py:94`, `mp.py:238`, `testing.py:79` — HEAD-pinned). Implemented in
   four files, called by nobody (`WifiService`'s reconnect path never uses
   it). ~10 code lines ≈ 400 stripped B; break = none. Coordinate with the
   agent currently editing wifi.
5. **ntp: delete the `broadcast=` kwarg** (`sockets_factory.py:11,18` +
   `README.md:59`). Dead pass-through, tests-only, docstring concedes NTP
   doesn't need it; direct `udp_socket(broadcast=True)` remains for anyone
   who does. ~4 code lines; break = one test.

Total CUT-NOW code: ~22 lines / ~0.8 KB stripped device bytes. That is the
honest number — this fleet does not have an mqtt-`root_topic`-sized cut
hiding in it.

### BUNDLE (with each library's next wave)

6. **sockets: fold `waits.py` into `generators.py`** — one non-test importer
   (`generators.py:40`), tight A→B chain; drops a file + a FAT cluster.
7. **sockets: revisit tests-only SSL surface** —
   `ssl_context_with_cert_and_key` bytes-variant (zero consumers;
   CP-raises-only) and `set_default_ca_bundle` (zero external consumers);
   `listener(backlog=4)` never overridden (weak demote).
8. **config: drop `DEFAULT_RUNTIME_CONFIG_PATH` from `__all__`** + its
   PEP-562 lazy branch (`__init__.py:52-55`); keep the module constant.
9. **logging: `Logger.log` per-emit `tuple(self._handlers)` snapshot**
   (`core.py:141`) — iterate directly or snapshot only when >1 handler;
   do it when the library gains a consumer.
10. **msgpack: trim the ~15-line caveat docstrings** on stream
    `pack`/`unpack` (test-lane heap + `.py`-install bytes only).
11. **Docs batch (three false or broken claims):** kvstore `testing.py:3`
    "downstream consumers import FakeKVStore" (zero exist); wifi
    `testing.py:126` same claim-shape for `FakeWifi`; sockets
    `testing.py:198` docstring example uses `NTPClient(sock=...)` — real
    kwarg is `socket=` (cold-reader `TypeError`).
12. **requests/http_server budget knobs** (`recv_budget_per_tick`,
    `send_budget_per_tick`, `stream_buffer_size`, `when_oversized`) — never
    set outside tests, but genuine tuning knobs; demoting saves ~0 stripped
    bytes. Note-only unless constructor surface is being trimmed anyway.

### KEEP-WITH-RATIONALE

- **kvstore's dict-completeness surface + four backends** — mapping-type
  contract; all backends reachable via runtime auto-detect; capacities all
  enforced; the field-reality MpNvs regression is verified fixed.
- **http_server `streaming.py`** — tests-only feature today, but
  lazy-imported only when a handler streams: a minimal deploy never parses
  its 8.4 KB. The correct quarantine shape for speculative surface.
- **requests `put`/`patch`/`delete`, `stream=True`, `read_body_into`** —
  PyPI-convention + documented, functional-tested behaviors (SKILL §1
  exception 1).
- **msgpack `_decode` tuple-threading** — the decode path's inherent
  allocation; offset-as-state refactor has no consumer demanding it.
- **sockets `generators.py` convenience layer** — no downstream library uses
  it, but demos/examples do; it is documented app surface, not plumbing.
- **The five `sockets_factory.py` DI shims** — deliberately separate files so
  custom-transport apps never deploy `chumicro_sockets`; 10+ sister projects
  import them. Naming drift (`_factory` vs `_connector_factory` vs
  `_listener`) → `/audit-integration`.
- **All 14 sub-50-line files** — package markers, re-export `__init__`s, and
  live DI shims; ~3 KB total cluster overhead buys runtime isolation.
- **Fleet docstring density (34 %)** — strips to 0 device bytes (Decision
  0090); charge to test-lane heap and reader time. A `/audit-comments` pass
  on the >50 %-density modules is optional polish, not structure.

### ESCALATE

- **logging adoption** — zero importers in either repo; keep/defer is a
  workspace-owner decision (`/audit-workspace`), not a code cut.
- **Sister-repo stale API references** — `HttpServer(listener_factory=)`,
  `WifiConfig.from_dict`, the removed `tcp_client_socket` family, plus the
  mqtt factory-kwarg churn already noted in the bloat review: the most
  visible consumers are pinned to renamed-away constructor surfaces.
  Template-repo fix + a pre-publication API-freeze signal.
- **`sockets_factory` naming convergence** — `/audit-integration`.

---

## Bottom line

**The fleet is not code-bloated, and its file count is not excessive.**
8 889 code lines across 13 libraries deliver the runner-contract,
cross-runtime, non-blocking capability set; 34 % doc density strips to zero
at deploy (848 KB raw → 370 KB flashed); 71 files decompose into re-export
convention, runtime-isolation markers, and live DI shims, with zero
gratuitous splits left (mqtt's `_wire` merge already took the one bad case).

The sweeps that found mqtt's fat come back clean here: **no dead cap-knobs**
anywhere in scope (every `max_*`/budget/timeout knob has a functional
threshold read), **no wrapper-doubling**, **no `__slots__`/`typing`/banned
syntax**, **every peer-sized allocation in requests/http_server bounded
before it allocates**, and hot paths fleet-wide are read-cursor +
memoryview + slice-assign with f-strings confined to error branches. msgpack
is the reference implementation of the fleet's own patterns.

What the audit actually found: one measured import-RAM defect (logging's
missing `gc.collect()`, 11.8 KB), one latent unbounded allocation (sockets
`recv_exact`, zero consumers so free to fix), ~22 code lines of
zero-consumer surface (`earliest`, `disconnect`, `broadcast=`), three false
or broken doc claims, and one genuinely strategic question that no knife
answers: **logging has no adopter**. Everything else is capability, honestly
quarantined.
