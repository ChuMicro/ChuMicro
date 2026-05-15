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
   `preflight --with-device-unit` opt-in flag, parallel to
   `--with-functional`.  Not in default preflight.  **Open
   sub-question:** does a single RAM session staging ~16 light
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

## Status

- [ ] not started — workstream opened 2026-05-15 (design captured in
  Decision 0068; implementation pending sign-off).
