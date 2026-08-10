---
name: audit-workspace
description: Code-quality audit at the mono-repo / ecosystem level. Looks for cross-library duplication, library-shape candidates (merge / split / delete / promote), speculative public API, dependency-graph health, and decision-ADR drift. Use when the workspace has accumulated patterns nobody owns.
---

# Workspace audit

Audit the entire mono-repo / ecosystem.  Where `/audit-library` looks inside one package and `/audit-integration` looks at boundaries between two or three, this skill looks at the workspace as a system: which libraries should exist, where shared concerns deserve their own home, what patterns have crystallised across libraries that should be hoisted into infrastructure.

## Scope

No argument needed (or pass `--focus <area>` for a targeted pass).  Default scope is the whole mono-repo: every `libraries/<name>/`, every `workbench/<name>/`, plus shared infrastructure under `scripts/`, `support/`, and `plans/`.

This skill is the **biggest** of the three audit skills and produces the longest punch-list.  It's also the one whose findings are most likely to spawn follow-up workstreams rather than direct code edits.

## How this audit fits the wider sequence

For full-sweep entry mode (release-cycle pass — see Process → Entry modes), `/audit-workspace` runs **first** in the audit family.  It produces the inventory + workstream candidates that the narrower audits depend on:

1. **`/audit-workspace`** (this skill) — produces the inventory + workstream candidates.
2. **`/audit-integration`** on each pair flagged by step 1 — confirms or refutes the boundary findings.
3. **`/audit-library`** on each library individually — internal cleanup that's blocked or aided by the workspace decisions in step 1.
4. **`/audit-embedded`** on each device library after step 3.  Per audit-embedded's body, the library pass shrinks surface first (dead code, single-use helpers, cargo-cult methods), which makes the embedded pass cleaner.  Skip for `workbench/*` packages — they're host-only.

In practice you'll often run them in the reverse order (small fixes first), but the *thinking* benefits from the bigger-scope-first sequence.

For routed-finding entry mode (a sibling escalates a single finding here), this sequencing doesn't apply — produce one workstream proposal and return.

## Audit philosophy

Workspace-level cleanup operates on **library shapes**, not function shapes.  The questions are bigger:

* **Do these libraries cohere?**  Each library should have a one-sentence reason to exist.  If two libraries' sentences overlap, evaluate merging.  If a library's sentence is "miscellaneous helpers," evaluate splitting.
* **Are decisions consistent?**  When `chumicro-wifi` and `chumicro-mqtt` both face the same architectural question (e.g., how to handle reconnect backoff), they should answer it the same way — or the difference should be a documented Decision.
* **Is the dependency graph clean?**  Libraries should depend downward (utility libs at the bottom, application-shaped libs at the top), not sideways or upward.
* **Are there cross-cutting patterns nobody owns?**  When 3+ libraries each implement the same shape (e.g., a "service with check / handle methods" pattern), that pattern should live in a shared library or be documented as a contract.
* **Is there speculative scope?**  Libraries / features built for "future users" who don't exist.  Per AGENTS.md → Workflow: until something ships to real users, "public API" means "us using it" — symbols with zero callers across this repo and the [workspace-template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) repo are dead code.

The output of this audit is often a set of **proposals** (merge candidates, infrastructure proposals, decision ADRs) more than direct edits.  Each proposal should be small enough that the user can sign off on it without a separate design pass.

## Audit dimensions

### 1. Library shape inventory

For every `libraries/<name>/` and `workbench/<name>/`:

* **One-sentence purpose.**  Read the README and the `pyproject.toml` `description`.  Can you write a one-sentence answer to "why does this library exist?"  If not, the library's purpose is unclear and that's the finding.
* **Public API surface.**  Read the package `__init__.py`'s `__all__`.  How many symbols?  Are they all *used* by mono-repo + workspace-template consumers?  Per the no-speculative-API rule, unused public symbols should be flagged.
* **Internal complexity vs scope.**  A library claiming a tight scope ("low-level wifi adapter") that has 800 lines of helper code suggests scope creep.
* **Dependency declaration.**  Each library's `pyproject.toml` `dependencies = [...]` should match its actual `import` statements.  Mismatches are packaging bugs.

### 2. Cross-library pattern detection

Patterns that appear in 3+ libraries are infrastructure candidates.  Look for:

