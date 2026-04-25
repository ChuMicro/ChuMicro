# Lazy loading on constrained runtimes — investigation

Status: `research`
Date: `2026-04-25`
Trigger: User push-back during Phase 3a kickoff — boot-time cost on embedded boards is real, and the existing pattern catalog only frames lazy loading as a workbench-CLI optimization, not a device-library principle.

## Question

Should ChuMicro device libraries adopt deferred / "JIT-like" loading
patterns systematically — and if so, where do the wins justify the
complexity?

## TL;DR

Most ChuMicro libraries are already **cheap enough at import** that
eager loading is fine.  The real win is for **libraries with
per-runtime adapters or many feature submodules**: the user's `app.py`
typically imports the library by name, and an eager `__init__.py`
that pulls in every submodule + every adapter (CP NVM + MP NVS + MP
LittleFS + memory, all at boot, even though only one is selected)
costs RAM + parse-time on a 256 KB-class board.

The fix exists already — `chumicro-deploy` and `chumicro-repl` both
use **PEP 562 module-level `__getattr__`** to defer submodule imports
until first attribute access.  PEP 562 is supported by both
MicroPython and CircuitPython (verified in source: the
`MICROPY_MODULE_GETATTR` config flag is default-on for every board
shipping at the "core features" ROM level — every production board
we target).  We should generalise the pattern from "workbench CLIs"
to "any library with a non-trivial submodule graph or per-runtime
adapter set."

## Inventory: how each current library loads today

Read top-of-`__init__.py` audit, 2026-04-25:

| Library | Top-level imports | Per-runtime adapters? | Boot cost shape |
|---|---|---|---|
| `chumicro-compat` | None — empty `__init__` | No | **Cheap.**  User imports the submodule directly (`from chumicro_compat.functools import partial`) per docstring contract. |
| `chumicro-config` | `runtime` + `section` | No | **Cheap.**  Two tiny modules.  `templates` (host-only via `importlib.resources`) is *not* re-exported — fail-fast on device. |
| `chumicro-kvstore` | `core` (KVStore + 4 exceptions) | **Yes** — 4 backends | **Eager core, lazy adapters.**  `core.py` imports `MemoryBackend` eagerly; `_select_backend` lazy-imports the per-runtime backend (`cp_nvm` / `mp_nvs` / `mp_littlefs` / memory).  Already optimal. |
| `chumicro-msgpack` | tries native C, falls back to `_pure` | Sort-of — native vs pure | **Optimal already.**  Try-import pattern means the pure-Python fallback (~700 B heap on CP per the docstring) only loads when no native C module exists. |
| `chumicro-runner` | `core` (Runner + TaskHandle) | No | **Eager** — imports `chumicro_timing.ticks` at module load.  Documented as **intentional** (commit comment): MP mount-mode functional tests pay an mpremote RPC per file read; lazy import would push that cost into test-execution time.  Niche test-harness optimization, not relevant to runtime. |
| `chumicro-timing` | `heartbeat` + `ticks` | No | **Eager.**  Same MP mount-mode rationale as runner.  Heartbeat + ticks always get used together. |
| `chumicro-deploy` (workbench) | None at top — PEP 562 `__getattr__` table | N/A (host) | **Optimal.**  `_LAZY_ATTRS` dict maps every public attribute → submodule; `__getattr__` imports on first access.  Cold-start `--help` pays nothing for `pyserial` / `mpremote` / `urllib`. |
| `chumicro-repl` (workbench) | None at top — PEP 562 `__getattr__` table | N/A (host) | Same as deploy. |

The pattern that pays off on workbench (`__getattr__` defers heavy
deps until first access) ports cleanly to device libraries with
similar shape.  The key signal is "does the user typically use only a
subset?"  If yes, lazy wins.  If no, eager is fine.

## Where lazy loading actually wins on device

