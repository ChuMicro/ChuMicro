---
name: audit-workspace
description: Code-quality audit at the mono-repo / ecosystem level. Looks for cross-library duplication, library-shape decisions (merge / split / delete candidates), speculative public API across the workspace, dependency-graph health, decision-ADR drift, and patterns that should be infrastructure. Use when the workspace as a whole has accumulated patterns nobody owns.
---

# Workspace audit

Audit the entire mono-repo / ecosystem.  Where `/audit-library` looks inside one package and `/audit-integration` looks at boundaries between two or three, this skill looks at the workspace as a system: which libraries should exist, where shared concerns deserve their own home, what patterns have crystallised across libraries that should be hoisted into infrastructure.

## Scope

No argument needed (or pass `--focus <area>` for a targeted pass).  Default scope is the whole mono-repo: every `libraries/<name>/`, every `workbench/<name>/`, plus shared infrastructure under `scripts/`, `support/`, and `plans/`.

This skill is the **biggest** of the three audit skills and produces the longest punch-list.  It's also the one whose findings are most likely to spawn follow-up workstreams rather than direct code edits.  Run it sparingly — once per major release cycle, or when the ecosystem feels off.

## Audit philosophy

Workspace-level cleanup operates on **library shapes**, not function shapes.  The questions are bigger:

* **Do these libraries cohere?**  Each library should have a one-sentence reason to exist.  If two libraries' sentences overlap, evaluate merging.  If a library's sentence is "miscellaneous helpers," evaluate splitting.
* **Are decisions consistent?**  When `chumicro-wifi` and `chumicro-mqtt` both face the same architectural question (e.g., how to handle reconnect backoff), they should answer it the same way — or the difference should be a documented Decision.
* **Is the dependency graph clean?**  Libraries should depend downward (utility libs at the bottom, application-shaped libs at the top), not sideways or upward.
* **Are there cross-cutting patterns nobody owns?**  When 3+ libraries each implement the same shape (e.g., a "service with check / handle methods" pattern), that pattern should live in a shared library or be documented as a contract.
* **Is there speculative scope?**  Libraries / features built for "future users" who don't exist.  Per the user-memory note `feedback_no_speculative_public_api.md` — until something ships to real users, "public API" means "us using it."

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
* **Repeated boilerplate** in scaffolders / generators / config readers.  Check `scripts/` and `workbench/workspace/scaffold` for ownership of this kind of work.

### 3. Library-shape candidates

These are the highest-impact and lowest-frequency findings.  When you see one, capture evidence carefully:

* **Merge candidates.**  Two libraries that always ship together, with overlapping concerns, where a single library would be simpler.  Evidence: do all consumers of A also consume B?  Is most of A's code at the boundary with B?
* **Split candidates.**  One library doing two unrelated jobs.  Evidence: does the library have two clusters of files that don't touch each other?  Two test-file clusters?  Two distinct sets of consumers?
* **Delete candidates.**  Speculative libraries with zero consumers in the mono-repo + workspace-template.  Evidence: grep `from chumicro_<name>` and `import chumicro_<name>` across both repos.  Zero hits → propose deletion.
* **Promote candidates.**  Helpers in `support/` or `scripts/` used by 3+ libraries that should become a real library.  Evidence: cross-library imports of internal helpers.

### 4. Decision-ADR drift

Per `plans/decisions/README.md`, structural decisions get an ADR.  Audit for:

* **Decisions made in code but not in plans/decisions/.**  Patterns that 3+ libraries follow without a corresponding ADR.  Either the pattern's a convention worth documenting, or it's accidental and should be reconsidered.
* **ADRs that are stale.**  Decisions that describe behaviour the code no longer implements (the ADR was superseded but never updated).  Per AGENTS.md: "Edit ADR bodies in place when the decision changes."
* **Conflicting ADRs.**  Decision N says X, Decision N+1 says Y, but both are listed as `accepted` and N hasn't been edited to point at N+1.

### 5. Workspace-tooling concerns

* **`scripts/run.py` commands** that are partially implemented or never used.
* **CI workflows** that test things the codebase no longer has, or skip things they should test.
* **Plan files in `plans/`** that describe work long-since shipped or abandoned.  AGENTS.md memory note: "Don't leave docs, templates, CI, and plans stale."  Audit `plans/next-up.md`, `plans/now.md`, `plans/workstreams/` for closed items still listed as open.

### 6. Cross-cutting performance / efficiency

