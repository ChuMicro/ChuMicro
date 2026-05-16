# Deploy-mode unification + on-device unit sweeps

Implements [Decision 0068](../decisions/0068-unified-deploy-mode-resolution.md).
Charters the `plans/open-questions.md` "two deploy-mode resolvers"
gap (now removed from that file — this workstream + the ADR are the
record).

## Goal

One deploy-mode resolver shared by `chumicro-deploy` and
`chumicro-pytest-device`; a `devices.yml` per-device capability; a
first-class on-device unit-sweep command + a `preflight` opt-in flag.
Outcome: RAM mode keeps its strong use (bulk on-device unit tests) and
sheds its footgun (silent data-file drop on CP RAM); the test path
loudly auto-switches instead of silently mis-deploying.

## Current state (pre-work)

- `Deployer._effective_device_for_source` (deployer.py): force →
  device-not-ram → non-`.py` data file → `requires_flash` lib →
  configured.  Returns `Device`.
- `resolve_effective_deploy_mode` (`pytest-device/_test_runner.py:181`):
  CLI override → devices.yml per-device → global default.  Returns a
  mode string.  **No source/lib inspection** — the divergence.
- `devices.yml`: per-device `deploy_mode`, global
  `defaults.deploy_mode`, `defaults.ide_runtime`.  No capability key.
- Functional tests flash-by-default (0047 / devices.yml).  Cross-runtime
  unit suite runs on unix-port; `--target device` exists but no
  dedicated bulk command.

## Implementation map (for a cold session — read before touching code)

Concrete code locations, verified this session.  Line numbers drift —
grep the symbol.

**The two resolvers to unify:**

- `workbench/deploy/src/chumicro_deploy/deployer.py` →
  `Deployer._effective_device_for_source` (~L112).  This is the CLI /
  app-deploy resolver; it *already* has the force / not-ram /
  non-`.py` / `requires_flash` order (added this session, commit
  `80927ff0`).  4 tests: `workbench/deploy/tests/test_deployer.py`
  `TestPreflightAutoSwitch` + `TestPreflightDataFileAutoSwitch`.
  Phase 1 lifts this body into a standalone
  `resolve_deploy_mode(...)` in `chumicro_deploy` and re-points the
  method at it (behaviour-preserving — those 8 tests must stay green).
- `workbench/pytest-device/src/chumicro_pytest_device/_test_runner.py`
  → `resolve_effective_deploy_mode` (~L181).  The test-path resolver
  with NO source/lib inspection — the divergence.  Phase 2 makes it
  delegate to the shared resolver.

**Staging / what feeds `staged_files` and `requires_flash_libs`:**

- `_test_runner.py` → `resolve_library_source_dirs` (~L103-178):
  returns dependency-first `src/` *directories* (library + its
  chumicro pyproject deps + test-file-imported libs).  This is the
  dependency-closure walk.  For functional/app-deploy `staged_files`
  = whole closure (these dirs); for the unit sweep `staged_files` =
  library-under-test's own `src/` only.  `requires_flash_libs` is
  derived from this same closure walk (transitive — 0068 §1 step 3),
  regardless of the `staged_files` scope.