* **Repeated state-machine shapes.**  E.g., wifi, mqtt, and requests all have "connecting / connected / failed / reconnecting" state machines.  If the *pattern* is the same, consider a shared base in a small infrastructure library (or a documented contract that they all implement).
* **Repeated configuration patterns.**  Multiple libraries with `<X>Config.from_dict()`.  Already addressed by `chumicro-config` per Decision 0036; verify every library follows that decision.
* **Repeated test-fixture shapes.**  If every networking library's `functional_tests/conftest.py` is structurally identical except for which library is being tested, the conftest is infrastructure.
* **Repeated boilerplate** in scaffolders / generators / config readers.  Check `scripts/new_library_scaffold.py` and adjacent generator scripts under `scripts/` for ownership of this kind of work.
* **Scaffold-emitted files that drift after copy.**  `scripts/new_library_scaffold.py` (and similar generators) emit files into each new library at creation time.  Once copied, the destinations drift independently — the scaffold loses its "canonical source" claim the moment two leaves disagree.  Detect with `find libraries -path '*/<subpath>' -exec md5 -q {} \;` (or equivalent): bytes-identical across N libraries + drifted in M others is the scaffold-drift fingerprint.  Concrete example surfaced by `/audit-comments` routing: `libraries/{sockets,http_server,websockets,ntp}/examples/helpers.py` are byte-identical; `mqtt` and `requests` already drifted.  The fix is a workspace-level decision — see "Decision space for cross-library consolidation findings" below.

### 3. Library-shape candidates

These are the highest-impact and lowest-frequency findings.  When you see one, capture evidence carefully:

* **Merge candidates.**  Two libraries that always ship together, with overlapping concerns, where a single library would be simpler.  Evidence: do all consumers of A also consume B?  Is most of A's code at the boundary with B?
* **Split candidates.**  One library doing two unrelated jobs.  Evidence: does the library have two clusters of files that don't touch each other?  Two test-file clusters?  Two distinct sets of consumers?
* **Delete candidates.**  Speculative libraries with zero consumers in the mono-repo + workspace-template.  Evidence: grep `from chumicro_<name>` and `import chumicro_<name>` across both repos.  Zero hits → propose deletion.
* **Promote candidates.**  Helpers in `support/` or `scripts/` used by 3+ libraries that should become a real library.  Evidence: cross-library imports of internal helpers.

### Decision space for cross-library consolidation findings

When a routed finding (cross-library duplication, scaffold-emitted drift, promote candidate, sibling-cohesion divergence) lands here, the proposal must lay out the user's actual choices.  A "promote to `<where>`" hand-wave is underspecified — the four real options are:

* **(a) shared package** — extract the pattern into a `support/<name>/` package (or a new `libraries/<name>/` if it earns library status); each callsite imports rather than copies.  Best when the pattern has stable internal shape and 3+ consumers.
* **(b) scaffold + sync** — keep a copy per library, but make the scaffold the source of truth and add a drift check (preflight lint or pre-commit hook) that fails when the leaves diverge.  Best when each leaf legitimately needs a local copy (examples, READMEs that ship with the package) and a shared import would couple too hard.
* **(c) documented contract** — let each library implement independently, but document the contract (an ADR or a `plans/patterns.md` entry) that all implementations must satisfy.  Best when the *shape* matters more than the implementation (state-machine names, return types, error taxonomies).
* **(d) accept the drift** — the duplication is small, the consequences of divergence are minimal, the cost of consolidation exceeds the cost of carrying N copies.  Record the rationale so future audits don't re-litigate the question.

Each option has a different **executing pathway** that the proposal must name (see Output format — PROPOSALS template).  Without the pathway, the workstream entry in `plans/next-up.md` is incomplete and the next auditor / agent / user has to re-analyse from scratch.

### 4. Decision-ADR drift

Per `plans/decisions/README.md`, structural decisions get an ADR.  Audit for:

* **Decisions made in code but not in plans/decisions/.**  Patterns that 3+ libraries follow without a corresponding ADR.  Either the pattern's a convention worth documenting, or it's accidental and should be reconsidered.
* **ADRs that are stale.**  Decisions that describe behavior the code no longer implements (the ADR was superseded but never updated).  Per AGENTS.md: "Edit ADR bodies in place when the decision changes."
* **Conflicting ADRs.**  Decision N says X, Decision N+1 says Y, but both are listed as `accepted` and N hasn't been edited to point at N+1.

### 5. Workspace-tooling concerns

* **`scripts/run.py` commands** that are partially implemented or never used.
* **CI workflows** that test things the codebase no longer has, or skip things they should test.
* **Plan files in `plans/`** that describe work long-since shipped or abandoned.  AGENTS.md memory note: "Don't leave docs, templates, CI, and plans stale."  Audit `plans/next-up.md`, `plans/now.md`, `plans/workstreams/` for closed items still listed as open.

