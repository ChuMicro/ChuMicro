# Deploy-path unification

One mechanism puts code on a board. Today there are several, drifting.

Opened 2026-05-18, out of a full `ChuMicro-Workspace-Template`
revalidation. Research + decisions captured here. The design/unification
work is still **ADR-before-code** (user directive: research/decide
first). Phase 1 is the exception by its own charter (independent
regressions, no design dependency) — the preflight regression is fixed
(2026-05-18); the repl regression remains as a Phase 2 root-cause input.

## The meta-finding (drives the shape of this workstream)

The recurring defect across this whole investigation is **divergent
code paths for one logical operation**, each introduced for a context,
then drifting apart:

- `init` re-implemented "clone the template" beside the documented
  recipe (removed — Decision 0075; the cautionary case in
  [`../decisions/README.md`](../decisions/README.md)).
- `deploy` vs `deploy-example` — two staging implementations, two
  default clean policies, two flag surfaces, for "put a project-shaped
  thing on a board."
- `install-libraries` (circup/mip → board) vs the deploy bundler — a
  second, out-of-band channel that writes `/lib` the deploy walker
  never sees.
- Production deploy (`rsync delete=False`, additive) vs functional-test
  staging (`rsync delete=True` + `FUNCTIONAL_TEST_EXTRA_EXCLUDES`) —
  the same write primitive driven by two different policies, the
  test-only one being the more correct one.
- `libraries/` vs `packages/` — two importable roots by human
  taxonomy; `packages/README.md` says curated libs land in `packages/`,
  `cli/library.py` says `libraries/`. Shipped contradiction.

This is one disease. The fix is not N point-patches; it is converging
on a single pipeline and an invariant that forbids re-divergence. The
invariant belongs in a small `proposed` ADR (Phase 0); the convergence
is this workstream; a CHU lint (Phase 5, per Decision 0074) is the
regression guard.

## Transport audit (committed evidence, not hand-waving)

Audited `circuitpython_transport.py` (`deploy_files` vs `stage` vs
`_stage_to_flash`) and `micropython_transport.py` (`deploy_files` vs
`stage` / `_clean_device_lib` / `wipe_filesystem`):

- **The write primitive is already shared.** CP funnels through
  `flash_drive.rsync`; MP through `mpremote fs cp` + a staging dir.
  There is *not* a separate copy implementation per context.
- **The divergence is policy + post-step, three axes:**
  1. **Delete semantics** — production `delete=False` (additive,
     orphan-prone); test `delete=True`. The core defect.
  2. **Keep set** — production: none; test:
     `FUNCTIONAL_TEST_EXTRA_EXCLUDES = {boot.py, boot_out.txt,
     code.py, settings.toml}`. Used nowhere but tests.
  3. **Post-write step** — production: Ctrl-D → soft-reboot → optional
     tail; test: execute harness via live raw REPL, collect asserts.
- **Axis 3 is irreducible.** "Run a harness and collect results" vs
  "soft-reboot and optionally tail" is a legitimate fork *after* the
  bytes land — it is not a path to delete. The current code wrongly
  couples *how files get there* (must be one) with *what happens
  after* (legitimately two). That coupling is the thing to cut.
- **MP `_did_initial_wipe`/`mkfs`** is a workaround for `fs cp` being
  additive (residue → `ENOSPC`). Under a real keep set its rationale
  changes — see Phase 2 (MP has no `rsync --exclude` analog).

Conclusion: unification is real and tractable — one stage + one
`rsync --delete` + one keep set for project/example/test; a single
explicit post-stage strategy hook for the irreducible axis-3 fork.

## The invariant (Phase 0 ADR — `proposed`, not yet landed)

