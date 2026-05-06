---
name: audit-library
description: Code-quality audit on a single library. Looks for duplication, abstraction honesty, method shape, dead code, YAGNI, top-to-bottom readability. Produces a punch-list, then executes high-confidence cleanups with user sign-off. Use when a library has accumulated implementation debt without a recent design pass.
---

# Library audit

Audit one library (`libraries/<name>/` or `workbench/<name>/`) for cleanup opportunities.  Output a prioritised punch-list, then execute the high-confidence ones with the user's go-ahead.

## Scope

A "library" is one publishable package — one `pyproject.toml` + `src/<name>/` + `tests/`.  This skill stays inside that boundary; cross-library concerns escalate to `/audit-integration`, ecosystem concerns to `/audit-workspace`.

Argument: the library name (matches the folder under `libraries/` or `workbench/`).  Example: `/audit-library wifi`, `/audit-library deploy`, `/audit-library workspace`.

## Audit philosophy

The lens is **"does the code say what it does?"**  Most cleanup opportunities fall into one of these patterns:

* **Honesty** — the implementation works but the call site, type, or name doesn't reflect what's happening.
* **Method shape** — work units fragmented across a chain of calls, or stuffed into one too-long method.
* **Wiring** — dead code, over-wiring, speculative public API.
* **Duplication** — same logic repeated where one helper would do.
* **Top-to-bottom readability** — scrolling the file should reveal the logic, not jump-around chase it.

Cleanup serves the **next reader**.  If the existing shape is already clear, leave it.  Don't golf.  Don't reshape because of taste alone — flag taste calls separately.

## Audit dimensions

Run through each.  Note findings as a punch-list with `file:line` + one-line description + dimension tag.

### 1. Honesty

Look for cases where the code works but the call site, type, or name doesn't match what's actually happening.

* **Class name lies about behaviour.**  Example seen in this repo: `InteractiveDeployer(max_attempts=1, prompt=lambda)` was configured to *not* be interactive but the type still said "Interactive."  Fix: rename / split the class so the name matches the configuration.
* **Function mutates inputs the caller treats as read-only.**  argparse `Namespace` mutation, dict mutation through side-effects.  Fix: return resolved values; let the caller assign.
* **Return type uses string sentinels instead of an enum / dataclass.**  Fragile, no type-check support.  Fix: small `dataclass` or `StrEnum`.
* **Docstring claims behaviour the code doesn't implement.**  E.g. "format-agnostic" when a regex is YAML-shaped.  Fix: correct the docstring (cheaper than retrofitting behaviour).
* **Two-step state machines for one conceptual operation.**  Function A finds a thing, then function B post-processes the result by re-checking what A already could have known.  Collapse into one step.

### 2. Duplication

* **Same logic repeated across files.**  ~5+ lines of structurally identical code → private helper.
* **Different functions converging on the same shape.**  Often signals a missing abstraction; compose, don't copy.
* **Constants defined in multiple places.**  Magic strings, magic numbers — define once.
* **Parallel test fixtures across files** (when this library has many test files).  Promote to a `conftest.py` or `tests/_fixtures.py` only when more than two consumers exist; otherwise YAGNI.

### 3. Method shape

* **Fragmented work units.**  If `_step1()` only ever calls `_step2()` which only ever calls `_step3()`, and each step is 5 lines, prefer a single 15-line method that scrolls top-to-bottom.  The user's framing: "instead of going all over the place."
* **Single-use private helpers with 1‑3 lines.**  If only one caller exists, inline it.  Helpers earn their existence via reuse or via a clear conceptual break.
* **Long methods (>50 lines) that mix abstractions.**  Split by *responsibility*, not by line count.  A method that reads a file, validates it, transforms it, and writes the result is doing four things and should split.
* **Nested conditionals 3+ deep.**  Extract a guard clause or split the function.

### 4. Wiring

* **Dead code.**  Functions / classes / constants with zero callers (in this library, sibling libraries, workbench, examples, tests).  Delete.
* **Over-wiring.**  Simple operations behind 3+ indirections.  E.g. `cli.py` → `dispatcher.py` → `handler.py` → `core.py` for a 5-line operation.  Flatten.
* **Speculative public API.**  Per `feedback_no_speculative_public_api.md` in user memory — exported symbols with zero callers in the mono-repo + workspace-template repo should be deleted, not preserved as "documented public API for hypothetical external users."  Until something ships to real users, "public API" means "us using it."