### 6. Cross-cutting performance / efficiency

* **Build times.**  `python scripts/run.py preflight` should run in a sensible budget (~30 s or less for the full sweep on this hardware).  Anything materially slower deserves investigation.
* **Test parallelism.**  Per AGENTS.md, tests should run via `python scripts/run.py test`.  Are slow tests using `--package-workers` correctly?
* **Bundle size.**  For libraries that ship to PyPI / circup / mip, audit the `.mpy` size where applicable.  Per Decision [0015](../../../plans/decisions/0015-board-architecture-support.md) the minimum supported tier is 256 KB MCU RAM + 2 MB physical / ~800 KB usable flash.  Boards at the floor care about every kilobyte.

### 7. chumicro workspace-policy compliance

These cross-library invariants only show up at workspace scope.

* **Three-runtime trinity** (Decision [0049](../../../plans/decisions/0049-three-runtime-trinity.md)) — every device library should ship CP + MP + CPython adapters / fakes.  Audit:
  * Does every `libraries/<name>/src/chumicro_<name>/` have `_adapters/` for the runtimes it claims to support?
  * Does every device library have a `testing.py` fake at CPython tier (marked `__chumicro_runtimes__ = ("cpython",)`)?
  * Does the library's `pyproject.toml` `[tool.chumicro].platforms` declaration match what's actually shipped?
  * Are there libraries that target only one runtime by accident — runtime-specific code without a CPython fake, blocking host-side testing?

* **Workbench-vs-library boundary** — verify [Decision 0032](../../../plans/decisions/0032-workbench-host-tools.md) + [Decision 0052](../../../plans/decisions/0052-workbench-no-library-imports.md) hold across the tree.  Run `grep -rn "^import chumicro_\|^from chumicro_" workbench/*/src/` and verify each hit imports another *workbench* package, not a library.

* **Recovery layer** (Decision [0053](../../../plans/decisions/0053-recovery-layer-philosophy.md)) — every workbench tool that touches hardware must have a `<package>.recovery` module classifying failures into a closed-set enum + recovery plans.  Generic `raise Exception` in workbench code is a UX defect.  Concrete instances: Decisions [0033](../../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md), [0039](../../../plans/decisions/0039-firmware-version-floor.md).  Audit each `workbench/<name>/` for a `recovery.py`; flag missing.

* **No mono-repo references in publishable `src/` trees** — `CHU006` enforces the deterministic subset across `libraries/*/src/`, `workbench/*/src/`, and `support/test_harness/src/`.  At workspace-audit scope, run `grep -rn "Decision \|plans/" libraries/*/src/ workbench/*/src/` to surface anything that's slipped past the lint at the reading level.  For the deeper pass (READMEs, reverse-direction template→mono-repo coupling, emitted-output leaks from generators, the eight-pattern decomposition P1–P8) route to [`audit-publishable-isolation`](../audit-publishable-isolation/SKILL.md) rather than expanding scope here.

* **No speculative public API across the workspace** — apply the audit-library lens at workspace scope: every export in every library's `__init__.py` `__all__` should have at least one consumer in:
  * The mono-repo (other libraries, workbench, scripts, tests).
  * The workspace-template repo (sibling checkout, conventionally at `$WORKSPACE_TEMPLATE_ROOT`).
  Zero callers in both → delete candidate.  Per AGENTS.md → Workflow ("Public API today means us using it").

* **Decision-ADR drift** — per `plans/decisions/README.md` and AGENTS.md:
  * Every `accepted` ADR should describe the *current* state.  Audit for ADRs whose body describes behavior the code no longer implements.
  * No `# Update (YYYY-MM-DD)` sections, no `> **Note:** Amended by...` blockquotes, no `Status: revised` (status is exactly four values: `proposed` / `accepted` / `superseded` / `deferred`).
  * When Decision N+1 supersedes part of Decision N, Decision N should be edited in place to reflect the new rule + cross-link N+1 inline.

* **Stale plan files.**  AGENTS.md memory: "Don't leave docs, templates, CI, and plans stale."  Audit:
  * `plans/next-up.md` `## Now` / `## Next` — items already shipped should have their bullets removed; cross-reference recent landings via `git --no-pager log -30 --oneline`.
  * `plans/now.md` — should reflect the current in-flight workstream, not stale ones.
  * `plans/workstreams/*.md` — closed workstreams should have `Status: closed` and a closing commit; open ones should still match active work.

