---
name: audit-library
description: Code-quality audit on a single library. Looks for duplication, abstraction honesty, method shape, dead code, speculative public API, top-to-bottom readability. Produces a punch-list, then executes high-confidence cleanups with user sign-off. Use when a library has accumulated implementation debt without a recent design pass.
---

# Library audit

Audit one library (`libraries/<name>/` or `workbench/<name>/`) for cleanup opportunities.  Output a prioritized punch-list, then execute the high-confidence ones with the user's go-ahead.

## Scope

A "library" is one publishable package — one `pyproject.toml` + `src/<name>/` + `tests/`.  This skill stays inside that boundary.

**The named scope is the only scope.** Observations that fall outside the named library — even adjacent fixes that look obvious — file as a new `## Next` entry in `plans/next-up.md` and stop there. Don't fold them into the audit's commits. Out-of-scope diffs that ride along are the leading cause of revert traffic on audit work.

**Sibling audits.** Embedded-systems concerns (flash, RAM-at-import, fragmentation, `const()` / `memoryview` reality on the device) route to `/audit-embedded` — same target library, different lens.  Cross-library concerns escalate to `/audit-integration`; ecosystem concerns to `/audit-workspace`.

**Device-library scope — the embedded lens leads.** When the target lives under `libraries/`, `/audit-embedded` is the **primary** lens and this audit's standards findings defer to it: size and allocation cost — flash bytes, import-time RAM, hot-path allocations, class / def / exception count, string-constant weight — outrank docstring completeness, defensive guards, rich error prose, and well-formedness. A finding that *adds* code to a device library to satisfy a standard (a guard, a docstring section, an error taxonomy, a speculative API) must justify its bytes; if it can't, downgrade it to advisory and rank it below every size finding. The inversion applies only under `libraries/` — standards stay primary for `scripts/`, `workbench/`, `.claude/surfaces/`, and the skills themselves. Measured 2026-07-05 baseline and the cut campaign: [`plans/workstreams/library-size-cut.md`](../../../plans/workstreams/library-size-cut.md).