* **Build times.**  `python scripts/run.py preflight` should run in a sensible budget (~30 s or less for the full sweep on this hardware).  Anything materially slower deserves investigation.
* **Test parallelism.**  Per AGENTS.md, tests should run via `python scripts/run.py test`.  Are slow tests using `--package-workers` correctly?
* **Bundle size.**  For libraries that ship to PyPI / circup / mip, audit the `.mpy` size where applicable.  Per Decision [0015](../../../plans/decisions/0015-board-architecture-support.md) the minimum supported tier is 256 KB MCU RAM + 4 MB flash.  Boards at the floor care about every kilobyte.

### 7. chumicro workspace-policy compliance

These cross-library invariants only show up at workspace scope.

* **Three-runtime trinity** (Decision [0049](../../../plans/decisions/0049-three-runtime-trinity.md)) — every device library should ship CP + MP + CPython adapters / fakes.  Audit:
  * Does every `libraries/<name>/src/chumicro_<name>/` have `_adapters/` for the runtimes it claims to support?
  * Does every device library have a `testing.py` fake at CPython tier (marked `__chumicro_runtimes__ = ("cpython",)`)?
  * Does the library's `pyproject.toml` `[tool.chumicro].platforms` declaration match what's actually shipped?
  * Are there libraries that target only one runtime by accident — runtime-specific code without a CPython fake, blocking host-side testing?

* **Workbench-vs-library boundary** (Decisions [0032](../../../plans/decisions/0032-workbench-folder-promotion.md), [0052](../../../plans/decisions/0052-workbench-no-library-imports.md)) — `workbench/*/src/` packages must NOT `import chumicro_<libname>` from `libraries/`.  Strict.  Templates / on-device payloads embedded as bytes are fine; live imports are not.  Run `grep -rn "^import chumicro_\|^from chumicro_" workbench/*/src/` and verify each hit imports another *workbench* package, not a library.

* **Recovery layer** (Decision [0053](../../../plans/decisions/0053-recovery-layer-philosophy.md)) — every workbench tool that touches hardware must have a `<package>.recovery` module classifying failures into a closed-set enum + recovery plans.  Generic `raise Exception` in workbench code is a UX defect.  Concrete instances: Decisions [0033](../../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md), [0039](../../../plans/decisions/0039-firmware-version-floor.md).  Audit each `workbench/<name>/` for a `recovery.py`; flag missing.

* **No mono-repo references in publishable `src/` trees** (`CHU006`) — `libraries/*/src/`, `workbench/*/src/`, and `support/*/src/` ship to PyPI / bundle consumers who don't have the mono-repo checked out.  No `Decision NNNN`, no `plans/...md` paths, no `scripts/run.py` mentions, no "chumicro mono-repo" framing.  Inline a one-line summary instead.  Run `grep -rn "Decision \|plans/" libraries/*/src/ workbench/*/src/` to surface the headline cases.  For a deeper pass — bare `run.py` mentions (no `scripts/` prefix), README leaks (CHU006 only scans `src/`), reverse-direction template→mono-repo coupling, and emitted-output leaks from generators — run `/audit-publishable-isolation` separately.  See [`audit-publishable-isolation`](../audit-publishable-isolation/SKILL.md) for the seven-pattern decomposition (P1–P7).

* **No speculative public API across the workspace** — apply the audit-library lens at workspace scope: every export in every library's `__init__.py` `__all__` should have at least one consumer in:
  * The mono-repo (other libraries, workbench, scripts, tests).
  * The workspace-template repo (`/Users/chuxor/circuitpython/ChuMicro-Workspace-Template/`).
  Zero callers in both → delete candidate.  Per the user-memory note `feedback_no_speculative_public_api.md`.

* **Decision-ADR drift** — per `plans/decisions/README.md` and AGENTS.md:
  * Every `accepted` ADR should describe the *current* state.  Audit for ADRs whose body describes behaviour the code no longer implements.
  * No `# Update (YYYY-MM-DD)` sections, no `> **Note:** Amended by...` blockquotes, no `Status: revised` (status is exactly four values: `proposed` / `accepted` / `superseded` / `deferred`).
  * When Decision N+1 supersedes part of Decision N, Decision N should be edited in place to reflect the new rule + cross-link N+1 inline.

* **Stale plan files.**  AGENTS.md memory: "Don't leave docs, templates, CI, and plans stale."  Audit:
  * `plans/next-up.md` `## Now` — items shipped should be in `## Done` with the commit reference.
  * `plans/now.md` — should reflect the current in-flight workstream, not stale ones.
  * `plans/workstreams/*.md` — closed workstreams should have `Status: closed` and a closing commit; open ones should still match active work.

* **Coverage gate consistency** (Decision [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md)) — agents pass `--coverage-threshold 94`.  If any library is materially below 94% AND has unjustified `# pragma: no cover` exclusions, flag for cleanup.