> There is exactly one mechanism that places code on a board: the
> deploy stage + `rsync --delete` primitive. A project goes through
> it; an example is a project through it (thin shim); a functional
> test is a project-plus-harness through it; a library is bundled by
> it. Nothing stages to a device outside it. Clean-slate is the
> default (`--no-wipe` is the single opt-out). One tool-owned,
> closed keep set survives the wipe: **`{boot_out.txt, boot.py,
> _chu_kv.msgpack}`** — device-generated/-required artifacts only,
> never user code or config. `settings.toml` is never preserved
> anywhere (a board-resident one is a competing wifi authority that
> breaks chumicro's config-driven wifi). Per-context behavior varies
> only in *payload staged* and the post-stage step — never in delete
> semantics, keep set, or transport.

Rationale to record in the ADR: `boot_out.txt` is load-bearing
(chumicro `probe`/identity reads it); `boot.py` is a device necessity
(survives unless the project ships one — then that one is payload);
`_chu_kv.msgpack` is the only filesystem-backed kvstore case (MP
non-NVS boards; CP `nvm` / ESP32 `nvs` are off-filesystem and never at
risk). Rejected, with reasons: additive-default (causes the
circup/mip orphan-drift class), per-context exclude sets, open
user preserve-lists, `settings.toml` preservation.

Phase 0 = write that ADR `proposed`. The audit above confirms the
invariant holds; do not land it `accepted` until Phase 2 implements
against it.

## Phases

**Phase 0 — Decide.** Write the invariant ADR (`proposed`). Settle:
clean-slate default + `--no-wipe`; the closed keep set; `settings.toml`
never preserved (incl. removing it from `FUNCTIONAL_TEST_EXTRA_EXCLUDES`
— unify *downward*); example = shim; `install-libraries` retired;
`libraries/` the one root. ADR-before-code (the discipline lesson from
0038/0075).

**Phase 1 — Independent regressions (no design dependency; do first).**
- ~~`chumicro-workspace preflight` dies `AttributeError: 'Namespace'
  object has no attribute '_env'` at `cli/quality.py:104`~~ **DONE
  2026-05-18.** `_cmd_preflight` built synthetic `Namespace`s for its
  `_cmd_lint` / `_cmd_test` sub-calls that dropped `_env`. Root cause it
  shipped: the three `TestCommandPreflight` tests stub both
  sub-commands, so the synthetic namespaces were never exercised. Fix:
  carry `_env=args._env` into both namespaces + a regression test that
  runs the real composition through an injected `CliEnv` runner.
  `scripts/run.py preflight` is a separate implementation and was never
  affected — the dead gate was the shipped regular-mode wrapper only.
  The lint+test guard for later phases is restored. workspace
  0.31.0→0.31.1.
- `repl <project>` ships a broken `chumicro_timing` (on-device
  `ImportError: no module named 'chumicro_timing.ticks_add'`,
  deterministic, leaves the board dead) while plain `deploy` of the
  same project runs. This is itself an axis-1/2 divergence symptom
  (repl's deploy path ≠ deploy's) — root-cause feeds Phase 2.

**Phase 2 — Unify the write path.** One stage + `rsync --delete` + the
closed keep set for project/example/test. Make the entrypoint *always*
part of the staged payload (project `app.py`→shim, example file→shim,
test file→shim) so `code.py` drops out of the exclude set entirely and
the rsync call is byte-identical across contexts. Extract the
irreducible post-stage step (soft-reboot+tail vs harness-exec+collect)
as an explicit strategy. Resolve **MP keep-set mechanics**: `lfs mkfs`
has no `--exclude`; preserve `{boot_out.txt, boot.py, _chu_kv.msgpack}`
via read-before-mkfs/restore or a scoped delete, not full reformat.

**Phase 3 — Collapse the commands.** `deploy-example` → thin front-end
over `deploy` (resolve example → ephemeral project → same `deploy` →
optional tail); its only unique surface is `--list` + the tail
convenience. Retire `install-libraries`' board-push: library
acquisition (pip; circup/mip only as a *download-to-local* backend)
lands files in `libraries/`, then the one `deploy` bundles them.

**Phase 4 — Root convergence.** `libraries/` is the single importable
root (pip-curated chumicro libs already land there per
`cli/library.py`). Decide `packages/` fate (collapse entirely vs keep
only for its gitignore-by-default behavior) and `shared/` fate. Fix
the `packages/README.md`-vs-`cli/library.py` contradiction as a
consequence, not a standalone patch.

**Phase 5 — Mechanize (Decision 0074).** A `chumicro-checks` rule that
fails if a new device-staging path appears outside the one pipeline,
or if a context grows its own delete/exclude policy. This is the
regression guard that makes the invariant durable.

## Discovered this session, routed (nothing dropped)

- Phases above own: preflight bug, repl regression, deploy/example/
  install-libraries divergence, clean-slate asymmetry, keep-set
  decision, entrypoint-as-payload, MP keep mechanics, circup/mip
  orphan defect, `libraries/`/`packages/` convergence + the
  README/code contradiction, the invariant ADR, the CHU guard.
- **Parked → [`../open-questions.md`](../open-questions.md):** `update`
  is a clone-and-clobber re-flow, not `git fetch`+merge (lineage is
  severed at clone by design). Real latent question, not blocking;
  lower priority than Phases 1–2.
- **Pre-existing, depended-on (not owned here):** the `library`/PyPI
  path is non-functional because chumicro packages have no release
  tags / PyPI project (`check_version` flagged it). User: "doesn't
  matter what's published" for the *design*. Tracked already as
  `next-up.md` "Workspace-template gaps #4b"; Phase 3/4 design must
  not assume PyPI availability.
- **`ChuMicro-Workspace-Template` repo loose ends (that repo, not
  this one) — user to triage:** untracked local-only
  `projects/hello_world`, `projects/two_board_test`,
  `projects/wifi_only/*` (not in the repo; their READMEs still carry
  the old `--device-id` since they were never tracked to fix);
  `.venv.stale.bak/` (session-1 moved-aside broken venv) — safe to
  delete. Decide: commit, delete, or leave.
- **Process (no code):** the ADR-discipline lesson — read a tree's
  governing README/SKILL before contributing into it — is corrected
  and recorded in agent memory; no work item.

## Explicitly NOT in this workstream

- Flash-vs-RAM deploy *mode* — that's
  [`deploy-mode-unification.md`](deploy-mode-unification.md) /
  Decision 0072, a different axis (mode, not path). Cross-reference,
  don't absorb.
- General deploy reliability / FSKit wedges —
  [`workbench-deploy-reliability.md`](workbench-deploy-reliability.md)
  and [`archive/deploy-multi-board-and-fskit-followups.md`](archive/deploy-multi-board-and-fskit-followups.md).
- Publishing chumicro to PyPI — a release decision, not a path-
  unification task (see "depended-on" above).

## Sequence

Phase 0 (ADR `proposed`) → Phase 1 (independent regressions, restores
the preflight gate; repl root-cause feeds Phase 2) → Phase 2 (unify
the write path; the load-bearing structural fix) → Phase 3 (collapse
commands) → Phase 4 (root convergence; falls out of 2–3) → Phase 5
(mechanize). Phase 1 can run in parallel with Phase 0.

## Status

Opened 2026-05-18. **Phase 0 not started** (ADR to be drafted
`proposed`; invariant confirmed by the transport audit above). All
phases pending. No code changed this session — research, decisions,
and this workstream only. Companion *completed* work this session
(`run.py` bootstrap self-heal, `init` retirement / Decision 0075,
template `--device`/ruamel fixes) shipped on `main` of both repos and
is recorded in `next-up.md` `## Done (recent)`; it is the context
that surfaced this workstream, not part of it.