**Test-file split is sometimes hardware-driven, not readability.** Before flagging a large `tests/test_*.py` as a peer-LOC outlier to split: a very large class-organized module that `MemoryError`s the on-device unit sweep on a 256 KB board is a *reactive* split governed by [Decision 0072](../../../plans/decisions/0072-large-test-modules-on-constrained-boards.md) (one test file per source module; see [device-testing.md](../../../docs/contributing/device-testing.md#large-test-modules-on-a-256-kb-board)). Cite that rationale when it applies, not a readability one; the threshold is library-weight-dependent, not a fixed line count.

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

* **Class name lies about behavior.**  Example seen in this repo: `InteractiveDeployer(max_attempts=1, prompt=lambda)` was configured to *not* be interactive but the type still said "Interactive."  Fix: rename / split the class so the name matches the configuration.
* **Function mutates inputs the caller treats as read-only.**  argparse `Namespace` mutation, dict mutation through side-effects.  Fix: return resolved values; let the caller assign.
* **Return type uses string sentinels instead of an enum / dataclass.**  Fragile, no type-check support.  Fix: small `dataclass` or `StrEnum`.
* **Docstring claims behavior the code doesn't implement.**  E.g. "format-agnostic" when a regex is YAML-shaped.  Fix: correct the docstring (cheaper than retrofitting behavior).
* **Two-step state machines for one conceptual operation.**  Function A finds a thing, then function B post-processes the result by re-checking what A already could have known.  Collapse into one step.
* **"Legacy X" framing in pre-1.0 code points at a fictional previous shape.**  Different family from the dateless-history sweep in §6 (which catches verb-form *"previously this did X"* / *"X now that Y landed"*).  This is the **noun form**: a docstring or help string calls something "the legacy X", "the older X", or "the X kept for back-compat", and an accept-this-alongside-the-canonical branch in code mirrors the claim.  In pre-1.0 codebases there is usually no shipped older form to maintain compat with — the alternate-name acceptance and the prose are speculative public API that crystallized together, never asked for by a real upgrade path.  **Audit move:** for each "legacy X" or "older X" mention, grep the git log + sibling-template repo for X.  If X never shipped in a released form, the multi-name acceptance code *and* the prose are both spec-only — drop them together (one commit, scope surfaced first per the bulk-rename rule in §Process).  Worked case: `config.toml` / `config.yml` / `config.yaml` accepted alongside `project_config.toml`, framed as "legacy name accepted so user-edited workspaces from before the rename keep working" — no such rename was ever shipped; ~150 net lines + 12 tests dropped when the user confirmed.
* **Stale CLI / recovery-command / status claims in docs.**  Grep `docs/guide.md`, `README.md`, and `docs/*.md` for every CLI flag, error-message text, recovery command, environment-variable name, and feature-status assertion they reference by name; confirm each still exists with the documented shape.  See [field-reality → stale CLI claims](field-reality.md#stale-cli--recovery-command--status-claims).
* **Doc bugs cluster — find one, audit every numeric and symbolic claim in the same file.**  When one quantitative or symbolic claim in a doc is wrong, the file's other numbers and symbols deserve a focused pass rather than a passing grep.  See [field-reality → doc bugs cluster](field-reality.md#doc-bugs-cluster--audit-numbers-and-symbols-together).
* **Tests that pass a parameter but don't exercise it.**  For every test that passes a tunable kwarg, mentally change the kwarg's value and ask "would this test still pass?"  If yes, the test exercises "doesn't crash when set," not "does what it claims."  Either the test needs a value-sensitive assertion, the parameter is dead surface, or both.  Same family of finding as the lying-class-name honesty check above — the gap is between what the test code looks like it's testing and what it actually tests.  See [field-reality → tests that don't exercise the parameter](field-reality.md#tests-that-pass-a-parameter-but-dont-exercise-it).
* **Runnable doc examples must call methods that actually exist.**  Every `obj.method_name(...)` in a `README.md` / `docs/guide.md` / docstring code-fence example needs a matching `def method_name` in the library's `src/`.  An example calling a method the class doesn't have would crash if anyone ran it — a runnable-example honesty failure, not just doc drift.  **Audit move**: for each method call in a doc code-fence, grep `def <name>` in `src/`.  The functional test next door is the corroborating cross-check — if the example calls a method the tests don't, the example is wrong.
* **Intra-module `# noqa: SLF001` density signals an attribute that isn't private.**  When a single module suppresses `SLF001` N+ times to access *its own* class's underscored attributes from sibling helper functions, the underscore is lying — the attribute isn't private-to-class; it's public state read across the module.  Drop the underscore and the suppressions disappear at every call site.  **Audit move**: grep `# noqa: SLF001` per module; clusters of the same underscored name within one module (not across packages, which is the SLF001 rule's actual concern) are rename candidates.  Same family as the lying-class-name check above — the name is advertising a visibility that doesn't match the use.
* **Leading-underscore module imported by external callers.**  Same shape as the SLF001-attribute case at module scope: `_<modname>.py` that other packages import is public-from-the-outside, private-from-the-name.  **Audit move**: grep `from <package>._<modname>` and `from <package> import _<modname>` outside `<package>`; matches mean either drop the underscore or document the external coupling explicitly.

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
* **I/O in `__init__` is a runner-contract violation.**  Any library that claims runner-shape (`check(now_ms)` / `handle(now_ms)` interface) promises errors land on `state` / `last_error`, observable via introspection — not as exceptions out of the constructor.  Construction should be side-effect free; lifecycle methods (`connect()`, `start()`, `open()`) own the I/O.  `from_config` factories follow the same rule — `from_config` builds a factory and threads it into the constructor; both stay side-effect free.  **Audit move:** grep `__init__` methods for `socket.connect`, `socket.bind`, `open(`, `.recv`, `.send`, `.read`, `.write`, `.dial(`, and factory calls like `socket_factory()` / `connection_factory()` / `listener_factory()` invoked at construction time.  Each match is a finding unless the I/O is documented as part of the constructor contract (rare — usually a bug).  See [field-reality → I/O in `__init__`](field-reality.md#io-in-the-constructor-violates-the-runner-contract).

### 4. Wiring

* **Dead code.**  Functions / classes / constants with zero callers (in this library, sibling libraries, workbench, examples, tests).  Delete.
* **Over-wiring.**  Simple operations behind 3+ indirections.  E.g. `cli.py` → `dispatcher.py` → `handler.py` → `core.py` for a 5-line operation.  Flatten.
* **Speculative public API.**  Exported symbols with zero callers in the mono-repo + workspace-template repo should be deleted, not preserved as "documented public API for hypothetical external users."  Until something ships to real users, "public API" means "us using it."  **Verify against all three import shapes before flagging:** `from pkg import X`, `from pkg.submod import X`, and `import pkg; pkg.X`.  Initial greps that only check the top-level shape routinely over-report zero-callers by 50 %+ — the symbol is exported once but reached via the submodule by everyone who uses it.  Worked case: the deploy audit's first pass flagged 37 zero-caller candidates; after rechecking the submodule shape, only 12 were real (workspace, repl, and pytest-device all reach into deploy via `from chumicro_deploy.recovery import …` / `from chumicro_deploy.macos_fskit import …` shapes the top-level grep missed).
* **Speculative public API extends to class properties and public methods, not just `__all__` exports.**  Named-without-underscore properties / methods on public classes are the same shape of speculative surface: a class is exported, a name on it has no external callers, and the name's presence costs flash + suggests support the codebase doesn't actually provide.  Default action is HIGH-confidence drop — same evidence threshold as `__all__` exports.  When internal code uses the name, the rewrite is mechanical (access the underscored attribute with `# noqa: SLF001`, matching how the rest of the class is already touched).  See [field-reality → speculative class properties](field-reality.md#speculative-public-api-class-properties).
* **Speculative public API extends to ADR contracts.**  When deleting a speculative symbol, the ADR that specified it is part of the surface — trim or rewrite the relevant section in the same diff (in place, per the ADR-edit rule).  Field reality:  `KVStoreReadOnly` was declared, exported in `__all__`, documented in `docs/guide.md` with an example handler, and spec'd in ADR 0034 §9 as "raised by the LittleFS backend when CP's `storage.remount` would fail" — but the LittleFS backend was MP-only-marked, the raise path was never wired, and zero callers existed across the mono-repo and workspace-template.  ADRs that describe an unimplemented contract drift silently; the audit pass is the moment to catch them.

### 5. Performance / efficiency

(Library code only — workbench / scripts have different rules per AGENTS.md.)

* **Allocations in hot paths.**  String building inside `runner.tick()` loops, dict construction per iteration, object creation in tight loops.  Pre-allocate; cache attributes; use `memoryview` to avoid copies.
* **Per-byte loops where per-chunk works.**  A specific shape of the above: `for byte in chunk: state.feed(byte)` calls a method (and allocates a frame) per byte.  When the state machine can consume `min(remaining, needed)` bytes per state via slice / extend / XOR-loop on a slice, restructure to per-chunk.  Each call frame on MicroPython has measurable cost; on a 1024-byte recv buffer, per-byte processing means 1024 frames per tick.
* **Redundant filesystem / network calls.**  Multiple `stat()` calls on the same path; multiple opens of the same file.  Cache or refactor to one read.
* **Unused imports + unused parameters.**  Cheap to spot, cheap to remove.
* **Eager work in `__init__` that the caller may never need.**  Defer to first use when reasonable.

### 6. Top-to-bottom readability

The user's framing: "following the file should allow me to understand the logic the more i scroll down instead of going all over the place."

This dimension's comment checks **detect and trim only** — the subtractive posture ("don't golf, if the shape is clear leave it") is correct for a library pass.  A comment so degraded it needs *new prose written from a fresh read of the code* is `/audit-comments`'s job, not this one: file it as a `## Next` pointer to `/audit-comments <name>` rather than trimming it further here.  The ratio sweep and AI-tic grep below are the *detectors* that feed that skill; the **cold-maintainer test** in the essay-bloat bullet is both the degradation detector and the trim-here-vs-route-there decision boundary (scope rule stated there).

* **Convention per file.**  Either public-functions-first or helpers-first; pick one and stick to it within the file.
* **Adjacent related concepts.**  Helper functions for the same feature should sit together, not be scattered.
* **Early-exit guards first.**  `if not condition: raise / return` should land at the top of the function, not be buried.
* **Docstrings and comments explain *why*, not just *what*.**  The signature says what; the body says how; the prose should say why this exists or what subtle invariant it holds.  Inline comments must *narrate* (`# every 30 s, queue a fetch`), not *label* (`# start a request`).  Drop prose that only re-states the signature.
* **Essay-bloat: prose that dwarfs the code it wraps.**  Compute a per-function `(docstring+comment) / code` line ratio across `src/` and read the outliers top-down — greps cannot see bloat or incoherence; ratio + read can.  Cut narration that restates the code, justifies the diff, or duplicates a constant's own docstring.  Apply the **cold-maintainer test**: every sentence must be comprehensible to a maintainer who didn't write it.  This is also the degradation detector that routes to `/audit-comments` — so split on scope: an *isolated* unparseable sentence in an otherwise-sound docstring, cut it here (don't paraphrase it).  But when the comment fails the test *as a whole* — cutting the bad sentences would leave nothing that tells a reader what the thing is or why it exists — that is a rewrite, not a trim: file a `## Next → /audit-comments <name>` pointer and **leave the comment in place**.  Do not whittle it to a stub here; a stub is the residue `/audit-comments` was created to prevent.  **Calibrate before cutting:** `typing.Protocol` method bodies (the docstring *is* the contract), `@property` / `@abstractmethod` stubs, and destructive- or many-parameter public-API `Args:` blocks legitimately run long — the ratio is a *trigger*, not a target.  See [field-reality → essay-bloat and the cold-maintainer test](field-reality.md#essay-bloat-and-the-cold-maintainer-test).
* **AI-tic, grammar-tic, and dateless-history sweep in comments.**  Run the standing regex from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex) over `src/` comments and docstrings, not just markdown.  Also apply the `the (one|single|sole) <noun>` definition-tic test and the brand-name / stacked-article checks from [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans).  These are *triage sweeps, not verdicts*: legitimate invariant prose (*"the single owner of the staging path"*, *"exactly one mechanism"*) is a keep, not a tic.  **Decision rule for each hit — the read-just-as-well test:** delete the word in your head and re-read the sentence; if it reads just as well without, drop it.  This is sharper than "judge each hit" and replaces it.  Keep-cases fail the test naturally: `canonical form`, `canonical 3-tuple`, `canonical slash-form path` lose information when "canonical" is deleted.  Drop-cases (*"canonical template"*, *"canonical content"*, *"canonical first-write text"*, *"the canonical reference"*) all read just as well as plain *"template"*, *"content"*, *"first-write text"*, *"the reference"*.  Same test applies to *robust*, *comprehensive*, *simply*, *just*, *actually*.  Worked case: 21 `canonical` occurrences in the workspace package, 16 dropped via the test, 5 real technical uses kept.  Flag the dateless history `CHU012` can't anchor on: *"previously this…"*, *"X now that / before / until Y landed"*, removed-code explanations, bench-observation logs (*"empirically the slowest we've observed"*), and **any `.scratch/` reference in publishable `src/`**.  `.scratch/` is the agent scratch convention; shipped code must never name it as a pointer *or* build it as a runtime path (a generated artifact uses the gitignored `_generated/` convention instead).  Both shapes are defects.  The lint catches the dated / verb-anchored subset; this sweep catches the judgment cases.  See [field-reality → AI-tic and dateless-history in code comments](field-reality.md#ai-tic-and-dateless-history-in-code-comments).

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
* **Naming** (Decision [0022](../../../plans/decisions/0022-naming-conventions.md)) — no single-letter variable names except `_`.  Spell out abbreviations into full words; AGENTS.md lists the recurring ones to expand (`env` → `environment`, `buf` → `buffer`, `src` → `source`, `cmd` → `command`, `msg` → `message`, `err` → `error`, `ref` → `reference`, `addr` → `address`, `exc` → `exception`, `exec` → `execute`).  Enforced by `CHU001`; `# noqa: CHU001` only when matching upstream API.
* **No mono-repo references in publishable `src/` trees** (`CHU006`) — no `Decision NNNN`, no `plans/...md` paths, no `scripts/run.py` mentions, no "chumicro mono-repo" framing in `libraries/*/src/`, `workbench/*/src/`, or `support/*/src/`.  Inline a one-line summary instead.
* **`f-strings` everywhere; `const()`, `memoryview`, pre-allocated buffers in hot paths.**  String building inside `runner.tick()` loops or `check`/`handle` methods is the most common hot-path allocation source.  `const()` and the leading-underscore convention are *independent axes* on MicroPython: `_X = const(N)` inlines AND strips the module-level name (RAM win, name unimportable from other modules); `X = const(N)` inlines and stays importable; bare `X = N` does neither.  Use the underscore form only when no other module — including `testing.py` and cross-runtime test files — needs to import the value.  When in doubt, public + `const()` keeps both wins.
* **No `__slots__` in device-library code** (Decision [0065](../../../plans/decisions/0065-device-library-scaffolding-cost.md)) — grep `__slots__` in `libraries/*/src/`; every match is a HIGH-confidence drop.  MicroPython and CircuitPython have no `__slots__` implementation ([MP discussion #13745](https://github.com/orgs/micropython/discussions/13745)); the runtimes parse the declaration but the attribute-locking + per-instance-dict-drop is a CPython-only behavior.  On-device value is zero, the only payoff is typo-shielding inside CPython tests, and the cost is the parsed declaration on every board this library ships to.  Per-board flash sits around 800 KB total across ~15 libraries — every line of test-only scaffolding in `src/` is real flash spent for zero device value.  See [field-reality → no `__slots__`](field-reality.md#no-slots-in-device-library-code).
* **No pure-passthrough `@property` in device-library code** (Decision [0065](../../../plans/decisions/0065-device-library-scaffolding-cost.md)) — grep `@property` in `libraries/*/src/`; classify each: pure passthrough (`def state(self): return self._state`) is a HIGH-confidence drop; computed properties (`bytes(self._body_view[:self._offset])`, `state in (DONE, ERROR)`) stay or convert to a regular method.  Each `@property` access on MP/CP is a Python-level function call (multiple µs vs a direct attribute load), and each declaration allocates a `property` object on the class.  Replace with a direct public attribute: `self.state = ...` in `__init__` instead of the descriptor pair.  Public-API stays compatible because callers write `parser.state` either way.  If the class has many similarly-named fields and the property scaffolding is enforcing a read-only convention, the underscore-on-the-backing-field convention does the same job at zero cost.
* **VERSION + check-version + check-api gates** — if behavior changed, was `VERSION` bumped per SemVer?  `python scripts/run.py check-version` enforces this against the last release tag; `check-api` catches accidental public API breaks.
* **Coverage gate** (Decision [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md)) — agents pass `--coverage-threshold 94` on every test invocation.  If the library is below 94%, what's covered with `# pragma: no cover` and is each one justified (runtime-only branches, hardware fallbacks)?
* **Speculative public API** — every export in the package's `__init__.py` `__all__`, grep across the mono-repo + the sibling workspace-template checkout (conventionally `$WORKSPACE_TEMPLATE_ROOT`).  Zero callers → delete candidate.  Until something ships to real users, "public API" means "us using it" — see the [Speculative public API](#4-wiring) bullet above for the broader rule.

### 8. Library leanness

Libraries ship to constrained devices — less source = less flash, less parse-time RAM, less `.mpy` bytecode.  Run this dimension when a library feels too big or after major feature work has accreted complexity that should drop out.  The peer-LOC trigger is what makes this an audit, not a vibe.

* **Peer-LOC comparison as audit trigger.**  Tabulate `wc -l libraries/*/src/chumicro_*/*.py` deployed source.  A library ≥1.5× the cluster median for its peer cohort (networking libs vs each other, persistence libs vs each other) is a leanness candidate.  Not a target — some libraries are genuinely bigger because they cover more wire surface (full-duplex framing, multi-method HTTP).  But a 4× peer outlier with siblings that handle similar wire complexity deserves a focused pass.  The numerical comparison turns "feels too big" into a specific question.

* **Cargo-cult class methods.**  Classes inlined or copied from sibling libraries often ship more methods than the receiving library's own code calls.  AST-walk class bodies; grep for callers within this library's `src/`; flag methods with zero in-library callers.  Be careful with protocol methods (`__iter__`, `__len__`, `__eq__`, `__repr__`, `__contains__`) — they may need to stay if external code uses the class dict-like / list-like / set-like; verify before deleting.  When deleting an unused method, delete its tests in the same diff so coverage stays meaningful.

* **Spec-trivia in `__all__`.**  Constants whose meaning is internal-only — protocol reserved codes that MUST NOT cross the wire, parse-state enums consumed only by this library, internal phase markers — shouldn't be public.  Slimmer-scoped than the general "speculative public API" check in §4: those exports were *intentional* but for the wrong audience.  Test: any callers outside the library importing the symbol?  If no, drop from `__all__` (move to module-private if the library still uses it internally; tests can reach into `chumicro_<name>._wire` or similar for internals).  **After dropping names, grep `README.md` + `docs/guide.md` + docstrings + examples for each removed name** — user-facing prose names internal classes more often than code-grep predicts.  See [field-reality → spec-trivia and doc residue](field-reality.md#spec-trivia-in-all--and-the-doc-residue).

* **Sibling-file structural duplication.**  Pairs of files in the same library that share scaffolding while differing only in role-specific details: parallel state machines, parallel field-by-field property accessors, parallel error paths, parallel constructor wiring.  Diff the sibling files visually first to confirm the parallel — line-count alone is misleading.  Refactor via a shared base parameterized by the role-specific differences (a factory callback, a flag, a `_role_label` string for error message clarity).  Highest test churn of any leanness work — do this slice last, after the smaller cleanups have settled, so the diff is purely about the dedup.

* **Final state matters less than the audit quality.**  A pass that cuts 20% of source but misses its self-set target by 15% is still a successful audit — base-class plus subclass deltas often cost more overhead than estimated.  The audit's goal is "find the unnecessary mass," not "hit a number."  Numbers are useful for triggering and bounding the work, not for grading it.

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
8. **Inspect the staged diff before every audit commit.**  Run `git --no-pager diff --cached` and confirm the staged changes match the commit message intent — every hunk should be one you made, nothing extra.  Audits run iteratively, and concurrent edits (linter hooks, parallel agent sessions, the user's own in-flight work) can land in the same files between your Edit and your `git add`; staging "the file" with `git add libraries/<name>/...` then picks up everything in the working tree.  Either stage with `git add -p` for surgical commits when foreign hunks are present, or always inspect `--cached` before `commit`.  Most expensive failure mode in iterative audit work; the cached-diff check costs ~2 seconds.  See [field-reality → inspect the staged diff](field-reality.md#inspect-the-staged-diff-before-every-audit-commit).
9. **Surface user-facing-behavior changes separately even when technically HIGH-confidence.**  A "wiring" finding like *"the `--non-interactive` CLI flag should construct `NonInteractiveDeployer` instead of bare `Deployer`"* changes stderr output for CI log scrapers, even though the symbol swap is a 4-line patch.  Hold it back from the HIGH batch, name the behavior delta to the user, let them sign off.
10. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.**  When preflight reports a failure that looks unrelated to the audit, `git stash` + re-run preflight + `git stash pop` to verify it's pre-existing.  Flag it in the punch-list output as a separate finding so the user can scope a fix into the same session or a follow-up.  Don't silently fold the fix into an audit commit — it muddies the diff and breaks the "this commit only audited X" review contract.
11. **Hand off remaining low items to the user.**  Don't make taste calls without sign-off.

## Anti-patterns

* **Don't golf.**  Saving 3 lines at the cost of clarity is a regression.
* **Don't reshape what works just because.**  Cleanup serves the reader; if the existing shape is clear, leave it.
* **Don't auto-fix taste-call findings.**  Method-shape and naming-style decisions are owned by the human reviewer.
* **Surface public-API breaks separately, don't fold them into the HIGH-confidence batch.**  Library symbols imported by sibling libraries / workbench / examples can be renamed or removed when the audit case is strong, but the break is a behavior delta — name it to the user, get sign-off, land it as its own commit rather than bundling with mechanical cleanups.  The "audit only changed X" review contract on the HIGH batch is what makes the batch safe to apply.
* **Don't move trivial helpers into a `utils.py`.**  Utility-bucket modules are death by a thousand cuts.
* **Don't diverge a sibling pattern unilaterally.**  When a stylistic refactor would only touch this library while sibling libraries keep the old pattern (e.g. a namespace-classes-of-string-constants idiom shared across multiple device libraries; a particular state-machine shape replicated across networking libs), the right move is "all libs or none."  Switching one library alone diverges the family for what's usually a modest savings, and public-API ergonomics often suffer (`if state == ServiceState.OPEN` reads better than a bare module-level constant).  Defer the finding to a workspace-level decision instead of executing it in the library pass.  Escalate to `/audit-workspace` for cross-lib coordination.
* **Don't add re-export shims, `__all__` placeholders, dummy module attributes, or "kept around so monkeypatch paths keep working" comment blocks to publishable `src/`.**  If a test patch path needs to follow an extracted helper to its new module, update the test — yes it's churn.  Mockability surfaces belong in `testing.py`; code that exists in shipped `src/` only to support a test harness that isn't part of `testing.py` doesn't belong there.
* **Don't import extracted helpers by bare name when tests will monkeypatch them.**  `from . import helpers` + `helpers.do_thing()` lets a `monkeypatch.setattr("chumicro_X.helpers.do_thing", fake)` reach every caller through the module attribute.  `from .helpers import do_thing` binds the function object into the caller's namespace at import time, so the patch rebinds `helpers` only and the caller still holds the original — tests then drift into multi-site patching to work around the binding.
* **Don't use lazy in-function imports to paper over a cycle you caused by extracting a sibling module.**  The cycle is *diagnostic*: the original module bundled two responsibilities whose true boundary sits differently from where the cut was sketched.  Re-draw the boundary, or pull the shared types into a leaf module that imports nothing from siblings — `recovery_kind.py` holding `DeployFailureKind` + `RecoveryPlan` for both `recovery.py` and `recovery_plans.py` is a worked case.  Only reach for a lazy import after confirming the structural fix won't work, and write the rationale inline so a later auditor doesn't undo the analysis.
* **Walker helpers belong with what they walk, not with what they read.**  When extracting modules, helpers that iterate a collection and `isinstance(item, <Type>)` against its members go in the module that defines `<Type>`, not in the module that owns the collection's source — the instinct "this reads `session.items`, so it goes in the session-helper module" is wrong when the helper also needs to know the *type* of items, since it induces a cycle that lazy imports paper over.  The walker module wants the data *and* the type together; the type's home is the walker's home.
* **Renames are diff-local — don't leave a back-compat alias for a private name.**  Renaming a private function updates every caller (including tests) in the same commit.  Private names don't earn migration windows.
* **Don't silently break the on-callback contract during a "shape" refactor.**  Tests pin observable interface contracts that diff-readers may miss — `on_progress` milestone sequences, `on_file_staged` call ordering, `on_execute_line` line splitting.  When extracting a shared method scaffold across two public entry points, confirm the test still sees the same callback-fraction sequence (e.g. `[0.0, 0.1, 0.2, 0.9, 1.0]`) for each entry point before committing.

* **Don't add per-change justification comments to library source during audit passes.**  Inline notes like `# bench-validated -25% allocation` or `# skips the bytes() copy` belong in the commit message body, not in `src/`.  Per-change comments document *why the diff exists* (audit reasoning) — they rot fast (today's bench number isn't necessarily true three audits later), they multiply across sites, and they ship as flash bytes on every supported board.  A general work-being-done comment at a strategy's home (one place, naming the buffer-reuse pattern at the parser's top) is OK sparingly; per-change notes are not.  Pre-existing per-change comments from earlier audits are legacy — don't proliferate, trim when convenient.  AGENTS.md → Code comments is the broader rule.

* **Don't gut a long docstring just because the ratio flagged it.**  Protocol contracts, a destructive-API `Args:` block (e.g. the flash-offset warning that stops a caller bricking a board), and clean multi-parameter public-API docs earn their length.  Cutting them is essay-bloat inverted — the "don't golf" rule applies to prose too.  Trim narration and incoherence; keep the load-bearing contract.

* **Don't dismiss inline comments that justify a non-obvious structure without verifying the claim.**  A comment like *"defined here rather than imported from X because <reason>"* is direct evidence that someone considered the cleaner alternative and rejected it.  Before "fixing" the structure, validate the comment's claim against the actual constraint it names — and run the test sweep that the constraint relates to, not just CPython unit tests.  If the file is imported by cross-runtime tests (any test file not marked `__chumicro_runtimes__ = ("cpython",)` or `__chumicro_host_only__ = True`), run `python scripts/run.py preflight` rather than `pytest libraries/<name>/tests/` before committing — the latter won't surface MicroPython / CircuitPython parse-time or import-time failures.  See [field-reality → don't dismiss inline comments](field-reality.md#dont-dismiss-inline-comments-without-verifying-the-claim).

## After the audit

If the audit produced commits:

* Bump the library's `VERSION` file *once* at the end of the audit pass — not per commit.  A multi-commit audit (HIGH batch + N medium-confidence singletons) bumps patch one time, in a final commit that also includes any post-audit lint / preflight fixes.  Per-commit bumps make the version history noisier than the actual semantic shift warrants.
* Run the `task-checkpoint` skill — it gates preflight at `--coverage-threshold 94`, refreshes `plans/next-up.md`, commits, and pushes.  The audit-specific gates below run before its commit step.
* If the change touched device libraries that own time / I/O, also run `python scripts/run.py test-libraries-functional --library <name>` to hardware-verify against `devices.yml` defaults.
* Run `python scripts/run.py check-version` and `python scripts/run.py check-api` if the library has a public API surface.  Run `check-api` *before* deciding the VERSION bump level — it surfaces public-surface changes that aren't obvious from the diff.  `__slots__` removal (device-library policy per §7), removed properties (even ones whose only callers were self-tests), and modified `__all__` count as public-surface changes even when the names look internal; a patch bump may not satisfy check-api in those cases.  Bump minor instead.
* Update any docstrings the user-facing API rewrites invalidated.
* Don't ship auto-fixes the user hasn't seen — taste-call findings stay in the punch-list output until the user signs off.

The audit is done when:

* Every HIGH-confidence finding either has a corresponding commit or has been explicitly skipped with the user's sign-off.
* Every MEDIUM and TASTE-call finding has an answer from the user — applied, deferred to `plans/next-up.md`, or dropped.
* `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.
* If the library owns time / I/O, `python scripts/run.py test-libraries-functional --library <name>` passes on the `devices.yml` defaults (or you've flagged that you couldn't run it).
* `check-api` agrees with the chosen VERSION bump level.
* Any ESCALATE findings are filed as `## Next` entries pointing at `/audit-integration` or `/audit-workspace`, not silently dropped.

If new stumbles surface after the final commit (a lint failure unmasked by removed dead code, a guide example that still names a deleted symbol), file as a follow-up rather than expanding the audit pass.

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
  prose      src/<name>/<file>.py:NN — <essay-bloat / incoherent / AI-tic / dateless history>
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

* `honesty` — class / arg / docstring lies about behavior.
* `duplicate` — same logic in multiple places.
* `shape` — method-shape changes (split / inline / collapse).
* `dead-code` — zero-caller code; safe to delete.
* `wiring` — over-wiring or speculative public API.
* `perf` — hot-path allocations, redundant I/O.
* `flow` — top-to-bottom readability.
* `prose` — docstring / comment essay-bloat, incoherence, AI-tic, dateless history (§6).
* `lean` — peer-LOC outlier, cargo-cult class methods, spec-trivia in `__all__`, sibling-file structural duplication (§8).
* `policy` — chumicro project-policy compliance (Decisions [0010](../../../plans/decisions/0010-library-testability.md), [0014](../../../plans/decisions/0014-runner-pattern.md), [0021](../../../plans/decisions/0021-docstring-type-policy.md), [0022](../../../plans/decisions/0022-naming-conventions.md), [0025](../../../plans/decisions/0025-dual-coverage-thresholds.md), [0037](../../../plans/decisions/0037-runtime-file-marking.md), [0044](../../../plans/decisions/0044-deploy-time-runtime-filtering.md), [0051](../../../plans/decisions/0051-runner-shaped-as-project-policy.md), [0065](../../../plans/decisions/0065-device-library-scaffolding-cost.md)).
* `cross-lib` — finding spans this library + at least one other; escalate to `/audit-integration`.
* `sibling-cohesion` — finding affects multiple libraries with the same pattern; escalate to `/audit-workspace` rather than diverging this one.

The goal: fewer surprising lines, tests still pass, project-policy invariants are enforced, call sites read more honestly than before.
