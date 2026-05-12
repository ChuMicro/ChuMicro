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
* **Stale CLI / recovery-command / status claims in docs.**  Grep `docs/guide.md`, `README.md`, and `docs/*.md` for every CLI flag, error-message text, recovery command, environment-variable name, and feature-status assertion they reference by name; confirm each still exists with the documented shape.  Field reality:  this audit found a `--drive` flag the CLI no longer exposes, a `launchctl kickstart` recovery command the source had dropped (SIP-blocked), and a "uid is reserved, empty today" claim that pre-dated the probe that now populates it.  All three were HIGH-confidence single-line edits — and all three would have rotted further without the grep.

### 2. Duplication

* **Same logic repeated across files.**  ~5+ lines of structurally identical code → private helper.
* **Different functions converging on the same shape.**  Often signals a missing abstraction; compose, don't copy.
* **N if/elif branches with the same action shape — collapse to a fixed-map dispatch.**  When N branches all do the same thing with different parameters (raise the same exception class with per-branch message text; emit the same log shape with per-branch values; return the same dataclass with per-branch fields), a module-level `_LOOKUP = {key: (param1, param2, ...)}` dict + one f-string raise/log/return beats the chain.  Watch for: identical statement shape across branches, only the literals change.  The `_OUT_OF_SUBSET` map in `chumicro_msgpack._pure` is a worked example — 7 if-branches × 4 lines each → 7-entry dict + 4-line dispatch.  Counter-cases where the chain is right: (a) branches dispatch to differently-shaped functions (e.g. `chumicro_mqtt._wire._parse_packet` calling `_parse_publish` / `_parse_connack` / `_parse_simple_ack` with different signatures); (b) the chain compares against ranges (`if byte <= 0x8f`) not single values; (c) only 2-3 branches and they're sufficiently distinct that the chain reads more honestly.
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
* **Per-byte loops where per-chunk works.**  A specific shape of the above: `for byte in chunk: state.feed(byte)` calls a method (and allocates a frame) per byte.  When the state machine can consume `min(remaining, needed)` bytes per state via slice / extend / XOR-loop on a slice, restructure to per-chunk.  Each call frame on MicroPython has measurable cost; on a 1024-byte recv buffer, per-byte processing means 1024 frames per tick.
* **Redundant filesystem / network calls.**  Multiple `stat()` calls on the same path; multiple opens of the same file.  Cache or refactor to one read.
* **Unused imports + unused parameters.**  Cheap to spot, cheap to remove.
* **Eager work in `__init__` that the caller may never need.**  Defer to first use when reasonable.

### 6. Top-to-bottom readability

The user's framing: "following the file should allow me to understand the logic the more i scroll down instead of going all over the place."

* **Convention per file.**  Either public-functions-first or helpers-first; pick one and stick to it within the file.
* **Adjacent related concepts.**  Helper functions for the same feature should sit together, not be scattered.
* **Early-exit guards first.**  `if not condition: raise / return` should land at the top of the function, not be buried.
* **Docstrings explain *why*, not just *what*.**  The signature already says what.  The body already says how.  The docstring should say why this exists or what subtle invariant it maintains.  Drop docstrings that only re-state the signature in prose.

### 7. chumicro project-policy compliance

These are non-negotiables from `AGENTS.md` and the relevant Decisions.  Most should already pass via lint / preflight, but the audit catches edge cases.

* **Runner-shape compliance** — any device library that owns time or I/O must be runner-shaped (Decisions [0014](../../../plans/decisions/0014-runner-pattern.md), [0051](../../../plans/decisions/0051-runner-shaped-as-project-policy.md)).  Grep for:
  * `time.sleep(N)` where N > 0.005 — banned in `libraries/*/src/`.
  * `select.poll(timeout=`<positive> — banned (use `timeout=0` for non-blocking poll).
  * `await` / `async def` — banned everywhere in library code.
  * Synchronous DNS calls (`socket.getaddrinfo` without yielding) — banned.
  * `check(now_ms)` / `handle(now_ms)` methods that *re-call* `ticks_ms()` instead of using the supplied `now_ms`.  Every service in a tick must see the same `now_ms` for deterministic intra-tick ordering, fairness, and composed deadlines — re-fetching mid-tick produces clock-domain misalignment that masquerades as protocol bugs.