**1. Per-runtime adapter selection.**  The pattern `chumicro-kvstore`
already uses for `_backends/` should be the template every adapter-
based library follows.  Concrete win: at boot, only one of
`{cp_nvm, mp_nvs, mp_littlefs, memory}` parses + loads.  On CP-RP2040
the kvstore footprint is `core.py` + `_backends/cp_nvm.py` + the base
shape — not all four backends.

**2. Optional features behind `__getattr__`.**  `chumicro-wifi`
(Phase 3a) ships with: `WifiService`, `WifiConfig`, plus adapters for
CP / MP-ESP32 / MP-RP2 / CPython.  A user who only imports
`WifiConfig` to do `from_dict` (e.g. validating a config snippet on
the host) shouldn't pay the `wifi.radio` import cost.  This argues
for the `__getattr__` table pattern at the top of
`chumicro_wifi/__init__.py`.

**3. Native-module delegation.**  `chumicro-msgpack`'s try-import
pattern is the canonical shape for "use the C built-in if it exists,
fall back to pure-Python otherwise."  Other libraries with the same
substrate-vs-fallback shape (future `chumicro-sockets` Phase 5,
`chumicro-mqtt` Phase 6) should follow it.

## Where eager loading is correct (don't lazy-load these)

- **Always-used core APIs.**  If 100 % of users will hit the import
  within a tick, lazy adds first-use overhead for no benefit.  E.g.
  `Runner.tick()` is the loop — `from chumicro_runner import Runner`
  immediately implies use.
- **Tightly-coupled submodules.**  `chumicro-timing`'s `heartbeat`
  always uses `ticks`; splitting them just to enable lazy is
  premature.
- **Hot paths.**  Don't lazy-import inside a function that fires every
  tick.  The first-use cost shows up as a tick spike.  Move the
  import into `__init__` or to module level if the function is hot.
- **Debug/inspection use.**  `from foo import bar` on a host for an
  introspection script doesn't care about boot time.  Lazy patterns
  are about devices, not hosts.

## Recommendation: tiering

Adopt a two-tier classification for new libraries:

**Tier A (eager-OK):** small-surface libraries (≤2 modules, no
per-runtime adapters, all features always co-used).  Today: `compat`,
`config`, `runner`, `timing`.  Standard `from .core import X` imports
at top of `__init__.py`.  No action needed.

**Tier B (lazy-required):** libraries with per-runtime adapters,
optional features, or a non-trivial submodule graph.  Today:
`kvstore` (already does it for backends), `msgpack` (native vs pure).
Soon: `wifi` (4 adapters), `mqtt` (sockets backend, QoS variants),
`sockets` (CP vs MP sockets shim).  These should:

  1. Place adapters under `_<package>/_backends/` or
     `_<package>/_adapters/` (single-underscore convention; not part
     of the public API contract).
  2. Use a `_select_*` factory that lazy-imports the chosen
     adapter (the kvstore template).
  3. Optionally — for libraries with more than ~5 public attributes
     spread across submodules — adopt the PEP 562 `__getattr__`
     pattern at the top of `__init__.py`, mirroring
     `chumicro_deploy/__init__.py`'s `_LAZY_ATTRS` table shape.

The PEP 562 pattern's added complexity (the explicit `_LAZY_ATTRS`
table + the `__getattr__` hook + the `__dir__` shadow) is justified
when the alternative would import 5+ submodules at boot for a user
who reaches for one.  Below that threshold, eager is fine.

## Cross-runtime support: PEP 562 verified

CircuitPython 10.1.4 and MicroPython 1.26.0 both compile with
`MICROPY_MODULE_GETATTR` enabled (default-on at the `CORE_FEATURES`
ROM level — every production board we target).  Source references:

* `.tools/micropython-v1.26.0/py/objmodule.c:73` — checks the flag at
  module attribute lookup time.
* `.tools/circuitpython-10.1.4/py/objmodule.c:78` — same code path.
* `.tools/circuitpython-10.1.4/py/mpconfig.h` — flag default-on at
  `MICROPY_CONFIG_ROM_LEVEL_AT_LEAST_CORE_FEATURES`.