### 5. Performance / efficiency

(Library code only — workbench / scripts have different rules per AGENTS.md.)

* **Allocations in hot paths.**  String building inside `runner.tick()` loops, dict construction per iteration, object creation in tight loops.  Pre-allocate; cache attributes; use `memoryview` to avoid copies.
* **Redundant filesystem / network calls.**  Multiple `stat()` calls on the same path; multiple opens of the same file.  Cache or refactor to one read.
* **Unused imports + unused parameters.**  Cheap to spot, cheap to remove.
* **Eager work in `__init__` that the caller may never need.**  Defer to first use when reasonable.

### 6. Top-to-bottom readability

The user's framing: "following the file should allow me to understand the logic the more i scroll down instead of going all over the place."

* **Convention per file.**  Either public-functions-first or helpers-first; pick one and stick to it within the file.
* **Adjacent related concepts.**  Helper functions for the same feature should sit together, not be scattered.
* **Early-exit guards first.**  `if not condition: raise / return` should land at the top of the function, not be buried.
* **Docstrings explain *why*, not just *what*.**  The signature already says what.  The body already says how.  The docstring should say why this exists or what subtle invariant it maintains.

## Process

1. **Read the library top-to-bottom first.**  One full pass through every `.py` under `src/` to build mental model.  Touch the tests too.  No edits yet.
2. **Read the library's `pyproject.toml`** for declared dependencies + any `[tool.chumicro.config]` manifest.  Helps spot mismatches between what's declared and what's used.
3. **Run the audit dimensions.**  Note findings in a list.
4. **Score each finding by confidence:**
   * **High** — dead code, obvious duplication, lying class names, broken docstring claims.  Safe to fix without further discussion.
   * **Medium** — method-shape changes, naming-style decisions, "this works but I'd structure it differently."  Benefit from a second opinion.
   * **Low** — cross-library coupling questions.  Escalate to `/audit-integration`, don't fix here.
5. **Present the punch-list to the user.**  Group by dimension.  Flag taste calls separately.
6. **Execute high-confidence items as one cohesive commit.**  Run `python scripts/run.py test --libraries <name>` after each batch of changes.  Hardware-verify if the change touches a deploy / probe / transport path.
7. **Hand off remaining medium / low items to the user.**  Don't make taste calls without sign-off.

## Anti-patterns

* **Don't golf.**  Saving 3 lines at the cost of clarity is a regression.
* **Don't reshape what works just because.**  Cleanup serves the reader; if the existing shape is clear, leave it.
* **Don't auto-fix taste-call findings.**  Method-shape and naming-style decisions are owned by the human reviewer.
* **Don't break public API in an audit pass.**  Library symbols imported by sibling libraries / workbench / examples are out-of-scope for renames; flag separately.
* **Don't move trivial helpers into a `utils.py`.**  Utility-bucket modules are death by a thousand cuts.

## After the audit

If the audit produced commits:

* Bump the library's `VERSION` file per AGENTS.md (patch unless structural).
* Run the `task-checkpoint` skill — `python scripts/run.py preflight --coverage-threshold 94` to confirm the broader sweep still passes.
* Update any docstrings the user-facing API rewrites invalidated.
* Don't ship auto-fixes the user hasn't seen — taste-call findings stay in the punch-list output until the user signs off.

## Output format

When presenting the punch-list, structure it like:

```
Library audit: chumicro_<name>
================================

HIGH-CONFIDENCE (safe to fix):

  honesty   src/<name>/<file>.py:NN — <one-line description>
  duplicate src/<name>/<file>.py:NN — <one-line description>
  dead-code src/<name>/<file>.py:NN — <one-line description>
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  shape     src/<name>/<file>.py:NN — <one-line description>
  ...

TASTE-CALL (your call):

  flow      src/<name>/<file>.py:NN — <one-line description>
  ...

ESCALATE:

  cross-lib src/<name>/<file>.py:NN — interaction with chumicro_<other>
            (route to /audit-integration <name>,<other>)
```

The goal: fewer surprising lines, tests still pass, call sites read more honestly than before.
