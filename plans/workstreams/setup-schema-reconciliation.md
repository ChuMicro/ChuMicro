# Setup: schema reconciliation for user-edited config files

Status: `planned` (not yet executed)
Filed: 2026-05-04
Related: [Decision 0057](../decisions/0057-two-file-config.md) — the two-file workspace config leaves `workspace.yml` and `projects/<name>/config.toml` as user-edited files materialized from a starter; this workstream covers what happens when the starter gains new schema entries after the user has already materialized + edited.

## Goal

When a user has materialized a `workspace.yml` (or per-project `config.toml`) from the canonical starter and edited it, and the canonical starter later gains a new schema entry (e.g. a new `[quality.observability]` block, a new `wifi.power_save` field, etc.), `python run.py setup` should surface the new entries in the user's file **without clobbering their edits**.

Today: `materialize_workbench_starters` and `materialize_templates` only write missing files; once materialized, the file is frozen at materialization-time content.  `update` refreshes tool-owned files by wholesale replacement but never touches user-owned files.  So a workspace that materialized last month doesn't see this month's schema additions; the user has to know to re-read the upstream starter and copy in the new bits manually.

Both user-editable files (`workspace.yml` and per-project `config.toml`) are now starter-materialized (Decision 0057).  The schema-bearing `workspace.yml` is the file that needs schema updates to flow without clobbering user edits.

## Design space

Five strategies in increasing complexity:

### A. **Status quo + manual diff** (no work)

`setup` does what it does today.  When upstream ships a new starter, contributors who care can `git diff` against the canonical content and paste in by hand.  Acceptable if schema additions are rare — but in practice every workspace-feature workstream adds something to the schema.  Cost: low until it isn't.

### B. **Show the diff on setup** (low complexity)

`setup` reads the user's materialized file, reads the canonical starter, and prints a diff with no auto-application: *"upstream starter has 3 fields you don't have: `quality.observability.metrics_endpoint`, `wifi.power_save`, `mqtt.broker.tls`.  Copy from `<starter-path>` if you want them."*

Pros: zero magic, zero risk of clobbering user edits, future-self-readable transcript every time setup runs.
Cons: still manual; user has to copy + paste; easy to forget.

### C. **Append missing top-level sections, commented out** (medium complexity)

Parse YAML structurally.  For each top-level section in the canonical starter that doesn't exist in the user's file, append the starter's commented version of that section to the user's file.  Don't touch any section that already exists in the user's file (even if its values differ from the starter).