* **Coverage gate consistency** (Decision [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md)) — agents pass `--coverage-threshold 94`.  If any library is materially below 94% AND has unjustified `# pragma: no cover` exclusions, flag for cleanup.

* **Four-board verification matrix.**  Hardware-touching changes verify against `devices.yml` defaults: Pi Pico W CP, Pi Pico W MP, Lolin S2 CP, Lolin S2 MP.  When the workspace audit surfaces a workstream that needs hardware verification, propose using this matrix unless there's a specific reason to subset.

* **`requires_flash` flagging** (Decision [0047](../../../plans/decisions/0047-deploy-mode-flash-default.md)) — libraries that OOM in CP RAM-mode on minimum-tier boards should set `[tool.chumicro].requires_flash = true` in pyproject.  Audit which libraries have it; flag any large device libraries that don't but probably should.

### Calibrating workstream scope

When proposing a workstream candidate (merge / split / promote / cross-cutting refactor), calibrate its scope against analogous past work in this repo's history.  Use `git log --stat --since="6 months ago"` filtered to files in the relevant trees, or scan `plans/workstreams/archive/` for closed workstream summaries.  Knowing what a similarly-sized refactor cost last time ("ripped out 750 lines + dropped one feature" vs. "nine-step sequence with design lock-down") sharpens the proposal's size estimate beyond gut feel.

## Process

**Entry modes.**  Two ways to invoke this audit:

* **Full sweep** (default) — walk the whole mono-repo per the steps below.  Produces inventory + workstream candidates.  Run once per release cycle or when the ecosystem feels off.
* **Routed finding** — a sibling audit ([`audit-library`](../audit-library/SKILL.md), [`audit-comments`](../audit-comments/SKILL.md), [`audit-integration`](../audit-integration/SKILL.md), [`audit-publishable-isolation`](../audit-publishable-isolation/SKILL.md)) surfaced a workspace-scope finding and routed it here with evidence pre-loaded.  Skip the full inventory; jump to the relevant dim — cross-library duplication / scaffold drift / sibling-cohesion → dim 2 + the "Decision space" block; merge / split / delete / promote → dim 3 + the "Decision space" block; ADR drift → dim 4; cross-cutting infra → dim 7 — and produce a single workstream proposal.  Repo-wide `/audit-comments` roll-out specifically lands here per that skill's scope note: schedule per-library passes via `plans/next-up.md` rather than running the comment audit across every library in one workspace-level pass.

The full sweep follows steps 1–8 below.  Routed-finding mode skips to step 4 with the sibling's evidence as the starting point and goes straight to step 5 (capture evidence) + step 7 (present punch-list) for the single finding.

1. **Read `plans/next-up.md`, run `git --no-pager log -30 --oneline` for recent landings, and skim `plans/workstreams/`** first.  The audit's purpose is to find work that *isn't* already tracked; knowing what's tracked saves you from re-finding it.
2. **Walk every library's README + `pyproject.toml`.**  Don't read the source yet — at workspace scope, the source is too much information.  README + pyproject is the contract.
3. **Build the dependency graph.**  Either via `support/docs/dependency-graph.svg` (if up-to-date) or by grep through `pyproject.toml` files + `import` statements.  Look for cycles, sideways deps, libraries with too many or too few dependencies.
4. **Run the audit dimensions** against the library inventory + dep graph.  Most findings will fall under "library shape" or "cross-library pattern."
5. **For each finding, capture evidence.**  Workspace-level findings are easy to dismiss without evidence ("seems duplicated").  Capture: which files, which symbols, which call sites.  The evidence is what makes a proposal actionable.
6. **Score by confidence + scope:**
   * **High + small scope** — dead code, stale plans, broken decision ADRs.  Safe to fix in the audit pass.
   * **Medium + small scope** — pattern-promotion candidates that don't break public API.  Sign-off then execute.
   * **Any confidence + large scope** — merge / split / delete / promote candidates, infrastructure proposals.  These are **workstream proposals**, not edits.  Add to `plans/next-up.md` as a new entry; don't execute.
7. **Present the punch-list to the user.**  Heavily group by scope (small fixes first, big proposals last).
8. **Execute small-scope items.**  Each commits separately if they're unrelated.  Hand the end-of-batch off to the `task-checkpoint` skill (preflight, plans-doc update, commit, push).  If preflight surfaces a failure unrelated to the current edit, isolate it and flag in the punch-list rather than silently folding the fix into a workspace-audit commit — workspace-audit blast radius is large enough that unrelated fixes obscure the audit's intent.

   For **proposal items** (merge / split / delete / promote candidates), don't execute — add an entry to `plans/next-up.md` with:
   * The proposal headline.
   * The evidence (consumer counts, code-at-boundary ratios, zero-caller greps).
   * An estimated workstream size (small / medium / large).
   * A pointer to the audit run that surfaced it.

