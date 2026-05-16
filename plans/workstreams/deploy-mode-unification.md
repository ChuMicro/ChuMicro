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
2. **pytest-device adopts it (functional path).**
   `resolve_effective_deploy_mode` delegates to the shared resolver,
   passing `staged_files` = the **full dependency closure**
   (`resolve_library_source_dirs` walk) so a cross-library functional
   test that needs a dependency's data file (e.g. requests-functional
   needing `sockets/_ca_bundle.der`) is correctly forced to flash, not
   silently dropped.  Loud message, continue in flash — never
   silent-skip.  Regression: a `--deploy-mode ram` run of the sockets
   TLS matrix on CP must now loudly switch to flash and pass (today it
   silently drops `_ca_bundle.der`).
3. **`devices.yml` capability.**  Optional per-device boolean
   `supports_ram_mode` (default/absent ⇒ `true`; back-compatible).
   Resolver step 2.  Loader fold + schema doc + template + a
   commented-out example on the Pi Pico W entries.
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
- [ ] **Phase 2 — pytest-device adopts it (functional path).**  Next
  entry point.  `resolve_effective_deploy_mode` delegates to the
  shared resolver passing the full dependency closure as
  `staged_files`.  Load-bearing regression on the 4-board matrix:
  `--deploy-mode ram` + the sockets TLS matrix on CP must loudly
  switch to flash and pass.  See the implementation map above.
- [ ] Phases 3–5 — `devices.yml` capability → unit-sweep command →
  docs/AGENTS.md.  Not started.