Pros: covers the common case (new section added upstream → appears as commented examples in user's file ready to uncomment + edit).  No three-way merge required.  Comment preservation only relies on YAML round-trip via ruamel (already a workspace dep).
Cons: doesn't handle *additions to existing sections* (e.g. starter adds `wifi.power_save` to an existing `[wifi]` block).  Doesn't handle removals or renames.  Doesn't handle the case where the user's edit *is* the new section name with different content.

### D. **Field-level reconciliation within sections** (higher complexity)

Extend C: walk the YAML tree.  For any commented-out field in the starter that doesn't exist in the user's file (commented or live), append it as a commented field in the same section.  Live values from the starter that don't exist in the user's file: append commented (so the user can uncomment if they want the new default).

Pros: covers the "new field in existing section" case that C misses.
Cons: comment-preservation across editing rounds gets fragile (ruamel's round-trip is good but not perfect for free-form comment placement).  More edge cases (what if the user *deleted* a section that the starter still ships?  Re-add it commented or respect the deletion?).

### E. **Three-way merge with snapshot** (highest complexity)

On every materialization, snapshot the starter content alongside the materialized file (e.g. `.chumicro/starter-snapshot/workspace.yml`).  On subsequent setup, do a three-way merge: snapshot ↔ user's current file ↔ new starter.  Apply non-conflicting upstream additions automatically; print conflicts for manual resolution.

Pros: most general.  Handles everything C and D do plus removals, renames, value updates.  Mirrors `git merge` semantics that contributors already know.
Cons: significant implementation effort (or pulling in a YAML 3-way-merge dep).  Snapshot directory adds clutter.  Conflict resolution UX needs design.  Probably overkill for the "occasional schema addition" cadence we actually have.

## Recommended starting point

**Strategy B for now (show the diff), with C as the natural follow-up.**  Reasons:

- B is ~50 lines and ships a useful behaviour change immediately.
- B's "user manually copies from the starter" friction is the same friction users already have today (since they don't see the diff at all today, just nothing happens).  It's a strict improvement.
- B's transcript tells us *which schema additions actually happen* in practice — gives data on whether C / D / E earns its keep.
- C is a natural step up once B has surfaced enough "I keep manually copying section X" pain to justify the YAML-walk machinery.
- E is overkill until we see real demand.  YAGNI.

Defer D and E until B's signal says they're worth it.

## What changes when this lands

### Workspace package

- New module: `chumicro_workspace.starter_diff` (probably).  Public `compute_missing_top_level_sections(user_path: Path, starter_text: str) -> list[str]` — returns top-level keys present in starter but missing in user's materialized file.  Pure function; pairs with the materialize_* family.
- `materialize_workbench_starters` — when target exists (the case where today it skips silently), call `compute_missing_top_level_sections` and print the result.  Don't touch the file.  Same pattern for `materialize_templates`.
- Optional: a `--apply-schema-additions` flag on `setup` that does the C-strategy append.  Off by default; opt-in until comment-preservation behaviour earns trust.

### Tests

- `test_starter_diff.py` — covers the diff function directly.
- `test_template_apply.py` — assert the diff prints when materialize encounters an existing-but-stale file.

### Docs

- `workbench/workspace/docs/guide.md` — note the new setup output ("upstream starter has new sections X, Y; copy from `<path>` to add them").
- `docs/contributing/development-*` — same one-line addition to the setup walkthrough.
- A small ADR describing the design choice (B with C as future follow-up; rejecting E as overkill).

## Open questions

1. **What format does the diff print in?**  YAML snippet of just the missing sections?  Diff-style with `+` markers?  A path list (`mqtt.broker.tls`)?  Lean: YAML snippet — the user can copy-paste it directly, which is the action they'd take anyway.
2. **Where is the canonical starter located when this runs?**  `chumicro_workspace.read_workspace_yml_starter()` returns the bytes; the diff function needs the text, not a path.  Easy.  But `materialize_templates` walks `_workspace_template/` for non-workbench-owned starters; those need a path.  Both cases need a `compute_missing` shape that takes content + user file.
3. **Per-project `config.toml` reconciliation.**  Does this strategy apply equally to `projects/<name>/config.toml` files when the upstream `projects/_template/config.toml` schema changes?  Probably yes, but the trigger isn't `setup` — it's `python run.py new` (which already copies the template into a new project) plus an opt-in "refresh schema in existing projects" command.  Out of scope for the initial B implementation; flag it as a follow-up.
4. **Comment preservation in C.**  ruamel.yaml round-tripping preserves comments well but not perfectly.  Test for the common patterns (section-level comments, end-of-line comments, blank-line spacing) before claiming the strategy is safe.  Probably need a fixture matrix.
5. **What about TOML?**  The two-file design has the user's project-side file as TOML, not YAML.  TOML doesn't have a comment-preserving round-trip story as good as ruamel for YAML.  C / D might require either a custom parser or a different strategy for TOML files.  Flag for the C-strategy implementation.

## Execution checklist (when picked up)

1. Implement strategy B — `compute_missing_top_level_sections` + wiring into `materialize_*`.
2. Add tests.
3. Update docs.
4. Ship.
5. Use for ~a release cycle to gather signal on whether C earns its keep.
6. If C is warranted, design the comment-preservation strategy + ship.

## Why this is a separate workstream from two-file-config-simplification

Both workstreams touch the materialize_* functions in `chumicro_workspace.template_apply`, but they're orthogonal:

- Two-file simplification = "how many files, which ones tracked?"  Affects the *layout*.
- Schema reconciliation = "what does setup do when a starter file already exists?"  Affects the *behaviour*.

Doing them together would interleave two design conversations.  Sequencing them — two-file first, then schema reconciliation — keeps each scope clean.  Reconciliation can also wait longer if signal is weak; conflating it with the two-file work would force shipping it on the two-file timeline.