The pattern Just Works on every board in `devices.yml`.  Hardware
verification will land alongside the first device library to adopt
it (chumicro-wifi, Phase 3a).

## Specific opportunities for current libraries

**No action needed** in this investigation — current libraries are
either small enough that eager is fine (timing, runner, compat,
config) or already lazy where it matters (kvstore backends, msgpack
native delegation).

**The benefit kicks in for new libraries.**  The wifi work in Phase 3a
is the first chance to apply the Tier B pattern from day one rather
than retrofitting.  Subsequent libraries (wifi, sockets, mqtt) follow
the same template.

## Boot-cost measurement: future work

Today we have qualitative claims ("~700 bytes of heap on CP for
msgpack pure-Python fallback") but no systematic boot-time / heap
measurement.  Useful follow-up — not blocking — would be a small
benchmark harness that:

* Imports each chumicro library on a target board.
* Reports heap delta + wall-clock time per import.
* Compares eager vs lazy variants of the same library.
* Runs as part of `test-libraries-functional` on a single board.

This would let us back the tiering recommendation with real numbers
and catch regressions when a new library inadvertently bloats boot.
Filed in `next-up.md` Investigations.

## Decisions to land alongside this investigation

* Update `plans/patterns.md` "Lazy module-level imports for short-
  lived entrypoints (PEP 562)" section to **drop the "workbench-only"
  framing** — the pattern is cross-runtime now that we've verified
  CP + MP support, and Tier B device libraries should use it too.
* No new ADR — this is a pattern recommendation, not a structural
  change.  If the wifi work surfaces a new constraint that flips the
  recommendation, we'd open one then.
* New-library scaffolder (`scripts/new_library_scaffold.py`) emits a
  comment in the generated `__init__.py` pointing to the patterns
  doc + the Tier A / Tier B classification, so authors know to read
  it before adding submodules.

## Open questions

* **Heap-cost measurement.**  How much RAM does each library actually
  cost on a 256 KB board?  We don't know without a benchmark.  The
  msgpack `~700 B heap on CP` claim is the only quantitative number
  we have today.  Reasonable to defer until wifi lands — when there's
  a 4-adapter library to compare eager vs lazy on.

* **`__dir__` parity for static analysis.**  PEP 562 + lazy loading
  hides attributes from `dir(module)` unless `__dir__` is
  implemented (as `chumicro_deploy/__init__.py:204` does).  Should
  Tier B libraries always pair `__getattr__` with `__dir__`?
  Probably yes; treat as a sub-pattern of the recommendation.

* **CI gate for inadvertent boot bloat.**  Once a benchmark exists,
  should preflight enforce a heap budget per library?  Premature now
  — revisit when there's a baseline to enforce against.

## What this changes in flight

* **Phase 3a (chumicro-wifi).**  Slice 0 now lands with the Tier B
  pattern: per-runtime adapters under `_adapters/`, lazy-imported
  via `_select_adapter`; `__getattr__` table at the top of
  `chumicro_wifi/__init__.py` if the public-API surface justifies it
  (probably yes — 4 adapters + WifiService + WifiConfig + State enum).
  Hardware-verifies PEP 562 behavior on every plugged-in board as a
  side-effect of the slice's functional tests.

* **Future libraries (sockets, mqtt, sensor drivers).**  Inherit the
  Tier B template via the new-library scaffolder hint + the patterns
  doc.

* **Existing libraries.**  No changes.  Re-evaluate if a library
  grows past Tier A's threshold (more submodules, adds adapters).

## Self-validation

Investigation deliverable only — no code changes to existing
libraries.  Verifies:

* Each library's current loading shape was actually inspected
  (not assumed) — see Inventory table.
* PEP 562 device support claim is sourced (file + line references in
  pinned runtime trees).
* Recommendation is conservative — doesn't ask any current library
  to refactor.

The next chance to validate the recommendation in production is
chumicro-wifi Slice 0; if Tier B turns out painful there, this doc
gets revised before the pattern propagates to Phase 5+ libraries.
