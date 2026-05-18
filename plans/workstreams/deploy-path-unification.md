# Deploy-path unification

One mechanism puts code on a board. Today there are several, drifting.

Opened 2026-05-18, out of a full `ChuMicro-Workspace-Template`
revalidation. Research + decisions captured here. The design/unification
work is still **ADR-before-code** (user directive: research/decide
first). Phase 1 is the exception by its own charter (independent
regressions, no design dependency) — the preflight regression is fixed
(2026-05-18) and the repl regression is root-caused (2026-05-18) and
written up as a Phase 2 input; Phase 1 is closed.

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

Phase 0 = write that ADR `proposed`. **Done 2026-05-18 —
[Decision 0077](../decisions/0077-one-device-staging-path.md).** The
audit above confirms the invariant holds; 0077 stays `proposed` and is
promoted to `accepted` only when Phase 2 implements against it, at
which point Decision 0059 §1 gets its in-place partial-supersession
edit (not before — 0059 is the accurate accepted reality until then).

## Phases

**Phase 0 — Decide. DONE 2026-05-18 —
[Decision 0077](../decisions/0077-one-device-staging-path.md)
(`proposed`).** Settled: clean-slate default + `--no-wipe`; the closed
keep set; `settings.toml` never preserved (incl. removing it from
`FUNCTIONAL_TEST_EXTRA_EXCLUDES` — unify *downward*); example = shim;
`install-libraries` retired; `libraries/` the one root. The 0059 §1
conflict is named in 0077's Rejected list; its in-place edit is
deferred to 0077's promotion (ADR-before-code, the discipline lesson
from 0038/0075).

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
- `repl <project>` leaves the board dead with `ImportError: no module
  named 'chumicro_timing.ticks_add'` while plain `deploy` of the same
  project runs. **Root-caused 2026-05-18 (static + bench, Pico W CP,
  `hello_world`) — feeds Phase 2, no isolated patch.** Mechanism:
  `cli/repl.py` unconditionally uses `project_boot_source`, whose
  `_BootShimSource.files()` is shim + project files only — **zero
  library payload** (no import-graph walk, no `library_sources`, no
  `/lib/`). `cli/deploy.py` instead runs `_resolve_deploy_layout()` and
  for the standard `app.py`+`run()` shape auto-selects
  `project_boot_with_import_graph_source` (boot-shim **+**
  `ImportGraphSource` → ships `chumicro_timing` under `/lib/`). Both go
  through `deploy_diff`, which deletes `list_files_in_scope() − source`;
  CP-flash scope (`_list_scope_on_drive`) is **all of `/lib/**`
  recursively**, so repl's library-less source makes the *entire*
  `/lib/chumicro_timing/` tree a prior `deploy` placed stale and
  wholesale-deletes it (bench: logged `removed stale
  /lib/chumicro_timing/{__init__,heartbeat,ticks}.py`; dir left an
  empty husk; `ImportError` every boot). The submodule-shaped error
  string is just CP's phrasing for `from chumicro_timing import
  ticks_add` when the whole package is absent — **falsified**: not a
  partial tree, and *not* linked to the separate deploy-walker
  silent-skip item (red herring from the error string). Secondary,
  noted not fixed here: repl's `_emit_failure_hints` misclassifies this
  as "library not installed in this venv — run `python run.py setup`"
  (the library is fine; repl's own path deleted it on-device). The
  naive fix — teach repl to resolve the layout like `deploy` — is
  exactly the per-context source-selection divergence
  [Decision 0077](../decisions/0077-one-device-staging-path.md) forbids;
  Phase 2 makes repl deploy *through* the one staging path rather than
  owning a second source policy. Corroborating axis-1 evidence seen on
  the same drive: additive orphans (`test_ntp.py` at root, empty
  `chumicro_config/` package dirs) — `deploy_diff` deletes stale files
  but not the now-empty package directories.

**Phase 2 — Unify the write path.** One stage + `rsync --delete` + the
closed keep set for project/example/test, entrypoint always staged as
payload, the post-stage step the one explicit fork.

*The mechanism already exists — Phase 2 is policy convergence, not a
rebuild.* `example-sweep-stability` shipped (2026-05-10) the `clean:
bool` kwarg plumbed end-to-end: `Deployer.deploy`/`deploy_files` → CP
`flash_drive.rsync(delete=clean)` + MP `_clean_device_lib` (wholesale
`rm -r :/lib` before `fs cp`; mount-mode no-op by design), with a
`{settings.toml, boot.py, boot_out.txt}` clean-exclude tuple at CP+MP
parity, `deploy-example` passing `clean=True`, `--no-clean` to opt out.
The `boot_out.txt`-stranding incident there (clean rsync wiped it; CP
only rewrites it on hard reset, not the deploy soft-reboot; loss →
multi-board UID mis-match → silent wrong-drive landing) is **bench
proof for [Decision 0077](../decisions/0077-one-device-staging-path.md)'s
keep set** — do not regress it. Verified in code: `deployer.py:265`
`clean=False` default; `circuitpy_drive.py:_list_scope_on_drive` scopes
`settings.toml` *out* (a second place it's protected, independent of
the exclude tuple).

The convergence deltas (the actual Phase 2 work):

1. **Flip the default.** `clean=False` → clean-slate default;
   `--no-clean` becomes the single `--no-wipe` opt-out (0077). Every
   context (project/example/test) inherits it; per-context callers stop
   choosing. Behavior-visible change on *every* `chumicro-workspace
   deploy` — the headline risk to flag.
2. **Converge the keep set to 0077's closed `{boot_out.txt, boot.py,
   _chu_kv.msgpack}`.** `boot_out.txt`+`boot.py` already excluded
   (keep). **Add `_chu_kv.msgpack`** — currently *not* preserved (MP
   non-NVS kvstore data is wiped on a clean deploy: a real gap).
   **Evict `settings.toml`** — 0077's deliberate call (board-resident
   `settings.toml` = competing wifi authority, Decision 0057).
   *Resolved with the user 2026-05-18: evict + a one-time loud warning*
   — when a clean deploy finds a pre-existing board `settings.toml`,
   print a prominent one-time notice naming the file and pointing at
   host-side `secrets.toml` before removing it (softer migration than a
   silent wipe; reverses the deliberate `example-sweep-stability`
   keep).
   **Why `settings.toml` is protected in *two* places — it is the
   disease, not two features.** Site A: the clean-exclude tuple on the
   `clean=True` *wipe-then-restage* path (CP `rsync --exclude`, MP
   `_clean_device_lib` survive-set). Site B: `_list_scope_on_drive`'s
   out-of-scope omission on the `deploy_diff` *reconcile* path (a file
   not "in scope" is never a stale-deletion candidate). Two staging
   paths (`clean` wipe vs `diff` reconcile) each grew an independent
   notion of "what survives," encoded differently and free to drift
   (Site A protects `{settings.toml, boot.py, boot_out.txt}`; Site B's
   scope is `{code.py, main.py, active.py, runtime_config.msgpack,
   /lib/**}` so `boot.py`/`boot_out.txt` are protected only by *being
   unscoped*, for a different reason than Site A's explicit exclude).
   This is exactly the meta-finding. Phase 2 collapses both into **one
   keep-set constant** consulted by the one unified path — the
   convergence *is* the answer to "why two sites." `runtime_config.msgpack`
   is **payload, not keep-set** (re-staged
   every deploy via `WithRuntimeConfig`; correctly absent from 0077's
   set — noted so a reader doesn't read it as a missing entry).
3. **Single source-selection owner** (Phase-1 repl root-cause seam).
   **DONE 2026-05-18 (Commit 1) — done by *elimination*, the stronger
   form.** A user question ("why does repl deploy at all?") reframed
   the fix: rather than make `repl` *share* `deploy`'s source policy
   (dedupe), `repl <project>`'s deploy path was *retired entirely* and
   the deploy-then-watch convenience moved onto the one deploy path as
   `deploy <project> --tail [SECONDS]`. `repl` now owns only
   interactive / standalone-tail and never stages code. The shared
   `resolve_project_deploy_source` owner (extracted in
   `cli/deploy.py`, used by `_cmd_deploy`) is the single source policy;
   no command owns a second. Bench-verified Pico W CP: `repl
   hello_world` → clean argparse rejection (was board-dead);
   `deploy hello_world --tail` → deploys through the one path (ships
   `chumicro_timing`) + tails, board healthy. Docs (workspace README
   command table + quickstart + dep notes) updated lockstep; the
   second deploy orchestration in `_cmd_repl` is deleted, not
   deduped — the regression class is now structurally impossible.
   CLI surface change (`repl <project>` retired) is intentional and
   user-approved.
4. **Empty-dir reaping** (Phase-1 repl root-cause seam). CP
   `_list_scope_on_drive`+`delete_files` deletes files only, leaving
   `/lib/<pkg>/` husks (stale `import <pkg>` fails mid-package). MP's
   wholesale `rm -r :/lib` already avoids this; CP must prune empty
   dirs. Directory pruning is part of the keep-set spec.
5. **Entrypoint always payload + post-stage fork.** Project `app.py`→
   shim, example file→shim, test file→shim, so `code.py` leaves the
   exclude set and the rsync is byte-identical across contexts. The
   irreducible post-stage step (soft-reboot+tail vs harness-exec+
   collect) is an explicit strategy, not a hidden coupling.
6. **MP keep-set mechanics.** `lfs mkfs` has no `--exclude`; the
   `{boot_out.txt, boot.py, _chu_kv.msgpack}` set survives via
   read-before-mkfs/restore or scoped delete (the existing
   `_clean_device_lib` scoped `rm -r :/lib` already is the scoped-delete
   shape — extend its survive-set, don't switch to mkfs).

*Sequencing (user-decided 2026-05-18): seams first, then convergence.*
**Commit 1a — DONE 2026-05-18:** delta 3 by elimination
(`repl <project>` retired → `deploy --tail`); bench-verified Pico W
CP. **Commit 1b — next:** delta 4 (empty-dir reaping), the remaining
seam. **Commit 2** = deltas
1+2+5+6 (default-flip, keep-set convergence incl. `settings.toml`
evict-with-warning + `_chu_kv.msgpack` add + the two-site collapse,
entrypoint-as-payload, MP mechanics) — the every-deploy-visible policy
change; promotes 0077 `proposed`→`accepted` and triggers the deferred
0059 §1 in-place edit. Commit 2 is gated on Commit 1 landed +
bench-clean.

Constraints Phase 2 must honor (cross-workstream, verified):

- **`cross-runtime-harness-class-support` `--per-file`** (Decision
  0072, implemented) re-stages per library through
  `_bulk_stage_for_device`; its bench finding that `--per-file` ENOSPC-
  failed all 299 tests on a *stale* flash but passed on a freshly
  `reset-board`-wiped Pico W is **further evidence for clean-slate
  default** — Phase 2's flip helps it; do not break per-file/per-library
  staging isolation.
- **`deploy-mode-unification` (COMPLETE)** owns the RAM/flash *mode*
  axis (orthogonal — 0077 says so). Its pytest-device per-library
  `rsync --delete` + soft-reset isolation (`plugin.py
  _bulk_stage_for_device`) is the *already-correct policy* the CLI path
  is converging toward — reuse, do not rebuild. Mount-mode `clean`
  no-op is by design (transient); preserve.
- **`walker-unresolved-import-failure` (open, `proposed`)** shares the
  `sources.py`/`ImportGraphSource` neighborhood the single-source-owner
  change touches. Independent defect (the repl↔walker link was
  falsified on-device); cross-reference, do not absorb or block on it.

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

Opened 2026-05-18. **Phase 0 done** —
[Decision 0077](../decisions/0077-one-device-staging-path.md)
`proposed` (invariant confirmed by the transport audit above; promotes
to `accepted` at Phase 2). **Phase 1 done** — preflight `_env`
regression fixed 2026-05-18; the repl `chumicro_timing` regression
root-caused 2026-05-18 (static + bench, Pico W CP) and written up as a
Phase 2 input (no isolated patch — the fix is the unified source path).
Phases 2–5 pending. The structural code change is Phase 2 (still
ADR-before-code: 0077 is the gate, now written; Phase 1 fully closed —
both regressions resolved/root-caused, Phase 2 has its concrete seam). Companion *completed* work this session
(`run.py` bootstrap self-heal, `init` retirement / Decision 0075,
template `--device`/ruamel fixes) shipped on `main` of both repos and
is recorded in `next-up.md` `## Done (recent)`; it is the context
that surfaced this workstream, not part of it.