* **Constructor injection** (Decision [0010](../../../plans/decisions/0010-library-testability.md)) — time / I/O / network dependencies should be passed in, not imported directly.  Fakes live in `src/<name>/testing.py` with `__chumicro_runtimes__ = ("cpython",)`.
* **Runtime markers** (Decisions [0037](../../../plans/decisions/0037-runtime-file-marking.md), [0044](../../../plans/decisions/0044-deploy-time-runtime-filtering.md)) — files whose body only makes sense on one runtime (`import wifi`, `import esp32`, `import socketpool`, `import microcontroller`, `import machine`) need `__chumicro_runtimes__ = ("circuitpython",)` or similar at module top.  Grep for runtime-specific imports without the marker.  The marker filters **device bundles**, not imports.  Cross-runtime test files legitimately import `testing.py` fakes at runtime on MicroPython and CircuitPython unix ports — sharing the fakes is exactly what `("cpython",)` is for (one fake set used across all three runtime test passes, not three parallel copies).  So when auditing a `("cpython",)`-marked file, don't assume CPython-only constructs (`from __future__`, `from typing import …`, async, importing leading-underscore `const()` names from siblings) are safe inside — check whether cross-runtime tests reach the file.  Symptom of getting this wrong: `pytest libraries/<name>/tests/` is green but `python scripts/run.py preflight` fails under `test-micropython` / `test-circuitpython` with import errors.
* **No `__future__` / no `typing` imports in device-library code** (Decision [0021](../../../plans/decisions/0021-docstring-type-policy.md)) — `from __future__ import annotations` and `from typing import ...` are banned in `libraries/*/src/` and `support/test_harness/src/`.  PEP 604 / 585 syntax only.  CPython-only trees (tests, scripts, workbench) may keep them.
* **Absolute imports only in device code** — `libraries/*/src/` and `support/test_harness/` must use `from chumicro_<name>.bar import baz`, never relative.  Relative imports break CircuitPython RAM-mode deploys.  Workbench packages and tests can use either style.
* **Naming** (Decision [0022](../../../plans/decisions/0022-naming-conventions.md)) — no single-letter variable names except `_`.  Spell out abbreviations except those AGENTS.md whitelists (`env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`).  Enforced by `CHU001`; `# noqa: CHU001` only when matching upstream API.
* **No mono-repo references in publishable `src/` trees** (`CHU006`) — no `Decision NNNN`, no `plans/...md` paths, no `scripts/run.py` mentions, no "chumicro mono-repo" framing in `libraries/*/src/`, `workbench/*/src/`, or `support/*/src/`.  Inline a one-line summary instead.
* **`f-strings` everywhere; `const()`, `memoryview`, pre-allocated buffers in hot paths.**  String building inside `runner.tick()` loops or `check`/`handle` methods is the most common hot-path allocation source.  `const()` and the leading-underscore convention are *independent axes* on MicroPython: `_X = const(N)` inlines AND strips the module-level name (RAM win, name unimportable from other modules); `X = const(N)` inlines and stays importable; bare `X = N` does neither.  Use the underscore form only when no other module — including `testing.py` and cross-runtime test files — needs to import the value.  When in doubt, public + `const()` keeps both wins.
* **VERSION + check-version + check-api gates** — if behaviour changed, was `VERSION` bumped per SemVer?  `python scripts/run.py check-version` enforces this against the last release tag; `check-api` catches accidental public API breaks.
* **Coverage gate** (Decision [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md)) — agents pass `--coverage-threshold 94` on every test invocation.  If the library is below 94%, what's covered with `# pragma: no cover` and is each one justified (runtime-only branches, hardware fallbacks)?
* **Speculative public API** — every export in the package's `__init__.py` `__all__`, grep across the mono-repo + `~/circuitpython/ChuMicro-Workspace-Template/`.  Zero callers → delete candidate.  Per the user-memory note `feedback_no_speculative_public_api.md`: until something ships to real users, "public API" means "us using it."

### 8. Library leanness

Libraries ship to constrained devices — less source = less flash, less parse-time RAM, less `.mpy` bytecode.  Run this dimension when a library feels too big or after major feature work has accreted complexity that should drop out.  The peer-LOC trigger is what makes this an audit, not a vibe.

* **Peer-LOC comparison as audit trigger.**  Tabulate `wc -l libraries/*/src/chumicro_*/*.py` deployed source.  A library ≥1.5× the cluster median for its peer cohort (networking libs vs each other, persistence libs vs each other) is a leanness candidate.  Not a target — some libraries are genuinely bigger because they cover more wire surface (full-duplex framing, multi-method HTTP).  But a 4× peer outlier with siblings that handle similar wire complexity deserves a focused pass.  The numerical comparison turns "feels too big" into a specific question.

