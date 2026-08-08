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

1. **Flip the default.** **DONE 2026-05-18 (Commit 2b), CP
   bench-verified Pi Pico W.** `deploy_diff(clean: bool = True)` is
   now clean-slate by default: the diff scope is the whole drive
   minus `DEVICE_KEEP_SET` + macOS noise (`_list_scope_on_drive(*,
   clean_slate=)` — all noise is dot-prefixed, so "no path part
   starts with a dot" excludes the class without enumerating it), so
   a stale board `settings.toml` / leftover user file is reconciled
   away with the one-time eviction notice (now also fired from the
   diff-path `delete_files`, guarded once-per-instance). `--no-wipe`
   (`dest=clean`, `store_false`) is the additive opt-out; the
   pre-existing `--wipe` is re-scoped as the *full-erase* escape
   (keep set included) — three coherent levels. The
   `clean_slate`/`clean` kwarg threads protocol → CP/MP transports →
   `FakeTransport` → both recovery wrappers (MP whole-device
   clean-slate landed in delta 6, below). Bench Pi Pico W CP: default `deploy` evicted a planted
   `settings.toml` + `junk.txt`, kept `boot_out.txt`, ran clean;
   `--no-wipe` preserved both. Decision 0077 promoted
   `proposed`→`accepted`; Decision 0059 §1 + its Rejected bullet
   edited in place to cross-link 0077; AGENTS.md gained the
   one-staging-path non-negotiable.
2. **Converge the keep set to 0077's closed `{boot_out.txt, boot.py,
   _chu_kv.msgpack}`.** **CP DONE 2026-05-18 (Commit 2a),
   bench-verified Pico W CP.** One `flash_drive.DEVICE_KEEP_SET`
   constant is now the single source of truth; the CP clean
   `--exclude` and `FUNCTIONAL_TEST_EXTRA_EXCLUDES` both derive from
   it (functional unified *downward* — it no longer keeps
   `settings.toml`). `_chu_kv.msgpack` added (was a real gap — MP
   non-NVS kvstore data was wiped); `settings.toml` evicted from the
   CP clean path with a one-time loud `_notice_settings_toml_eviction`
   (guarded once per transport instance). Bench: a clean
   `deploy-example` on a board carrying a planted `settings.toml`
   printed the notice once, removed `settings.toml`, kept
   `boot_out.txt`, shipped `code.py`. **Deferred to 2b (folds into the
   default-flip):** the `_list_scope_on_drive` diff-path eviction +
   the MP keep-set survive-set — under clean-slate-default every
   deploy goes through the one clean path, so the diff-scope edit and
   MP `_clean_device_lib` survive-set land there, not as a separate
   site. `boot_out.txt`+`boot.py` were already kept (now via the
   constant, not an ad-hoc tuple).
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
4. **Empty-dir reaping** (Phase-1 repl root-cause seam). **DONE
   2026-05-18 (Commit 1b).** CP `delete_files` now sweeps the whole
   `/lib/**` scope bottom-up after unlinking and `rmdir`s every empty
   directory (rsync `--delete` semantics; `rmdir` only removes empties
   so live packages are untouched, lib root preserved). Bench-verified
   Pico W CP: a `wifi_only`→`hello_world` shrink deleted the stale
   `chumicro_msgpack`/`runner`/`wifi`(+`_adapters`) files and reaped
   every now-empty package dir *including* pre-existing husks —
   `/lib` collapsed to just `chumicro_timing/`. 2 unit tests
   (reap-emptied-pkg + keep-dir-with-live-files). **Known narrow
   limitation, deferred to Commit 2:** reaping sits inside
   `delete_files`, which early-returns when no file is stale, so a
   *zero-stale* deploy won't sweep a lingering husk. It prevents *new*
   husks unconditionally (any deploy that empties a package reaps it
   same-call) — the regression class — and a real `--delete` runs
   every deploy regardless; making the sweep unconditional belongs in
   Commit 2's one-clean-primitive restructure, not bolted onto
   `delete_files`. MP's wholesale `rm -r :/lib` already avoids husks.
5. **Entrypoint leaves the exclude set + post-stage fork named.**
   **DONE 2026-05-18 (Commit 2c), CP unit-tested; functional bench
   pending.** The original framing ("test file→shim") was wrong and
   is corrected here: a functional test ships *no* entrypoint at all —
   its harness runs over the live raw REPL, not by booting one
   (Decision 0027). What delta 5 actually does: delete
   `FUNCTIONAL_TEST_EXTRA_EXCLUDES` (0077's named-rejected per-context
   exclude) so the CP functional stage issues the byte-identical clean
   rsync a production deploy does (`--delete` + `DEVICE_KEEP_SET`); a
   stale board `code.py`/`settings.toml` is now reconciled away rather
   than preserved (a real, user-approved behavior change — running the
   functional suite wipes a deployed project, keep set surviving). The
   post-stage fork is named explicitly as `PostStageStep`
   (`SOFT_REBOOT_AND_TAIL` vs `HARNESS_EXEC_OVER_REPL`), recorded on
   the transport so the "identical bytes path, named fork" invariant
   is unit-assertable and Phase 5's lint has a symbol to anchor on.
   **Scope expansion (user-decided 2026-05-18):** delta 5 also
   converged the MP functional path — its first copy-mode stage
   blind-`lfs mkfs`'d the whole filesystem (destroying
   `_chu_kv.msgpack`/`boot_out.txt`, a deeper 0077 keep-set violation
   than the CP carve-out). It now calls the same `_clean_slate_device`
   as `deploy_files(clean=True)`. Decision 0071's per-library
   tracked-delete on subsequent MP stages is the orthogonal mode-axis
   mechanism and is unchanged (keep-set-safe by construction). This
   resolved the `open-questions.md` "MP copy-mode sweep dirty board"
   entry (deleted) and added a 0077↔0071 cross-link both ways.
6. **MP keep-set mechanics.** `lfs mkfs` has no `--exclude`; the
   `{boot_out.txt, boot.py, _chu_kv.msgpack}` set survives via
   read-before-mkfs/restore or scoped delete (the existing
   `_clean_device_lib` scoped `rm -r :/lib` already is the scoped-delete
   shape — extend its survive-set, don't switch to mkfs).

*Sequencing (user-decided 2026-05-18): seams first, then convergence.*
**Commit 1a — DONE 2026-05-18:** delta 3 by elimination
(`repl <project>` retired → `deploy --tail`); bench-verified Pico W
CP. **Commit 1b — DONE 2026-05-18:** delta 4 (empty-dir reaping),
bench-verified Pico W CP. **Commit 1 (the seams) complete.**
**Commit 2a — DONE 2026-05-18:** keep-set constant + CP clean-path
`settings.toml` eviction + one-time notice + `_chu_kv.msgpack` keep,
bench-verified Pico W CP. **Commit 2b — DONE 2026-05-18,
bench-verified Pico W CP:** clean-slate default-flip + `--no-wipe` +
`--wipe` re-scope + diff-path eviction notice; 0077
`proposed`→`accepted`; 0059 §1 edited in place; AGENTS.md
non-negotiable added. **Delta 6 — MP keep-set survive-set — DONE
2026-05-18, bench-verified Pi Pico W MP:** `_clean_device_lib` →
`_clean_slate_device` (scoped delete of every root entry except the
keep set, via an mpremote `exec` subprocess — not the persistent
serial, which would hold the port the following `fs cp` needs; that
ordering bug was caught + fixed on the bench); MP
`list_files_in_scope(clean_slate=True)` walks the whole device
(`_LIST_ALL_SCRIPT`) and host-filters keep set + dotfiles. Bench: a
clean `deploy-example` on a board full of stale `test_*.py` +
`settings.toml` + `junk.txt` collapsed to payload + `_chu_kv.msgpack`
(keep set). **Commit 2c — DONE 2026-05-18, CP unit-tested + MP functional
converged; functional bench pending:** delta 5 — `FUNCTIONAL_TEST_EXTRA_EXCLUDES`
deleted (CP functional now the byte-identical clean rsync), post-stage
fork named (`PostStageStep`), MP functional first-stage `mkfs`→
`_clean_slate_device` (keep-set-preserving), 0077 entrypoint clause
corrected in place + 0077↔0071 reconciled, `open-questions.md`
MP-dirty-board entry resolved. Original Commit 2 = deltas
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

**Phase 3 — Collapse the commands. COMPLETE 2026-05-19**
(design settled 2026-05-18 ADR-before-code, all forks user-decided;
shipped over Commits 3a–3d, CP/MP unit-tested, functional bench
pending). Two collapses, both in this Phase (user: "Both A and B").
Mechanism lives here; the ADRs state only the invariant (README
"what does NOT belong in a decision record").

*Collapse A — `deploy-example` → thin front-end (the 0077-load-bearing,
self-contained part; implements accepted 0077 + 0059 §1, no new ADR).*
Verified in code, `deploy-example` diverges from `deploy` on **two**
axes, not one:

- *Source builder* — `deploy` routes through
  `cli/deploy.py:resolve_project_deploy_source` (single source owner,
  four `WithRuntimeConfig` front-ends, Phase 2 Commit 1).
  `deploy-example` routes via its own
  `cli/examples.py:_build_deploy_example_source` → `example_source()`
  — the parallel staging source 0077 names in its Rejected list.
- *Stage primitive (the load-bearing one)* — `deploy` calls
  `runner.deploy_diff(source, clean=True, wipe=, on_file_deleted=)`:
  the 0077-conformant clean-slate path Phase 2 built (`deployer.py`).
  `deploy-example` calls `runner.deploy(source, clean=, tail_seconds=)`
  — `Deployer.deploy()`, the *additive, no-reconcile, no-keep-set-scope*
  primitive. Even `clean=True` there is just the legacy CP
  exclude-tuple rsync. **`deploy-example` is the last CLI command
  bypassing the unified stage primitive** — the parallel
  `example_source` builder is secondary; `deploy()` vs `deploy_diff()`
  is the real 0077 violation.

The audit's "one parameterized builder + thin front-ends" was the
*wrong* cut and 0077 says why: per-context variance is legitimate in
the *payload* (which inner `FileSource`) and forbidden in
stage/delete/keep/transport. The five inner-source constructors
(directory walk, AST import-graph walk, synthesized shim, shim+graph
merge, example-path resolver) are the legitimate payload fork, not
duplication; don't merge the front-ends. The settled mechanism:

1. **Source: `ExampleSpec` branch on `resolve_project_deploy_source`**
   (user-chosen over a sibling resolver — one function owns project +
   example source policy, literally "route `example_source` through
   the dispatcher"). New `example: ExampleSpec | None` param; the
   example branch bypasses `_resolve_deploy_layout` (no on-disk
   project shape) and returns `("example", wrapped)`. Not a `mode=`
   string with inner-source conditionals — that is 0077's forbidden
   re-coupling. `example_source`'s `ImportGraphSource` construction
   stays intact as the 5th inner constructor.
2. **Stage: `_cmd_deploy_example` calls `runner.deploy_diff(...)`**
   byte-identical to `_cmd_deploy`. Consequently `Deployer.deploy()`
   + the `Interactive/NonInteractiveDeployer.deploy()` wrapper
   methods are **deleted** (user: nothing published, sole consumer is
   us → dead code per the no-backwards-compat rule, not a public-API
   ADR). `_cmd_demo` and the low-level `chumicro-deploy deploy` CLI
   (`workbench/deploy/src/chumicro_deploy/cli.py:264`) fold onto
   `deploy_diff` (add `--no-wipe`/`--wipe` parity to the low-level
   CLI); the 4 `workbench/deploy/examples/*.py` programmatic scripts +
   the `result.py` docstring are rewritten to the `deploy_diff` API
   (`verify-examples` must stay green). Exactly one stage primitive
   remains — Phase 5's lint then has zero sanctioned bypass.
3. **Tail: keep the interactive REPL drop** (user-chosen). 0077
   explicitly leaves the post-stage step a legitimate per-context
   fork (`PostStageStep`); a first-touch front door wants to
   *interact*, not a bounded capture. `deploy-example` keeps dropping
   into `chumicro_repl` (route through the entrypoint cleanly);
   `deploy --tail` keeps its bounded `tail()`.
4. **Tail-dedup helper (audit bullet 2, fold into the same commit):**
   one `wrap_with_runtime_config(inner, *, project_dir,
   search_paths=None, workspace=None, secrets_toml=None,
   output_path=None)` in `deploy_source.py` (the module owning
   `WithRuntimeConfig`) absorbing the 3–4× duplicated default
   resolutions — `find_library_roots(search_paths)` + its repeated
   4-line comment (`example_source.py:223`, `import_graph.py:287`,
   `boot_shim.py:502`), `secrets_toml = workspace.secrets_toml` 3×
   (`boot_shim.py:293,452`; `import_graph.py:249`),
   `project_dir / GENERATED_DIRNAME / "runtime_config.msgpack"` 3×,
   `find_project_config(project_dir)` 4×. Each front-end keeps its own
   inner-source construction and ends with one call — collapses the
   dup *without* merging front-ends. Normalize `boot_shim.py:35`'s
   `chumicro_deploy.runtime_marker` import to the package root (audit
   bullet 3) since the file is touched.

What stays unique to `deploy-example` and is untouched (0059,
0077-sanctioned): `--list`, the precheck stack, the four first-touch
board states + bootstrap wizard, runtime-marker disambiguation,
distinct exit codes, recovery coaching, the `--tail`/`--no-tail`/
`--non-interactive` UX. Boundary contract is otherwise clean
(`chumicro_workspace` → `chumicro_deploy` only, no cycle, declared in
pyproject; `FileSource` `@runtime_checkable`, all inner sources
duck-type it honestly).

*Collapse B — library acquisition.* **[Decision
0078](../decisions/0078-library-acquisition-is-host-local.md)
`accepted`.** The 3d shape (`install-libraries` AST-discovers imports,
pip/mip `--target`-fetches each into a gitignored
`<workspace>/_libraries/<name>/src/` blob, registers a parallel
regular-mode `library_sources:` block) was wrong from the get-go: a
second acquisition subsystem beside the curated `library` path, a
flattened site-packages blob mislabeled as one library's `src/`, and
AST-discovery that finds nothing on a fresh project (you cannot import
what isn't acquired). 0078 was rewritten in place (a
wrong-from-the-start correction, not a superseding ADR — the
AGENTS.md ADR rule). Corrected design: declarative
`chumicro-workspace library add` pulls a library's full editable tree
plus its `pyproject` closure from a published snapshot channel
(`ChuMicro/ChuMicro-Libraries[-Experimental]`, circup/mip-shaped tags,
single-snapshot internally-consistent closure) into **committed
`libraries/<name>/`**, edit-preserving (`_library-backups/<name>/`
before any replace), one engine behind a prompt_toolkit browser and a
scriptable non-interactive `library add`. Landed: `library_channel.py`
(snapshot resolve + one-tarball/extract-subtree, 100 % cov) +
`library.py` rewired off pip-sdist onto it with single-snapshot
closure (converged onto `dep_resolver.transitive_closure`) +
edit-preserving placement; `CliEnv.http_get` seam; the entire
`install-libraries`/`_libraries`/pip-mip subsystem
(`install_libraries.py`, `cli/install_libraries.py`, its tests,
parser wiring) deleted; `.gitignore` `_libraries/`→`_library-backups/`.
Remaining: the prompt_toolkit browser front-end (engine + scriptable
`add` done); the promote-pipeline full-tree channel + catalog index
(Phase, CI-gated). Per-library version pinning is gated on a
`pyproject` version-constraint decision — generalized into
`open-questions.md`. Workspace-template `.gitignore` +
regular-mode README are cross-repo, separate, user-gated.

**Phase 4 — Root convergence.** Largely subsumed by the corrected
Collapse B: the rewired `library` path is the single acquisition
mechanism and `libraries/` the single committed importable root, so
the parallel-root problem is gone. Residual, standalone: decide
`packages/` fate (collapse vs keep for its gitignore-by-default
behavior) and `shared/` fate, and fix the
`packages/README.md`-vs-`cli/library.py` contradiction.

*Investigation (2026-07-04) — evidence gathered, recommendation KEEP;
**decided KEEP by user nod the same day.***

**Where the roots live.** `packages/` and `shared/` are workspace roots
— they exist only in the user-workspace layout, present in
`ChuMicro-Workspace-Template` (`packages/{README.md,.gitignore}`,
`shared/README.md`), absent from this mono-repo. All three roots are
defined on `chumicro_workspace.WorkspaceLayout`
(`workspace.py:shared_dir/libraries_dir/packages_dir`).

**Who consumes them (grep, both repos).** All three are live payload
inputs, not dead scaffold: `import_graph.build_search_paths`
(`import_graph.py:130,133-137,138`) appends each to the import-resolution
search path in a documented precedence order — `library_sources`
override → `shared/` → each `libraries/<name>/src/` → `packages/` →
caller tail — feeding one `ImportGraphSource` and thus one
`Deployer.deploy_diff()`. So the three roots are three *payload* sources
behind the single staging path, not three staging paths. The CHU rule
root-lists (`chu001/006/008/012` `_SCOPED_ROOTS`) also enumerate all
three as known workspace roots.

**The named contradiction is already resolved.** The current
`packages/README.md` scopes `packages/` to **third-party / vendored**
trees (gitignored by default via `packages/.gitignore` — everything bar
`README.md`/`.gitignore`), *not* curated chumicro libraries;
`shared/README.md` carries an explicit "When to use shared/ (vs
libraries/)" table; `cli/library.py` puts curated libs in `libraries/`.
The three roots partition the space cleanly (third-party → `packages/`;
flat user helpers → `shared/`; curated/publishable → `libraries/`). The
`packages/README.md`-says-curated / `cli/library.py`-says-`libraries/`
clash the meta-finding named was closed by template commit `2f8a24c`
(rewrote both READMEs, dropped the stale empty `libraries/` scaffold,
gave `packages/` its README). A mono-repo grep finds no live doc
telling users curated libs go in `packages/` — the only surviving
instance is this workstream's own meta-finding line. No fix outstanding.

**Recommendation — KEEP all three; collapse nothing.** Each root does
work the others cannot: `packages/` uniquely gives **gitignore-by-default**
for big/license-varied third-party trees (collapsing it into `libraries/`
forces either committing those trees or making `libraries/` gitignored,
which breaks Collapse-B's committed-curated-root invariant); `shared/`
uniquely gives a **zero-ceremony flat-module** root (collapsing it
imposes `pyproject`/`src/`/`tests/`/`VERSION` on a single helper file —
the ceremony it exists to avoid); `libraries/` is the curated root.
This is the same shape Phase 3 blessed for sources: legitimate *payload*
variance behind one staging path, which 0077 permits (variance in
*payload*, never in stage/delete/keep/transport). The disease the
meta-finding diagnosed was the parallel *acquisition mechanism*
(`install-libraries` vs `library`), closed by Collapse B — not the root
count. Collapse cost is high (rewrite `build_search_paths`, the
`WorkspaceLayout` properties, three READMEs, four CHU root-lists) to
delete a distinction that is load-bearing; no evidence of drift or user
confusion from the three-root taxonomy in its post-`2f8a24c` form.
**Decided: KEEP** (user nod 2026-07-04) — the three-root taxonomy
stands; `packages/` / `shared/` / `libraries/` remain three documented
payload roots behind the one `Deployer.deploy_diff()` staging path.
With this, every phase of the workstream is closed.

**Phase 5 — Mechanize (Decision 0074). DONE 2026-07-04 — `CHU034`.** A
`chumicro-checks` rule that fails if a new device-staging path appears
outside the one pipeline. Shipped as `CHU034`: outside the
`chumicro_deploy` package (the `workbench/deploy/` tree that owns and
orchestrates the primitives), no `.py` under `libraries/` / `support/`
/ `workbench/` may call the reserved transport primitives
`deploy_files` / `delete_files` / `list_files_in_scope` — the write-
and-execute + diff-reconcile trio `Deployer.deploy_diff()` exclusively
owns. A direct call elsewhere is a second staging path or a context
growing its own delete scope (the "grows its own delete/exclude policy"
half of the spec — `delete_files`/`list_files_in_scope` are the delete-
policy primitives). AST match by method name, `# noqa: CHU034`
escapable, syntax errors surface as findings. Zero violations on the
current tree on first run (the three primitives had zero external
callers post-Phase-3 — the convergence already removed them). The
sanctioned second-axis primitives are deliberately *not* reserved:
`stage` (harness-over-REPL staging — pytest-device + the demo runner),
`clear_entrypoints` (per-session entrypoint clear), and
`wipe_filesystem` (standalone destructive erase — `reset-board`);
reserving them would fire on legitimate mode-axis code. This is the
narrowest rule that catches the drift class Phases 0-3 eliminated
(commands re-implementing the write path — `repl`'s deploy, `deploy-
example`'s `Deployer.deploy()`); the "context grows its own *exclude*
constant" sub-class (the deleted `FUNCTIONAL_TEST_EXTRA_EXCLUDES`) is
not separately linted — it collapsed into `flash_drive.DEVICE_KEEP_SET`
and any re-divergent staging that would consult a rogue exclude set
must still call one of the three reserved primitives to land bytes, so
`CHU034` catches it at the call site. Registered in
`rules/__init__.py`; README rule table + range; AGENTS.md
one-staging-path non-negotiable cross-references it; `chu034` tests in
`workbench/checks/tests/test_chu034.py`.

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
  [`deploy-mode-unification.md`](archive/deploy-mode-unification.md) /
  Decision 0072, a different axis (mode, not path). Cross-reference,
  don't absorb.
- General deploy reliability / FSKit wedges —
  [`workbench-deploy-reliability.md`](archive/workbench-deploy-reliability.md)
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
**`accepted` 2026-05-18** (CP path implemented + bench-verified).
**Phase 1 done** — preflight `_env` fixed; repl `chumicro_timing`
root-caused + structurally fixed. **Phase 2 — Commits 1a/1b/2a/2b
done, all bench-verified Pi Pico W CP:** single source owner
(repl retired → `deploy --tail`), CP empty-dir reaping, keep-set
unification + `settings.toml` eviction, clean-slate default-flip
(`--no-wipe`/`--wipe`) + 0077 promotion + 0059 §1 in-place edit +
AGENTS.md non-negotiable; delta 6 (MP keep-set survive-set,
bench-verified Pi Pico W MP). **Commit 2c done 2026-05-18 (delta 5),
CP unit-tested + MP functional converged — functional-suite bench
the one remaining hardware step:** `FUNCTIONAL_TEST_EXTRA_EXCLUDES`
deleted (CP functional = the byte-identical clean rsync; stale board
`code.py` now reconciled away), post-stage fork named (`PostStageStep`),
MP functional first-stage `mkfs`→`_clean_slate_device`, 0077
entrypoint clause corrected + 0077↔0071 reconciled.
**Phase 2 complete. Phase 3 complete 2026-05-19** (design settled
2026-05-18 ADR-before-code, all forks user-decided; shipped over
Commits 3a–3d, CP/MP unit-tested + preflight-green, functional bench
the one open hardware step): Collapse A — `wrap_with_runtime_config`
tail-dedup (3a), `deploy-example` → `ExampleSpec` branch on
`resolve_project_deploy_source` + `deploy_diff` with interactive REPL
drop retained (3b), `Deployer.deploy()` + wrapper `.deploy()` deleted
/ demo + low-level `chumicro-deploy` CLI folded onto `deploy_diff` /
4 example scripts + deploy guide rewritten (3c) — one stage primitive,
zero CLI bypass; Collapse B —
**[Decision 0078](../decisions/0078-library-acquisition-is-host-local.md)
`accepted`** (3d's `_libraries/` pip/mip-`--target` fetch was
wrong-from-the-start; 0078 rewritten in place → declarative
`library add` pulls full editable trees + closure from a published
snapshot channel into committed `libraries/`, edit-preserving; engine
rewired (`library_channel.py` + `library.py`), `install-libraries`
subsystem deleted; browser front-end + promote-pipeline channel
remain). **Phase 5 done 2026-07-04 — `CHU034`** (device-staging
primitives reserved to `chumicro_deploy`; zero violations on first run;
tests + README + AGENTS.md cross-ref shipped). **Phase 4 decided
2026-07-04 — KEEP all three roots (user nod), workstream fully
closed** (the named `packages/README.md`↔`cli/library.py` contradiction
was already closed by template commit `2f8a24c`; `packages/` /
`shared/` / `libraries/` are three documented *payload* roots behind
one `Deployer.deploy_diff()`, each load-bearing — evidence + costs in
the Phase 4 section above; not decided unilaterally). Companion
*completed* work this session
(`run.py` bootstrap self-heal, `init` retirement / Decision 0075,
template `--device`/ruamel fixes) shipped on `main` of both repos
(see `git log` around the deploy-path-unification surfacing for the
landing commits); it is the context that surfaced this workstream,
not part of it.
