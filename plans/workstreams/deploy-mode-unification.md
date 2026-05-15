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

## Phases

1. **Shared resolver.**  Lift the policy into one
   `chumicro_deploy` function `resolve_deploy_mode(configured, *,
   staged_files, device_caps, requires_flash_libs, force) ->
   (mode, message|None)`.  Re-point `Deployer._effective_device_for_source`
   at it (behavior-preserving for the CLI path).  Unit-test the
   resolution order exhaustively (it already has 4 tests in
   `test_deployer.py` — migrate + extend).
2. **pytest-device adopts it.**  `resolve_effective_deploy_mode`
   delegates to the shared resolver, passing `context` (`functional`)
   + the staged file set (`resolve_library_source_dirs` walk) so
   functional runs get the non-`.py`→flash + `requires_flash` policy.
   Loud message, continue in flash — never silent-skip.  Regression: a
   `--deploy-mode ram` run of the sockets TLS matrix on CP must now
   loudly switch to flash and pass (today it silently drops
   `_ca_bundle.der`).
3. **`devices.yml` capability.**  Optional per-device boolean
   `supports_ram_mode` (default/absent ⇒ `true`; back-compatible).
   Resolver step 2 (universal).  Loader fold + schema doc + template
   + a commented-out example on the Pi Pico W entries.
4. **On-device unit-sweep command.**  `scripts/run.py
   test-unit-on-device` (final name TBD): cross-runtime unit suite on
   real boards, RAM-blessed.  Resolves mode **per library** (Decision
   0009 shape) with `context=unit-sweep` — step 4 (data-file) is
   skipped, so a stray `src/` data file (e.g. `_ca_bundle.der`)
   doesn't force the whole sweep to flash; only `requires_flash`
   libraries fall back per-library.  Each per-library deploy is
   single-mode (all-or-nothing — no within-deploy mixing); mode
   varies *across* the sweep's N deploys, not within one.  **Open
   sub-question:** exact batching granularity — strict per-library
   (N deploys, reuses the existing per-package shape) vs. a
   light-RAM / heavy-flash two-bucket split (2 deploys, fewer
   connect/stage cycles, but a 17-library RAM staging may OOM).
   Decide during implementation against measured staging cost.
   `preflight --with-device-unit` opt-in flag, parallel to
   `--with-functional`.  Not in default preflight.
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
- `test-unit-on-device` runs the cross-runtime unit suite on the
  4-board matrix; light libraries ride RAM (per-library resolution),
  only `requires_flash` libraries fall to flash; a stray `src/` data
  file does NOT force the sweep to flash.  `preflight
  --with-device-unit` appends it; default `preflight` unchanged (no
  device deploy).
- `devices.yml` `supports_ram_mode: false` honored with a loud
  message; absent ⇒ both modes (back-compat).

## Status

- [ ] not started — workstream opened 2026-05-15 (design captured in
  Decision 0068; implementation pending sign-off).