* **Cargo-cult class methods.**  Classes inlined or copied from sibling libraries often ship more methods than the receiving library's own code calls.  AST-walk class bodies; grep for callers within this library's `src/`; flag methods with zero in-library callers.  Be careful with protocol methods (`__iter__`, `__len__`, `__eq__`, `__repr__`, `__contains__`) — they may need to stay if external code uses the class dict-like / list-like / set-like; verify before deleting.  When deleting an unused method, delete its tests in the same diff so coverage stays meaningful.

* **Spec-trivia in `__all__`.**  Constants whose meaning is internal-only — protocol reserved codes that MUST NOT cross the wire, parse-state enums consumed only by this library, internal phase markers — shouldn't be public.  Slimmer-scoped than the general "speculative public API" check in §4: those exports were *intentional* but for the wrong audience.  Test: any callers outside the library importing the symbol?  If no, drop from `__all__` (move to module-private if the library still uses it internally; tests can reach into `chumicro_<name>._wire` or similar for internals).

* **Sibling-file structural duplication.**  Pairs of files in the same library that share scaffolding while differing only in role-specific details: parallel state machines, parallel field-by-field property accessors, parallel error paths, parallel constructor wiring.  Diff the sibling files visually first to confirm the parallel — line-count alone is misleading.  Refactor via a shared base parameterized by the role-specific differences (a factory callback, a flag, a `_role_label` string for error message clarity).  Highest test churn of any leanness work — do this slice last, after the smaller cleanups have settled, so the diff is purely about the dedup.

* **Final state matters less than the audit quality.**  A pass that cuts 20% of source but misses its self-set target by 15% is still a successful audit — base-class plus subclass deltas often cost more overhead than estimated.  The audit's goal is "find the unnecessary mass," not "hit a number."  Numbers are useful for triggering and bounding the work, not for grading it.

## Extraction patterns and module hygiene

When a finding ends in "extract these helpers to a sibling module," the *how* matters as much as the *what*.  Several patterns landed wrong on the first try during the deploy audit; capture them once.

* **Call extracted helpers through the module attribute, not by bare name.**  After extracting `helpers.py` from `transport.py`, write `from . import helpers` in `transport.py` and call `helpers.do_thing()`, not `from .helpers import do_thing` + `do_thing()`.  The bare-name form binds the function object into `transport.py`'s namespace at import time; a `monkeypatch.setattr("chumicro_X.helpers.do_thing", fake)` rebinds the name in `helpers` only, while the binding inside `transport.py` still points at the original.  Tests then patch the canonical location and one patch site affects every caller transparently.

* **Update test patch paths to follow the canonical definition.**  Tests that did `monkeypatch.setattr("chumicro_X.transport.do_thing", ...)` have to switch to `"chumicro_X.helpers.do_thing"` after the extraction.  Yes it's churn.  No, don't avoid it by re-exporting names from the old module.

