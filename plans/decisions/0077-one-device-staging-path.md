# Decision 0077: One device-staging path (deploy-path unification invariant)

Status: `proposed`
Date: `2026-05-18`
Related: Decision [0059](0059-deploy-example-front-door.md) (deploy-example front door — its §1 separate `example_source` staging path is partially superseded on this ADR's promotion), Decision [0028](0028-deploy-modes.md) / [0068](0068-unified-deploy-mode-resolution.md) / [0072](0072-large-test-modules-on-constrained-boards.md) (flash-vs-RAM *mode* — an orthogonal axis, not absorbed here), Decision [0074](0074-drift-mechanization-as-project-policy.md) (the lint that makes this invariant durable), Decision [0075](0075-retire-init-creation-is-clone-only.md) / [0038](0038-workspace-bootstrap-via-clone.md) (the divergence-by-convenience drift class this invariant exists to stop), Decision [0057](0057-two-file-config.md) (why a board-resident `settings.toml` is a competing authority), Workstream [`deploy-path-unification`](../workstreams/deploy-path-unification.md).

## Context

Several code paths place code on a board — `init`'s clone re-implementation (removed, Decision 0075), `deploy` vs `deploy-example`, `install-libraries`' out-of-band `/lib` write vs the deploy bundler, production `rsync delete=False` vs functional-test `delete=True`, `libraries/` vs `packages/` as the importable root. Each was introduced for one context and drifted from the others. The most damaging drift is additive-by-default production deploy: circup/mip-installed libraries are orphaned, never reconciled, and the failure surfaces only at first boot on the board.

A transport audit (recorded in the workstream) establishes the write primitive is *already* shared — CP funnels through `flash_drive.rsync`, MP through `mpremote fs cp` + a staging dir. The divergence is policy and post-step on three axes: delete semantics, keep set, and post-stage step. Only the post-stage step is an irreducible fork. This is one disease; N point-patches re-grow it. The fix is convergence plus an invariant that forbids re-divergence.

## Decision

There is exactly one mechanism that places code on a board: the deploy stage + `rsync --delete` primitive. Per-context behavior varies **only** in the payload staged and the post-stage step — never in delete semantics, keep set, or transport. Nothing stages to a device outside this mechanism.

- **Clean-slate is the default.** `--no-wipe` is the single opt-out. Additive staging is not a per-context option.
- **One tool-owned, closed keep set survives the wipe:** `{boot_out.txt, boot.py, _chu_kv.msgpack}` — device-generated or device-required artifacts only, never user code or config. `boot_out.txt` is read by chumicro `probe`/identity; `boot.py` is a device necessity *unless the project ships one*, in which case that one is payload and overwrites; `_chu_kv.msgpack` is the only filesystem-backed kvstore case (MP non-NVS boards — CP `nvm` / ESP32 `nvs` are off-filesystem and never at risk).
- **`settings.toml` is never preserved anywhere**, including removal from the functional-test exclude set (unify *downward* to the stricter policy). A board-resident `settings.toml` is a second wifi authority competing with chumicro's config-driven wifi (Decision 0057) — a silent-wrong-credentials class, not a convenience.
- **The post-stage step is the one legitimate fork** and is an explicit strategy, not a hidden coupling: "soft-reboot then optionally tail" (project/example) vs "execute the harness over live raw REPL and collect asserts" (functional test). This fork happens strictly *after* the bytes land; it never changes how they got there.

The entrypoint is always part of the staged payload (project `app.py` → shim, example file → shim, test file → shim) so `code.py` leaves the exclude set entirely and the rsync call is byte-identical across contexts.

## Rejected

- **Additive default (`delete=False`).** The direct cause of the circup/mip orphan-drift class — the defect that opened this workstream. The more-correct policy already existed, used only by functional tests.
- **Per-context exclude sets** (e.g. `FUNCTIONAL_TEST_EXTRA_EXCLUDES`). A per-context knob is exactly the seam future drift grows in; the invariant permits one closed set or none.
- **Open user preserve-lists.** Any user-extensible keep list reintroduces "this board has stale state the deploy won't reconcile." The keep set is closed and tool-owned.
- **Preserving `settings.toml`** (the prior functional-test behavior). Convenience that ships a competing wifi authority; unify to the stricter rule.
- **A separate staging source per context** — concretely, Decision 0059 §1's standalone `example_source` and its "an example is not a project / keep `deploy` as the only deploy command — Rejected" framing. That created a parallel staging implementation for what is structurally a project. An example is a project through this one pipeline (a thin shim); 0059's precheck stack, four-state UX, exit codes, recovery coaching, and `--list` are unaffected and stand.

## Consequences

- The invariant is `proposed`, not `accepted`: it is confirmed by the transport audit but is not in force until Phase 2 of the workstream implements against it. **On promotion to `accepted`**, Decision 0059 §1 gets an in-place partial-supersession edit (its separate `example_source` staging path → "example is a project through the one pipeline"); until then 0059 remains the accurate accepted reality and is not edited.
- Mechanism consequences that follow from the single-path rule (sequenced in the workstream, not re-listed as separate decisions): `deploy-example` collapses to a thin front-end over `deploy`; `install-libraries`' board-push is retired (library acquisition lands files in `libraries/`, then the one `deploy` bundles them); `libraries/` is the single importable root, which resolves the `packages/README.md`-vs-`cli/library.py` contradiction as a fallout rather than a standalone patch.
- MP needs a keep-set mechanic: `lfs mkfs` has no `--exclude`, so `{boot_out.txt, boot.py, _chu_kv.msgpack}` is preserved via read-before-mkfs/restore or a scoped delete, never a blind reformat. The existing MP `_did_initial_wipe`/`mkfs` workaround for additive `fs cp` is re-derived under the real keep set rather than kept as-is.
- The flash-vs-RAM *mode* axis is explicitly out of scope — it is path-orthogonal (Decision 0028/0068/0072). This ADR governs *where bytes go and what survives*, not *how the entrypoint runs after*.
- Durability is mechanized in Phase 5 per Decision 0074: a `chumicro-checks` rule fails the build if a new device-staging path appears outside this pipeline, or if a context grows its own delete/exclude policy. The invariant is judgement-stated here and lint-enforced there.