* **Four-board canonical matrix.**  Hardware-touching changes verify against `devices.yml` defaults: Pi Pico W CP, Pi Pico W MP, Lolin S2 CP, Lolin S2 MP.  When the workspace audit surfaces a workstream that needs hardware verification, propose using this matrix unless there's a specific reason to subset.

* **`requires_flash` flagging** (Decision [0047](../../../plans/decisions/0047-deploy-mode-flash-default.md)) — libraries that OOM in CP RAM-mode on minimum-tier boards should set `[tool.chumicro].requires_flash = true` in pyproject.  Audit which libraries have it; flag any large device libraries that don't but probably should.

### Calibrating workstream scope

When proposing a workstream candidate (merge / split / promote / cross-cutting refactor), calibrate its scope against analogous past work in this repo's history.  Use `git log --stat --since="6 months ago"` filtered to files in the relevant trees, or scan `plans/workstreams/archive/` for closed workstream summaries.  Knowing what a similarly-sized refactor cost last time ("ripped out 750 lines + dropped one feature" vs. "nine-step sequence with design lock-down") sharpens the proposal's size estimate beyond gut feel.

## Process

1. **Read `plans/next-up.md` (including its `## Done (recent)` log) and skim `plans/workstreams/`** first.  The audit's purpose is to find work that *isn't* already tracked; knowing what's tracked saves you from re-finding it.
2. **Walk every library's README + `pyproject.toml`.**  Don't read the source yet — at workspace scope, the source is too much information.  README + pyproject is the contract.
3. **Build the dependency graph.**  Either via `support/docs/dependency-graph.svg` (if up-to-date) or by grep through `pyproject.toml` files + `import` statements.  Look for cycles, sideways deps, libraries with too many or too few dependencies.
4. **Run the audit dimensions** against the library inventory + dep graph.  Most findings will fall under "library shape" or "cross-library pattern."
5. **For each finding, capture evidence.**  Workspace-level findings are easy to dismiss without evidence ("seems duplicated").  Capture: which files, which symbols, which call sites.  The evidence is what makes a proposal actionable.
6. **Score by confidence + scope:**
   * **High + small scope** — dead code, stale plans, broken decision ADRs.  Safe to fix in the audit pass.
   * **Medium + small scope** — pattern-promotion candidates that don't break public API.  Sign-off then execute.
   * **Any confidence + large scope** — merge / split / delete / promote candidates, infrastructure proposals.  These are **workstream proposals**, not edits.  Add to `plans/next-up.md` as a new entry; don't execute.
7. **Present the punch-list to the user.**  Heavily group by scope (small fixes first, big proposals last).
8. **Execute small-scope items.**  Each commits separately if they're unrelated.  After each batch, run `python scripts/run.py preflight --coverage-threshold 94` to confirm the full sweep still passes.  Read the `git-commit` skill before each commit.

   For **proposal items** (merge / split / delete / promote candidates), don't execute — add an entry to `plans/next-up.md` with:
   * The proposal headline.
   * The evidence (consumer counts, code-at-boundary ratios, zero-caller greps).
   * An estimated workstream size (small / medium / large).
   * A pointer to the audit run that surfaced it.

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

  merge      <lib_a> + <lib_b> — evidence: <count> consumers overlap, <ratio> of <lib_a>
             is at the boundary.  Estimated workstream: <small / medium / large>.

  promote    <pattern> appears in libraries/{wifi,mqtt,requests}/.  Promote to <where>.
             Estimated workstream: <small / medium / large>.

  split      <lib> handles <X> and <Y> independently — separate consumer sets.
             Estimated workstream: <small / medium / large>.

  delete     <lib> has zero consumers in mono-repo + workspace-template.
             Estimated workstream: small.

DECISION DRIFT:

  stale      Decision NNNN — <description> superseded by Decision MMMM but not edited.
  missing    Pattern <X> exists in 3+ libraries; no ADR.

ESCALATE:

  (Items that warrant their own design pass before any execution.)
```

The goal: a workspace where each library has a clear reason to exist, the dependency graph reads cleanly, decisions match code, and patterns that have earned their keep are documented or hoisted.

## Sequencing recommendation

Run audits in this order across a release cycle:

1. **`/audit-workspace`** first — produces the inventory + the workstream candidates.
2. **`/audit-integration`** on each pair flagged by step 1 — confirms or refutes the boundary findings.
3. **`/audit-library`** on each library individually — internal cleanup that's blocked or aided by the workspace decisions in step 1.

You'll often run them in the reverse order in practice (small fixes first), but the *thinking* benefits from the bigger-scope-first sequence.