* **Test-cater scaffolding in src is wrong.**  If a code change in `src/` exists *only* to keep test patch paths or test imports stable — re-exports, `__all__` placeholders, dummy module attributes, lazy imports threading through a public function — the test is the thing to change, not src.  Mockability surfaces belong in `testing.py` (where they're declared and documented).  Per user feedback during the deploy audit: "code that exists to support a test harness that isn't a part of testing.py or a part of mockability shouldn't be in the package code."

* **Break import cycles with a leaf types module, not a lazy import.**  If `recovery.py` defines `DeployFailureKind` + `RecoveryPlan` and you extract a `recovery_plans.py` that needs both, a `from .recovery_plans import PLANS` inside `recovery.py`'s body works but is a smell — function-scope imports are how "import cycle" usually manifests in code review.  Cleaner: pull the shared types into a `recovery_kind.py` leaf module that imports nothing from siblings, and let both `recovery.py` and `recovery_plans.py` import from it.  Linear dependency graph; no lazy imports; tests see honest module-scope structure.

* **Renames are diff-local.**  Renaming a private function (`_enter_uf2_bootloader_programmatic` → `_dispatch_bootloader_reset`) updates every caller — including tests — in the same commit.  Don't leave a back-compat alias.  Private names don't earn migration windows.

## Process

1. **Read the library top-to-bottom first.**  One full pass through every `.py` under `src/` to build mental model.  Touch the tests too.  No edits yet.
2. **Read the library's `pyproject.toml`** for declared dependencies + any `[tool.chumicro.config]` manifest.  Helps spot mismatches between what's declared and what's used.
3. **Run the audit dimensions.**  Note findings in a list.
4. **Score each finding by confidence:**
   * **High** — dead code, obvious duplication, lying class names, broken docstring claims.  Safe to fix without further discussion.
   * **Medium** — method-shape changes, naming-style decisions, "this works but I'd structure it differently."  Benefit from a second opinion.
   * **Low** — cross-library coupling questions.  Escalate to `/audit-integration`, don't fix here.
5. **Present the punch-list to the user.**  Group by dimension.  Flag taste calls separately.
6. **Execute high-confidence items as one cohesive commit.**  Run the library's tests + every sibling package that imports from it after each batch of changes — e.g. extracting helpers from `chumicro_deploy` means also running `workbench/workspace/tests`, `workbench/repl/tests`, `workbench/pytest-device/tests` because they all import `chumicro_deploy.*` symbols and a bad-rename or namespace-binding regression won't surface in the library's own suite.  Hardware-verify if the change touches a deploy / probe / transport path (Pi Pico W CP / MP boards from `devices.yml` defaults).  Read the `git-commit` skill before each commit.
7. **Execute medium-confidence items as separate commits, one per finding.**  Per user request: small reversible commits beat one big merge — if one of N refactors turns out wrong, the other N-1 stay.  Order from lowest risk (single-call-site internal dedup, docstring fixes) to highest (module extractions that touch test patch paths) so each new commit lands on a known-good base.  Run tests + siblings after each.
8. **Surface user-facing-behavior changes separately even when technically HIGH-confidence.**  A "wiring" finding like *"the `--non-interactive` CLI flag should construct `NonInteractiveDeployer` instead of bare `Deployer`"* changes stderr output for CI log scrapers, even though the symbol swap is a 4-line patch.  Hold it back from the HIGH batch, name the behavior delta to the user, let them sign off.
9. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.**  When preflight reports a failure that looks unrelated to the audit, `git stash` + re-run preflight + `git stash pop` to verify it's pre-existing.  Flag it in the punch-list output as a separate finding so the user can scope a fix into the same session or a follow-up.  Don't silently fold the fix into an audit commit — it muddies the diff and breaks the "this commit only audited X" review contract.
10. **Hand off remaining low items to the user.**  Don't make taste calls without sign-off.

## Anti-patterns

* **Don't golf.**  Saving 3 lines at the cost of clarity is a regression.
* **Don't reshape what works just because.**  Cleanup serves the reader; if the existing shape is clear, leave it.
* **Don't auto-fix taste-call findings.**  Method-shape and naming-style decisions are owned by the human reviewer.
* **Don't break public API in an audit pass.**  Library symbols imported by sibling libraries / workbench / examples are out-of-scope for renames; flag separately.
* **Don't move trivial helpers into a `utils.py`.**  Utility-bucket modules are death by a thousand cuts.
* **Don't diverge a sibling pattern unilaterally.**  When a stylistic refactor would only touch this library while sibling libraries keep the old pattern (e.g. a namespace-classes-of-string-constants idiom shared across multiple device libraries; a particular state-machine shape replicated across networking libs), the right move is "all libs or none."  Switching one library alone diverges the family for what's usually a modest savings, and public-API ergonomics often suffer (`if state == ServiceState.OPEN` reads better than a bare module-level constant).  Defer the finding to a workspace-level decision instead of executing it in the library pass.  Escalate to `/audit-workspace` for cross-lib coordination.
* **Don't add re-export shims, `__all__` placeholders, or "kept around so monkeypatch paths keep working" comment blocks to publishable `src/`.**  If a test patch path needs to follow an extracted helper to its new module, update the test.  Mockability surfaces belong in `testing.py`; back-compat re-exports for tests don't belong in shipped code.  (See "Extraction patterns" above.)
* **Don't use lazy in-function imports to paper over a cycle you caused by extracting a sibling module.**  The cycle is a signal that the shared types belong in a third leaf module — see the recovery_kind pattern in "Extraction patterns" above.
* **Don't silently break the on-callback contract during a "shape" refactor.**  Tests pin observable interface contracts that diff-readers may miss — `on_progress` milestone sequences, `on_file_staged` call ordering, `on_execute_line` line splitting.  When extracting a shared method scaffold across two public entry points, confirm the test still sees the same callback-fraction sequence (e.g. `[0.0, 0.1, 0.2, 0.9, 1.0]`) for each entry point before committing.

* **Don't dismiss inline comments that justify a non-obvious structure without verifying the claim.**  A comment like *"defined here rather than imported from X because <reason>"* is direct evidence that someone considered the cleaner alternative and rejected it.  Before "fixing" the structure, validate the comment's claim against the actual constraint it names — and run the test sweep that the constraint relates to, not just CPython unit tests.  If the file is imported by cross-runtime tests (anything other than `*_pytest.py`), run `python scripts/run.py preflight` rather than `pytest libraries/<name>/tests/` before committing — the latter won't surface MicroPython / CircuitPython parse-time or import-time failures.  Cost of getting this wrong in the timing audit: a "fix" that deduped tick constants by importing from a sibling module, which broke MP+CP test runs because the constants the sibling module exposed were leading-underscore `const()` names (stripped from the module namespace on MP/CP).

## After the audit

If the audit produced commits:

* Bump the library's `VERSION` file *once* at the end of the audit pass — not per commit.  A multi-commit audit (HIGH batch + N medium-confidence singletons) bumps patch one time, in a final commit that also includes any post-audit lint / preflight fixes.  Per-commit bumps make the version history noisier than the actual semantic shift warrants.
* Run the `task-checkpoint` skill: `python scripts/run.py preflight --coverage-threshold 94` to confirm the full sweep (lint + build + docs + unit tests on all runtimes + checks) still passes.
* If the change touched device libraries that own time / I/O, also run `python scripts/run.py test-libraries-functional --library <name>` to hardware-verify against `devices.yml` defaults.
* Run `python scripts/run.py check-version` and `python scripts/run.py check-api` if the library has a public API surface.  Run `check-api` *before* deciding the VERSION bump level — it surfaces public-surface changes that aren't obvious from the diff.  `__slots__` renames, removed properties (even ones whose only callers were self-tests), and modified `__all__` count as public-surface changes even when the names look internal; a patch bump may not satisfy check-api in those cases.  Bump minor instead.
* Update any docstrings the user-facing API rewrites invalidated.
* Don't ship auto-fixes the user hasn't seen — taste-call findings stay in the punch-list output until the user signs off.

## Output format

When presenting the punch-list, structure it like:

```
Library audit: chumicro_<name>
================================

HIGH-CONFIDENCE (safe to fix):

  honesty    src/<name>/<file>.py:NN — <one-line description>
  duplicate  src/<name>/<file>.py:NN — <one-line description>
  dead-code  src/<name>/<file>.py:NN — <one-line description>
  lean       src/<name>/<file>.py:NN — <cargo-cult method / spec-trivia export>
  policy     src/<name>/<file>.py:NN — <Decision NNNN violation>
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  shape      src/<name>/<file>.py:NN — <one-line description>
  perf       src/<name>/<file>.py:NN — <one-line description>
  lean       src/<name>/<file>.py:NN — <sibling-file dedup proposal>
  ...

TASTE-CALL (your call):

  flow       src/<name>/<file>.py:NN — <one-line description>
  ...

ESCALATE:

  cross-lib         src/<name>/<file>.py:NN — interaction with chumicro_<other>
                    (route to /audit-integration <name>,<other>)
  sibling-cohesion  src/<name>/<file>.py:NN — pattern shared with N peer libraries
                    (route to /audit-workspace for cross-lib decision)
```

Tag taxonomy:

* `honesty` — class / arg / docstring lies about behaviour.
* `duplicate` — same logic in multiple places.
* `shape` — method-shape changes (split / inline / collapse).
* `dead-code` — zero-caller code; safe to delete.
* `wiring` — over-wiring or speculative public API.
* `perf` — hot-path allocations, redundant I/O.
* `flow` — top-to-bottom readability.
* `lean` — peer-LOC outlier, cargo-cult class methods, spec-trivia in `__all__`, sibling-file structural duplication (§8).
* `policy` — chumicro project-policy compliance (Decisions [0010](../../../plans/decisions/0010-library-testability.md), [0014](../../../plans/decisions/0014-runner-pattern.md), [0021](../../../plans/decisions/0021-docstring-type-policy.md), [0022](../../../plans/decisions/0022-naming-conventions.md), [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md), [0037](../../../plans/decisions/0037-runtime-file-marking.md), [0044](../../../plans/decisions/0044-deploy-time-runtime-filtering.md), [0051](../../../plans/decisions/0051-runner-shaped-as-project-policy.md)).
* `cross-lib` — finding spans this library + at least one other; escalate to `/audit-integration`.
* `sibling-cohesion` — finding affects multiple libraries with the same pattern; escalate to `/audit-workspace` rather than diverging this one.

The goal: fewer surprising lines, tests still pass, project-policy invariants are enforced, call sites read more honestly than before.
