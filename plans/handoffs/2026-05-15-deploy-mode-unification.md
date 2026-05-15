# Handoff 2026-05-15 — deploy-mode unification (Decision 0068) ready to implement

## What this session was about

Two threads, in sequence:

1. **MicroPython TLS default-trust (Shape Y)** — started from a memory
   note that MP's bare `ssl.wrap_socket` skips cert validation.
   Investigated, designed (Decision 0067), implemented, hardware-
   validated on the 4-board matrix.  **This workstream is CLOSED and
   shipped** — not a pickup item.  It is only relevant here because it
   produced `chumicro_sockets/_ca_bundle.der` (a shipped data file),
   which is the concrete case that exposed thread 2.

2. **Deploy-mode unification (Decision 0068)** — the `.der` data file
   surfaced that `chumicro-deploy` and `chumicro-pytest-device` have
   two *divergent* deploy-mode resolvers, and a `--deploy-mode ram`
   functional run on CP silently drops the data file.  That cascaded
   through a long design conversation into Decision 0068.  **0068 is
   `accepted` + signed off; implementation is the pickup for the next
   session and has NOT started.**

## What got done

- Thread 1 (TLS Shape Y): commits roughly `fb37cf0e` → `b7547011`
  (~16 commits).  Decision 0067 `accepted`.  Workstream
  `tls-default-trust-hardening.md` complete.  Don't reopen.
- Thread 2 (0068): commits `f31606b2` → `0ca5c20a`.  Decision 0068
  `accepted` 2026-05-15.  0047 §3 edited in place to cross-link 0068
  (`f31606b2`).  Workstream `deploy-mode-unification.md` written and
  made cold-session-ready (it has a full **Implementation map** —
  read it first).

## The pickup — implement Decision 0068

Everything needed is in
[`workstreams/deploy-mode-unification.md`](../workstreams/deploy-mode-unification.md):
5 phases, sequence, acceptance, and an "Implementation map (for a
cold session)" with exact symbols/paths.  Decision 0068 has the
*why*.  Start at Phase 1 (lift the shared resolver).  The
load-bearing acceptance is the Phase-2 regression: `--deploy-mode
ram` + `libraries/sockets/functional_tests/test_real_tls_matrix.py`
on a CP board must loud-switch to flash and pass (today it silently
drops `_ca_bundle.der`).  4-board canonical matrix: Lolin S2 + Pi
Pico W × CP/MP (all four are usually plugged in; ask the user).

## Design reasoning journey (why 0068 looks the way it does)

`git log` shows *what* changed commit-by-commit but not *why the
design converged here* across ~10 iterations.  This is that context —
read it so you don't re-litigate settled forks:

- **Why not just add the missing check to the test resolver?**
  Duplicated policy is exactly what drifted into the silent-drop bug.
  One shared resolver, two callers.