## After the audit

The audit is done when:

* Small-scope items have a commit each or an explicit user skip.
* Workstream proposals are added to `plans/next-up.md` with the proposal template (headline, evidence, estimated workstream size).
* `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.

After the after-action sweep, invoke the `task-checkpoint` skill — it owns preflight, plans-doc update, commit, and push.  Don't stop without invoking it.

If the audit surfaces a workstream too big to scope here, file an entry pointing at `plans/workstreams/<name>.md` and move on.  Out-of-scope expansion mid-audit is the leading cause of bloated workspace-audit commits.

## Anti-patterns

* **Don't propose merges / splits / deletes without evidence.**  "I think these two libraries could be merged" is a vibe; "all 14 consumers of A also consume B, and A has 380 lines of which 240 are at the boundary with B" is a proposal.
* **Don't refactor cross-cutting patterns into infrastructure during the audit.**  That's a workstream of its own — propose, don't execute.
* **Don't ship structural changes that touch 5+ libraries in one commit.**  Workspace-scoped changes need to land library-by-library so each step is rollback-able.
* **Don't propose architectural changes the user hasn't asked for.**  Workspace audit can flag that the architecture has drift; deciding what to do about it is the user's call.

## Output format

The workspace audit's output is bigger.  Structure it like:

```
Workspace audit
================

PUNCH-LIST (small fixes — safe to execute):

  dead-code  libraries/<name>/src/<file>.py — <symbol> has no consumers
  stale-doc  plans/next-up.md:NN — <item> shipped in <commit>; should be in Done
  ...

PROPOSALS (workstream candidates — for plans/next-up.md):

  Every proposal includes evidence, estimated workstream size, and an
  *executing pathway* — the skill, script, or focused agent task that
  closes the loop.  audit-workspace produces the proposal; it does not
  execute large refactors.  Without the executing pathway named, the
  workstream entry is incomplete and the next agent / user has to
  re-analyse from scratch.

  merge      <lib_a> + <lib_b> — evidence: <count> consumers overlap, <ratio> of <lib_a>
             is at the boundary.  Estimated workstream: <small / medium / large>.
             Executing pathway: focused agent task (no single skill covers cross-
             library merges); land library-by-library so each step is rollback-able.

  promote /  <pattern> appears in libraries/{wifi,mqtt,requests}/.  Decision space
  consolidate (from §"Decision space for cross-library consolidation findings"):
               (a) shared support package — extract to support/<name>/
               (b) scaffold + sync       — source of truth in scripts/new_library_scaffold.py
                                           + drift check (preflight or pre-commit)
               (c) documented contract   — each library implements; ADR documents shape
               (d) accept                — record rationale; carry the duplication
             Recommended: <option> because <one-line reason>.
             Estimated workstream: <small / medium / large>.
             Executing pathway per option:
               (a) /new-library covers libraries/<name>/; support/<name>/ is hand-rolled
                   (no skill currently scaffolds support packages) + cross-library import
                   edits as a focused agent task.
               (b) edit scripts/new_library_scaffold.py to be the source of truth +
                   add a drift check (workbench/checks/ rule or pre-commit hook).
                   No skill currently fits; focused agent task.
               (c) /new-decision to author the ADR + per-library docstring or impl
                   edits as drift surfaces in later audits.
               (d) Append the rationale to a plans/workstreams/<name>.md note or
                   the originating ADR.  Nothing to execute beyond that.

  split      <lib> handles <X> and <Y> independently — separate consumer sets.
             Estimated workstream: <small / medium / large>.
             Executing pathway: focused agent task per the split-library workstream
             pattern (extract X into its own libraries/<x>/, update consumers).

  delete     <lib> has zero consumers in mono-repo + workspace-template.
             Estimated workstream: small.
             Executing pathway: direct edit (rm -rf libraries/<lib>/, update
             libraries/README.md, run preflight).

DECISION DRIFT:

  stale      Decision NNNN — <description> superseded by Decision MMMM but not edited.
  missing    Pattern <X> exists in 3+ libraries; no ADR.

ESCALATE:

  (Items that warrant their own design pass before any execution.)
```

The goal: a workspace where each library has a clear reason to exist, the dependency graph reads cleanly, decisions match code, and patterns that have earned their keep are documented or hoisted.