- Staging orchestration: `plugin.py` ~L805-868 (per-item prepare;
  flash re-stages per library via `_bulk_stage_for_device`
  ~L1290 with `library_filter`, RAM re-stages per file with
  `_should_soft_reset_before_stage` ~L1243).  The per-library
  isolation (rsync `--delete` on library switch; soft-reset between
  RAM files) ALREADY EXISTS — the sweep reuses it untouched, do not
  rebuild it.  Comments at `plugin.py` ~L816-821 / ~L1254-1265 and
  `circuitpython_bootstrap.py` ~L119-121 ("non-`.py` silently
  skipped in RAM-mode CP") encode the constraints — read them.
- `device.py`: `DeployMode` enum, `DEFAULT_DEPLOY_MODE = "flash"`
  (~L33).  The sweep's last-resort default is `ram`, NOT this — that
  is a *caller* choice in the sweep command, not a change to
  `DEFAULT_DEPLOY_MODE` (don't flip the global; 0047 owns it).
- `chumicro_deploy.sources.FileSource.files()` → on-device path map;
  `circuitpython_bootstrap.py` is the RAM CP raw-REPL subsystem
  (RAM-only; verified NOT shared with `chumicro-repl`, which has its
  own `workbench/repl/.../session.py`).

**Verification (Phase-2 regression is the load-bearing one):**

- `--deploy-mode ram` + `libraries/sockets/functional_tests/test_real_tls_matrix.py`
  on a CP board must now *loudly switch to flash and pass* — today
  it silently drops `_ca_bundle.der`.  Run on the 4-board canonical
  matrix (Lolin S2 + Pi Pico W × CP/MP).
- `chumicro_ntp` unit suite must stay RAM (dependency-closure
  non-poisoning — 0068 §1 step 4 / workstream acceptance).

**Explicitly OUT of scope (do not conflate):**

- The `plans/next-up.md` "`subprocess.run(["sync"])` slow
  CircuitpythonTransport tests" item is a SEPARATE unit-test-isolation
  defect (real `sync` not faked).  It is *not* caused by, fixed by,
  or related to this workstream.  Preflight never deploys to a board;
  this work does not touch preflight timing.  Leave that item alone.
- Do NOT delete RAM mode / the bootstrap subsystem.  Deletion was
  considered this session and explicitly rejected (0068 Alternatives)
  — most libraries are RAM-capable and the subsystem works.
- Do NOT supersede 0028 or 0047.  0028's RAM/flash transport
  mechanics stay; 0047's `requires_flash` schema + flash-default
  stay.  0068 only unifies the *resolution policy* on top and
  cross-links 0047 §3 (already edited in place).
- AGENTS.md / docs / `device-testing.md` updates land in **Phase 5,
  after the command exists** — do not document the flag/command/schema
  before they're real.

## Phases

1. **Shared resolver. — DONE** (commit pending).  Policy lifted into
   `chumicro_deploy.preflight.resolve_deploy_mode(configured_mode, *,
   staged_files, device_caps, requires_flash_libs, resolution_unit,
   force) -> (mode, message|None)`, exported from the package root
   alongside the frozen `DeviceCaps(supports_ram_mode=True)`
   capability struct (full §1 rule incl. the §2 capability branch
   ships now; Phase 3 only feeds `devices.yml → DeviceCaps`).
   `requires_flash_libs` is the **transitive import/dependency
   closure** (not the unit's own lib) — importing a flash-only dep
   OOMs regardless of test purity.  `resolution_unit` (the unit's own
   library, or `None` for an app deploy) selects the message variant:
   when the closure forces flash and the unit isn't itself flagged,
   the message recommends it declare `requires_flash` (durable record;
   resolver never edits pyproject).  `Deployer._effective_device_for_source`
   re-pointed at it (passes `resolution_unit=None`,
   `DeviceCaps()` — behavior-preserving; the 8 existing
   `test_deployer.py` `TestPreflight*` tests stay green).  Exhaustive
   pure-function coverage in `test_resolve_deploy_mode.py` (all 5
   steps + non-RAM-capable board + the recommend variant).
2. **pytest-device adopts it (functional path). — DONE** (commit
   pending).  A session-scoped `_session_effective_deploy_mode`
   (memoized per device on `_TransportCache`) combines the existing
   precedence resolver with the shared `resolve_deploy_mode`, passing
   `staged_files` = the **full dependency closure** of every
   `DeviceTestItem` targeting the device (`_device_closure_source_dirs`
   reuses `resolve_library_source_dirs`; `_staged_file_names` walks it,
   skipping `__pycache__`) plus the closure-scoped `requires_flash`
   set.  All four `get_transport` call sites (prepare, execute,
   feature-probe, PR-summary) route through it, so the mode is decided
   once from the whole closure *before* the per-device transport is
   cached — no mid-session switching.  Loud `warnings.warn`, continue
   in flash, never silent-skip.  Regression PASSED on the 4-board
   canonical matrix (Lolin S2 + Pi Pico W × CP/MP): `--deploy-mode
   ram` + the sockets TLS matrix loudly switches to flash and all 3
   legs pass on every board (was a silent `_ca_bundle.der` drop).
   The data-file switch message was reworded runtime-agnostic (still
   one byte-identical string per 0068 §1) so it no longer reads
   CP-only ("raw-REPL exec") when emitted on MicroPython.  No
   over-switch verified on hardware: a RAM-capable library (`timing`,
   no data file, not `requires_flash`) + `--deploy-mode ram` stays
   RAM on Lolin S2 CP *and* MP (15/15 each, no switch warning).
3. **`devices.yml` capability. — DONE** (commit pending).  Optional
   per-device boolean `supports_ram_mode` on `DeviceEntry`
   (default/absent ⇒ `true`, back-compatible; non-bool ⇒
   `DeviceConfigError`).  Added to the `default.py` loader's
   `_DEPLOY_ONLY_FIELDS` (known key, not swept into `extra`) and
   parsed/validated in `_validate_device`.  pytest-device's
   `_session_effective_deploy_mode` now builds
   `DeviceCaps(supports_ram_mode=device_entry.supports_ram_mode)` —
   the resolver's step-2 branch (shipped in Phase 1) finally has a
   real producer.  Schema documented in `device-testing.md` (incl. an
   auto-switch note so the deploy-mode section isn't stale) + a
   commented example in the shipped `devices.yml.template`
   (`examples/devices.yml` is gitignored, not a committed surface).
   4 new loader/wiring tests.
4. **On-device unit-sweep command.**  `scripts/run.py
   test-unit-on-device` (final name TBD): cross-runtime unit suite on
   real boards.  Applies the §1 rule **per library suite**, passing
   `staged_files` = that library's **own package src only** (NOT the
   dependency closure) so a dependency's data file (`sockets`'s
   `_ca_bundle.der`) doesn't poison every sockets-dependent suite —
   safe because pure unit tests can't reach a dep's data-file path
   (0003/0016).  Groups libraries by resolved mode, runs each group as
   **one single-mode device session** reusing the existing per-library
   staging untouched (flash: rsync `--delete` on library switch; RAM:
   soft-reset between files — both already exist).  `ram` pref on a
   RAM-capable board ⇒
   a RAM session over the light libraries + a flash session over the
   `requires_flash` / data-file ones; `flash` pref or no-RAM board ⇒
   one flash session.  No per-library transport switching, no
   `context` flag, no within-session mixing (a session is one mode).
   The sweep's last-resort default mode is **RAM** (CLI → per-device
   → global `defaults.deploy_mode` → RAM), distinct from Deployer /
   functional which fall back to flash (0047) — the sweep exists for
   RAM-capable on-device validation.  Behavioral pass/fail only:
   **no coverage gating** (coverage.py can't trace MP/CP; 0009/0025
   stay unix-port-only; the command takes no `--coverage-threshold`).
   **OOM→`requires_flash` learning:** if a library that resolved to
   RAM still OOMs on stage/import, flip *that* suite to flash for the
   run + recommend it declare `requires_flash` (same channel as the
   §1 transitive warning).  `preflight --with-device-unit` opt-in
   flag, parallel to `--with-functional`.  Not in default preflight.
   **Open sub-question:** does a single RAM session staging ~16 light
   libraries' src+tests at once OOM?  If so, sub-group the RAM session
   (still single-mode, just more sessions).  Decide against measured
   staging cost during implementation.
5. **Docs + AGENTS.md.**  Command table, `devices.yml` schema,
   device-testing.md matrix.  AGENTS.md gets the command + the
   supported-matrix rule once the command exists (not before — it's
   `proposed` until then).

## Sequence / dependencies

1 → 2 (2 needs the shared resolver) → 3 (capability is a resolver
input) → 4 (independent of 2/3 but wants the resolver for its own
mode pick) → 5 (after the surface is real).

## Acceptance

- One resolver; `grep` finds no second deploy-mode policy.
- 4-board: `--deploy-mode ram` + sockets TLS matrix on CP → loud
  "switching to flash" + green (no silent `_ca_bundle.der` drop).
- `test-unit-on-device`, `ram` pref, RAM-capable board: light
  library suites run in a RAM session; `requires_flash` libraries and
  data-file-shipping libraries (e.g. `chumicro_sockets` →
  `_ca_bundle.der`) run in a flash session — *that library's* suite
  switches, not the whole sweep; the other ~16 stay RAM.  `flash`
  pref or non-RAM board ⇒ one flash session, all libraries.
  `preflight --with-device-unit` appends it; default `preflight`
  unchanged (no device deploy).
- **Dependency-closure non-poisoning:** `chumicro_ntp`'s unit suite
  (depends on `sockets`, not `requires_flash`, never touches TLS)
  stays in the RAM session — its own-src has no data file, and
  `sockets`'s `_ca_bundle.der` in the dependency closure does NOT
  flip it.  Conversely a `chumicro-requests` *functional* test on CP
  RAM still loudly switches to flash (full-closure scope sees the
  dependency's data file).
- `devices.yml` `supports_ram_mode: false` honored with a loud
  message; absent ⇒ both modes (back-compat).
- **Transitive `requires_flash`:** a synthetic light library that
  imports a `requires_flash` lib resolves to flash *and* the message
  recommends it declare `requires_flash`; declaring it silences the
  recommendation.
- **OOM→learn:** a library forced to RAM that OOMs on stage/import
  flips just its own suite to flash for the run + recommends the
  declaration; the rest of the sweep is unaffected.
- **Non-gating:** `--with-device-unit` exposes no coverage-threshold
  flag; the unix-port/CPython coverage gate is unchanged.
- Two device sessions (RAM group then flash group) on one board in
  one run connect/teardown cleanly on the same serial port.

## Status

- [x] **Phase 1 — shared resolver.**  `resolve_deploy_mode` +
  `DeviceCaps` in `chumicro_deploy.preflight`, exported; Deployer
  re-pointed (behavior-preserving, 8 `TestPreflight*` green); 19
  pure-function tests.  Signature carries `resolution_unit`
  (centralised recommend message; ADR §1 edited in place).
- [x] **Phase 2 — pytest-device adopts it (functional path).**
  Session-scoped `_session_effective_deploy_mode` (memoized per device)
  feeds the full dependency closure to the shared resolver; all four
  `get_transport` call sites route through it.  Load-bearing
  regression PASSED on the 4-board matrix (Lolin S2 + Pi Pico W ×
  CP/MP): `--deploy-mode ram` + sockets TLS matrix loud-switches to
  flash, 3/3 legs green per board.  7 contract tests; preflight green
  (3900).
- [x] **Phase 3 — `devices.yml` `supports_ram_mode` capability.**
  Optional per-device boolean on `DeviceEntry` (absent ⇒ `true`,
  back-compatible; non-bool ⇒ `DeviceConfigError`), threaded into
  `DeviceCaps` by pytest-device so the Phase-1 resolver step-2 branch
  has a producer.  Loader fold + `device-testing.md` schema +
  template + Pi Pico W commented examples.  4 new tests; preflight
  green.
- Phase 4 split into sub-units (it is the largest; each commits
  independently):
  - [x] **4a — caller-scoped `staged_files`.**  pytest-device now
    scopes `staged_files` to each library's own `src` when every
    device item is a unit test (`_device_is_unit_sweep` /
    `_device_own_source_dirs`), full closure for functional;
    `requires_flash_libs` stays the full transitive closure in both.
    6 new tests.  **Architectural finding:** `libraries/*/tests/`
    routes to the device backend *only* under `--target unix-port`
    today — `--target device` is functional-only, unit tests fall to
    the plain CPython lane.  Running the unit suite on hardware needs
    a new collection mode (planned: `--target device-unit`), so 4a's
    on-hardware proof (ntp stays RAM) rides with 4d, not standalone.
  - [x] **4b — `device-unit` collection + `test-unit-on-device`
    command + mode grouping.**  New `--target device-unit` value
    routes `libraries/*/tests` to the device backend (parallel to
    `unix-port`; `--target device` stays functional-only).
    `scripts/run.py test-unit-on-device` resolves per-library mode
    (own-src `staged_files`, full-closure `requires_flash`,
    `resolution_unit`=lib's pip name), groups libraries by resolved
    mode, runs one single-mode `--deploy-mode` session per (runtime,
    mode) group (flash group first), skips a runtime cleanly when no
    device is configured.  `preflight --with-device-unit` opt-in,
    serial after the functional tail.  Sweep last-resort preference is
    RAM; **simplification of 0068 §1 precedence** — the sweep does not
    inherit `devices.yml` `deploy_mode` (functional-tuned); it is
    CLI-`--deploy-mode`-or-RAM, since the loader folds global→
    per-device so "explicitly set" is unknowable and the sweep's whole
    purpose is RAM validation.  4 dispatch + grouping tests; preflight
    green.  Hardware end-to-end rides with 4d.
  - [x] **4b.1 — test-support staging gap → [Decision 0069](../decisions/0069-test-support-module-marker.md). DONE.**
    21/37 cross-runtime unit files import a `*.testing` fake;
    `testing.py`'s false `__chumicro_runtimes__=("cpython",)` marker
    made the 0044 device filter strip it → every fake-using suite
    `ImportError`d on-device.  0069 implemented (commit `03311b1d`):
    explicit `__chumicro_test_support__` + `is_test_support_module()`
    reader; product/bundle always-exclude, `device-unit` includes via
    `stage(include_test_support=True)`.  **Verified on hardware** —
    Pi Pico W CP `device-unit` flash: `timing` 29/29, `wifi` 41/41,
    `runner` 61/61, all standalone green (was a mass ImportError).
  - [ ] **4b.2 — multi-library session sequencing bug.**  Decisive
    finding: *every library passes standalone* on the `device-unit`
    flash path, but the full 15-library sweep session fails most
    suites wholesale (e.g. `runner/test_core` 61/61 alone → all-FAIL
    in the combined run; same for `wifi`).  Not per-library
    conformance, not 0069, not the RAM grouping (Lolin S2 CP grouping
    verified correct earlier).  The defect is the per-library flash
    re-stage between libraries in one pytest session — rsync
    `--delete` on library switch + the next library's closure
    re-stage.  **Root-caused (Pi Pico W CP flash, reproduced 2×, not
    transient) into two distinct issues:**

    **(i) Sweep-scope / test-classification gap.**  The sweep assumes
    every `libraries/<n>/tests/test_*.py` (non-`_pytest`) is a
    cross-runtime *device* test.  False for a subset: the 6
    `test_{mp,cp}_{adapter,*backend}.py` files are *host-side*
    fake-injection unit tests that also assert the wrong-runtime
    constructor raises (each has a
    `test_runtime_acquisition_raises_*_on_cpython`).  They have no
    `__chumicro_runtimes__` marker (pre-`device-unit`, "tests/ minus
    `_pytest` runs on unix-port" was the only contract).  On a real
    CP board they fail wholesale (MP-backend import).  A blanket
    runtime marker is *wrong* — it would kill the deliberate
    cpython-negative-path assertions.  Needs a classification
    decision: how a host-only unit test opts out of the device-unit
    sweep (parallel to how `_pytest.py` opts out), likely ADR-worthy.
    Standalone-green libs are unaffected by this item.

    **(ii) Full-scale session degradation.**  `runner/test_core`
    (61/61 standalone, 90/90 with timing, 126/126 with kvstore) and
    `wifi/test_wifi` (41/41 standalone) show `.FFFF…` — first test of
    the file passes, rest fail — only deep into the full 254 s /
    663-test Pico W flash sweep (~67 %+).  Signature = transport/board
    dies mid-session at scale (FAT/flash churn from hundreds of rsync
    `--delete`+restage cycles on the 491 KB drive, or heap/handle
    exhaustion), not per-library and not (i).  Bounded but non-obvious
    Phase-4 mechanism problem; needs a design approach (periodic
    reconnect / board reset between libraries / chunking).  The
    "~16-lib RAM OOM" sub-question is retired (staging is per-library);
    this is the flash-session-at-scale analogue.
  - [ ] **4c — wifi RAM-on-CP hard-crash (post-0069).**  Separate
    from the staging gap: `wifi` under `--deploy-mode ram` on CP drops
    the USB CDC (board → safe mode; `reset-board` FS-wipe recovers it
    once the crashing payload is gone).  Reproduces running `wifi`
    alone.  Investigate only *after* 0069 lands (the `ImportError`
    masks it today); report cause before fixing — may be a real
    wifi-on-RAM-CP defect the sweep correctly surfaced (0068 §3) or a
    raw-REPL payload issue.  Plus OOM→`requires_flash` learning.
  - [ ] **4d — sweep validation + scope decision.**  0068's stated
    Phase 4 acceptance is grouping + non-poisoning (observed in 4c
    finding 1), *not* every library's unit suite passing on silicon —
    0068 is "behavioral pass/fail only", so per-library on-silicon
    unit failures (`wifi`: 80 fail even in flash) are the sweep's
    *output*, tracked separately, not a 0068 gate.  Remaining: a
    clean grouping-validation pass on a light subset across the
    4-board matrix once hardware is physically recovered; decide
    whether per-library on-silicon conformance is in or out of this
    workstream (leaning out — it is follow-up the sweep exists to
    generate).
- [ ] Phase 5 — docs + AGENTS.md (after the command exists).