- **Why not delete RAM mode entirely?** Seriously explored mid-session
  (an ADR 0069 / deletion path was drafted in conversation then
  rewound).  Rejected because: most libraries ARE RAM-capable (only
  the 4 `requires_flash` networked libs aren't), the CP raw-REPL
  bootstrap subsystem is already written + working AND verified
  NOT entangled with `chumicro-repl` (repl has its own
  `session.py`/`recovery.py`), and on-device unit sweeps are the
  validation path that catches real-silicon divergences unix-port
  hides (this TLS work itself proved that — rp2 lacks
  `MBEDTLS_PEM_PARSE_C`, non-compacting GC fragmentation).  Recorded
  in 0068 Alternatives.  **Do not re-propose deletion.**
- **Why no `context` parameter on the resolver?** An earlier draft had
  per-library mode resolution with the transport switching mode
  mid-sweep + a `context` flag.  Rejected: deploy mode is
  session-scoped (transport cached per device), so compute each
  library's mode up front and group same-mode libraries into one
  single-mode session — same outcome, no mid-session switching, no
  flag, zero changes to existing per-library staging.
- **Why a boolean `supports_ram_mode`, not an array?** Two modes
  exist, flash is always available, so the only DOF is "can this
  board RAM?"  Boolean = no invalid states.  No board needs `false`
  today — the field is declared for schema stability, zero current
  consumers, acknowledged not hidden.  RAM *tightness* (Pi Pico W
  256 KB) is per-library via the OOM→`requires_flash` learning, NOT
  a board-wide disable.
- **The transitive `requires_flash` insight (0068 §1 step 3).**
  `requires_flash` is import-time OOM, so it's transitive: if X
  imports requests, X can't RAM even if X's tests are pure (the
  import alone OOMs; AST-walking can't prune it).  Therefore
  `requires_flash_libs` is ALWAYS the full closure, while
  `staged_files` is caller-scoped (own-src for the unit sweep, full
  closure for functional).  Two inputs, opposite scoping rules,
  because the two triggers fail differently.  This was the single
  hardest part to get right — don't collapse the two scopes.
- **Why the unit sweep defaults to RAM** (not 0047's flash default):
  0047's flash-default exists for the beginner-app-deploy footgun,
  which doesn't apply to a deliberate dev sweep whose entire purpose
  is RAM-capable on-device validation.  Caller choice, NOT a flip of
  `DEFAULT_DEPLOY_MODE`.

## Dead ends (don't re-walk)

- ADR 0069 / "delete RAM mode, flash-only on-device" — drafted in
  conversation, rewound.  The analysis is preserved in 0068's
  Alternatives bullet; nothing more to do there.
- The claim "dropping RAM regresses preflight via the flash `sync`
  cost" — **wrong, corrected.** Preflight NEVER deploys to a board.
  The slow `sync` is an unrelated unit-test-isolation defect in
  `test_circuitpython_transport.py` (real `subprocess.run(["sync"])`
  not faked) — its own `next-up.md` item, NOT part of this
  workstream.  Do not conflate.
- `context`-parameter resolver + per-library transport mode
  switching — rejected (see reasoning journey).

## How to rebuild context fast

- Read **Decision 0068** then the **Implementation map** in
  `workstreams/deploy-mode-unification.md`.  That's 90% of it.
- `git --no-pager log --oneline f31606b2..0ca5c20a` — the 0068 design
  arc, commit messages carry the per-step rationale.
- Key symbols (grep, line numbers drift):
  `Deployer._effective_device_for_source` (deployer.py),
  `resolve_effective_deploy_mode` (`pytest-device/_test_runner.py`),
  `resolve_library_source_dirs` (same file, the closure walk),
  `_bulk_stage_for_device` / `_should_soft_reset_before_stage`
  (`pytest-device/plugin.py`), `DEFAULT_DEPLOY_MODE` (deploy
  `device.py`).
- Related ADRs: 0047 (flash-default + `requires_flash`, §3 cross-links
  0068), 0028 (RAM/flash transport mechanics — stays accepted, NOT
  superseded), 0027 (device-test infra), 0009 (per-library test runs
  — host-side; the on-device per-library isolation is the
  pytest-device staging, a different mechanism — do not conflate
  0009 with the device path).
- The `.der` that started thread 2:
  `libraries/sockets/src/chumicro_sockets/_ca_bundle.der` +
  `_ca_bundle.py` loader; Decision 0067 for its background.

## Gotchas

- **`subprocess.run(["sync"])` slow-test item is NOT this work.**
  It's adjacent in `next-up.md` and a cold session will be tempted to
  fold it in.  It's a separate unit-test-isolation defect; preflight
  never deploys; leave it.
- **0028/0047 are NOT superseded.**  Only the *resolution policy* is
  unified; their transport mechanics + `requires_flash` schema +
  flash-default stand.  0047 §3 is already cross-linked in place.
- **AGENTS.md / docs wait for Phase 5.**  The flag/command/`devices.yml`
  key don't exist until implemented — documenting them earlier
  describes vapor.
- **Per-library isolation already exists** (rsync `--delete` on lib
  switch; soft-reset between RAM files).  Reuse it; do not rebuild a
  parallel mechanism.  Source comments at `plugin.py` ~L816-821 /
  ~L1254-1265 encode the constraints.
- Hardware op seen this session: a Lolin S2 CP board needed
  `chumicro-workspace reset-board --yes --device <id>` to clear stale
  read-only CIRCUITPY state before functional tests would deploy.
  Expect this may recur during Phase-2 4-board validation.
- 16 commits in thread 1 are TLS Shape Y (closed); don't let their
  volume in `git log` obscure that thread 2 (0068) is the pickup.
