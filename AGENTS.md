# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

## Non-negotiable rules

### Workflow

- Always pass preflight before commit. If preflight is already red on `main` (not from your changes), surface and stop. No carve-out for doc-only, plans-only, handoff, or workstream-log commits.
- Always invoke the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill at end of work. It owns preflight, `plans/next-up.md` refresh, durable-lesson lift, commit, and push. "End of work" is per coherent unit of work (one commit subject), not per session.  Multiple checkpoints per session is normal.
- Always anchor claims to evidence (file, symbol, test, or command). Verify by reading code, running tests, or checking command output. Training recall is not verification. For anything time-sensitive, version-specific, or newer than the model cutoff, always web-search rather than asserting from memory.
- Sub-agent reports and session handoffs describe intent, not state. Never build on a concrete claim from a sub-agent (Explore / audit-* / general-purpose) or a `plans/handoffs/` file without re-deriving from code, tests, or commands, *especially* one marked `[VERIFIED]`. These docs are an index of what was tried, not a boundary on current state.
- Read the artifact, not the summary. Never trust an exit code, "preflight passed" string, or sub-agent summary alone.  Re-read the file or re-run the smallest failing check.
- Re-read after external change. Always re-assert `pwd` after any external change; a "modified externally" notice means re-read the file before editing it again.
- Never expand scope when fixing a focused bug. Mention pre-existing issues separately, unless they qualify for the inline-fix carve-out below.
- Never add features, abstractions, or speculative error handling beyond what was asked. Removing unnecessary complexity from code you're already touching is fine.
- Always clean up after yourself. If you make an import, variable, function, or test unused, remove it. If your change affects docs, update them. Exception: when a pre-existing inconsistency is directly material to the task (e.g. writing a regex to handle drift you could instead normalize), surface the choice rather than papering over it.
- Inline-fix carve-out for pre-existing drift. When a pre-existing issue is obvious or easily researched (prose verifiably wrong against current code or an accepted ADR, a stale flag name, a renamed identifier, a dead reference), fix it inline and mention in the commit message body. A long backlog of tiny corrections is its own failure mode.  Fixing them along the workstream hardens the ecosystem. Anything that opens a research rabbit hole (refactors, adjacent bug fixes, behavior changes, anything where a quick read can't confirm the right answer) stays out unless asked.
- Always re-verify state after recovery actions. When a fix depends on the user running a recovery action (replug, reset-board, unwedge), re-run the failing detection and the smallest failing test before committing. "Done" from the user is the signal to verify, not proof the fix worked.
- `main` is the only long-lived branch ([Decision 0019](plans/decisions/0019-branching-model.md)) and it is PR-only ([Decision 0120](plans/decisions/0120-main-is-pr-only.md)). Work on a short-lived topic branch (`fix/…`, `docs/…`, `feature/…`), push the branch, and open or update a pull request against `main`. Never push to `main` directly; the ruleset rejects it for every actor, agent sessions included. Outside contributors fork and follow the same PR path ([CONTRIBUTING.md](CONTRIBUTING.md)). The one other branch 0019 allows is a short-lived `release/<library>-vX.Y.x` cut from a stable tag to hotfix an older release, deleted once the patch ships.
- No backwards-compatibility burden until 1.0: no aliases for renamed symbols, no deprecated-but-working surfaces, no tolerant readers of our own retired formats, no production fallbacks whose only consumer is a test. Never deprecate or provide legacy support. Break and migrate every consumer in the same commit; tests adapt to code, never code to tests. Cross-runtime shims (MP/CP/CPython) are the mission, not compat.  They stay, as does tolerance toward external peers (broker quirks, malformed network input). [Decision 0092](plans/decisions/0092-no-backwards-compat-before-publication.md) carries the rationale.
- Always pass the commit message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`) so backticks, `$`, parens, and newlines pass literally. No `Co-Authored-By: Claude …` trailer (a local commit-msg hook strips any that slip through). Full mechanics + verify step: [`git-commit`](.github/skills/git-commit/SKILL.md) skill.
- Git safety: never bypass safety without explicit ask. No `git config` edits, no `--no-verify` / `--no-gpg-sign`, no force-push to main, no destructive ops (`reset --hard`, `checkout .`, `restore .`, `clean -f`, `branch -D`).
- Never `git --amend`. A failed pre-commit means the commit didn't happen.
- Never commit unsolicited.
- Always run `git --no-pager diff --cached --stat` before every commit and confirm staged hunks match intent. Always stage with explicit pathspecs (`git add path/to/file`). Never `git add .` or `git add -A`. Parallel agent sessions, linter hooks, and in-flight user work all land in the same files between Edit and `git add`.  Staging "the file" picks up everything in the working tree.
- Never `git stash` to scope a cached diff or "park" work.  Stash removes content from a parallel agent's or user's working tree mid-session. Use explicit pathspecs (`git add <path>`) to scope a commit; for already-staged unrelated work, `git restore --staged <path>` unstages without removing working-tree content.
- `.scratch/` is gitignored. Use this folder for temp files and log captures.
- Always pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Always disable pagers (`git --no-pager`, `| cat`).
- Always use file tools to write or edit files. Never use heredocs, `echo`, `printf`, or `cat` for file content. The heredoc rule above is commit messages only.
- Never hard-code or commit secrets. Wifi passwords, MQTT credentials, API tokens belong only in the gitignored `secrets.toml`.
- Always pair a lint suppression with a brief explanation why, so a reviewer can verify.
- Always skim [`plans/patterns.md`](plans/patterns.md) for an established pattern before writing implementation code in `libraries/` or `workbench/`.
- Always invoke the [`new-library`](.github/skills/new-library/SKILL.md) skill before scaffolding a new library. It owns directory layout, `__init__.py` + `testing.py` placement, test placement (`tests/` cross-runtime by default; pytest-fixture suites opt down via `__chumicro_runtimes__ = ("cpython",)`), initial `VERSION` seed, `pyproject.toml`, and `__all__`. `python scripts/run.py new-library --workbench` scaffolds a host-only tool. Reading an existing library to copy its layout is a fallback only.
- Always read [`plans/decisions/README.md`](plans/decisions/README.md) before creating or editing a file under `plans/decisions/`. New ADRs always route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill.  Invoke it, never freehand. An ADR contains only context, decision, invariant, rationale, and rejected alternatives with reasoning. Everything else (phase plans, migration rosters, bake-validation logs, class signatures, per-runtime substrate tables, future-work checklists) is mechanism and goes to [`plans/workstreams/<name>.md`](plans/workstreams/).
- A `plans/workstreams/<name>.md` file you're picking up is a directive, not a research artifact. Execute the next unshipped phase from its `## Implementation phases` / `## Plan` section. Verify any claim that looks changed (read the code, run the test, check the commit), then proceed. Never bounce to the user without a concrete blocker. As each phase lands, append one line to `## Validation history`; update the `Status:` line (`shipped`/`parked`/`superseded`) when fully done.
- Always run `--help` on `python scripts/run.py`, `chumicro-workspace`, `chumicro-deploy`, or `chumicro-repl` (and each subcommand) before asking the user or giving up on a flag. The full subcommand inventory is discoverable.
- Always deploy through `chumicro-workspace deploy` (or `chumicro-deploy` for raw file trees the project structure doesn't support). Both run the one device-staging path: diff + `rsync --delete`. Never bypass. The lower-level transport primitives it is built from (`deploy_files` / `delete_files` / `list_files_in_scope`) stay `chumicro_deploy`-internal; consumers stage through `Deployer.deploy_diff()` (enforced by `CHU034`).
- A library public-API or behavior change requires one `VERSION` bump per change-set, never one per commit. The gate is change-set wide: `check-version` diffs a pull request as `origin/main...HEAD`, and CI hands it `CHUMICRO_DIFF_BASE` on a direct push so a multi-commit push is graded whole. One bump anywhere in the set satisfies it, so a full audit pass is a single bump and a pull request should never carry a version ladder for one library. `python scripts/run.py check-api` confirms the minimum level (patch / minor / major). A behavior-only change still bumps `patch` so users see it land in their version pin, and that includes a changed exception message or any other shipped string. A `src/*.py` diff limited to comments and docstrings is **not** release-relevant and needs no bump. `check-version` decides this structurally, by comparing docstring-stripped ASTs ([Decision 0113](plans/decisions/0113-docstring-only-not-release-relevant.md)). Detail in [docs/contributing/releases.md](docs/contributing/releases.md).
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython).

### Testing

- Always pass `--coverage-threshold 94` to `test` and `preflight`.
- Test skips must be loud. Never write a test with no assertions or validation. Always use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- A cross-runtime test file is the default for `tests/test_*.py`. Never `import pytest`; use plain `assert` and constructor-injected fakes from each library's `testing.py`. Opt down via in-file markers: `__chumicro_runtimes__ = ("cpython",)` lifts the `import pytest` ban for fixture suites; `__chumicro_host_only__ = True` for host-only (next bullet). The marker is the contract; `_pytest.py` is only a human hint. The top docstring names the lane.
- A host-only test file declares `__chumicro_host_only__ = True` at module level to run on CPython + MP/CP unix-ports but never on real silicon, for files that drive runtime-specific source through host fakes to assert off-target behavior (e.g. `test_runtime_acquisition_raises_on_cpython`). The collector excludes them from device-unit staging. The filename `test_{cp,mp}_*` prefix is a human hint; the marker is the contract.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under both CircuitPython and MicroPython. A PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect.
- When writing tests, depend only on the package's own `src/` + `testing.py`, stdlib, pytest + plugins, `chumicro_test_harness` (including its submodules, see [Decision 0082](plans/decisions/0082-test-harness-as-infrastructure-library.md)), and the package's declared dependencies from `pyproject.toml` (runtime `dependencies` plus the `[test]` extra), including their `testing.py` fakes. A test-only dependency, like a reactor-contract test importing `chumicro_runner`, is declared in the `[test]` extra so the suite's closure stays installable. Never import an undeclared chumicro package and never read sibling-repo filesystems.
- Real-board bake catches orchestration bugs unit tests miss. Changes touching host-side concurrency, streaming-transport plumbing, marker dispatch, multi-call sequences against the same transport, or abort / cleanup paths need a real-board bake before "done", *even when the unit suite is green*. Run a representative demo or Category 1 functional test against a real board before reporting orchestration work complete.
- A test stand-in fake must model the target's awkward behaviors, not just the easy path. A fake that returns the convenient result regardless of inputs hides production bugs that only surface against the real component.
- A literal or `(A, B)` tolerance in production code that exists *specifically* to accommodate a fake's hardcoded value is a smell that the fake is wrong, not the platform. Ask why both literals exist.  A fake pinned to A is the usual answer. The fix is the fake reading the platform's real value, not production tolerating both. Full recognizer + worked example in [`plans/patterns.md`](plans/patterns.md).

### Library code rules

- Runner-tick budget: ≤5 ms per call in `tick()` / `handle()`; only `Runner.wait` blocks ([Decision 0080](plans/decisions/0080-runner-reactor.md)). No `async` / `await` / `asyncio` / `uasyncio` ([Decision 0087](plans/decisions/0087-generators-for-sequential-io.md), enforced by `CHU033` outside `functional_tests/`). No ISRs, no blocking TCP/TLS handshake.  Use `chumicro_sockets`'s tick-driven connector ([0081](plans/decisions/0081-non-blocking-connect-via-tick-driven-connector.md)). Offenders: `time.sleep(>0.005)`, `select.poll(>0)`, blocking `getaddrinfo` / `socket.recv()` / `machine.lightsleep`, MP `os.urandom`.
- All time math must go through `chumicro_timing` (`ticks_ms`, `ticks_diff`, `ticks_add`, `Heartbeat`) in `libraries/` source and in any tests gating on deadlines or elapsed time. Never call `time.monotonic`, `time.ticks_ms`, or `supervisor.ticks_ms` directly.  Mixing them pits a `chumicro_timing`-tick deadline against a wall clock and produces a "freeze" that looks like a stalled service but is really mismatched units. Sole exception: `chumicro_timing`'s own resolution tests.
- **Where a clock is injected, that clock does the comparing.** A class taking `ticks=` must reach every deadline through it (`self._ticks.ticks_diff(...)`), never through a module-level `from chumicro_timing.ticks import ticks_diff` in a helper. The import silently wins over the caller's clock and `FakeTicks` will not catch it, because a chumicro-shaped fake agrees with the hardcoded version; test with a clock that disagrees. The design rule that avoids it: a suspended object publishes its deadline via `next_deadline(now_ms)` and never judges a time itself, so `ready(now_ms)` is only for conditions needing no clock. See `plans/patterns.md` "Injected clocks" for the reproduction and the clock to test with.
- Steady-state zero allocation per tick. Inside `tick()` / `handle()` / `check()` / any parser inner loop, allocation delta over 1000 ticks ≤ 64 bytes.  Verify with `gc.mem_alloc()` bracketed by `gc.disable()` ([audit-embedded §10](.github/skills/audit-embedded/SKILL.md)). Named offenders with rewrites:
  - f-strings / `.format()` (each allocates a new `str`) → `log.info("...%d...", n)` with logger-side interpolation, or guard with `if log.is_enabled(INFO):`
  - dict / list / tuple / set literals inside the loop → reuse a module-level constant or a cleared scratch container
  - `bytes(view[a:b])` to feed `struct.unpack` → `struct.unpack_from(fmt, buf, offset)`
  - `bytes(view).decode("utf-8")` → `str(view, "utf-8")` (the 3-arg constructor accepts buffer-protocol objects, skips the intermediate `bytes` copy)
  - `int.from_bytes(bytes(buffer[a:b]), ...)` → drop the `bytes()` wrapper, `int.from_bytes` accepts any buffer-protocol object directly
  - `enumerate` / `zip` / `reversed` in a hot loop (each allocates an iterator) → index by hand or restructure
  - `self.x.y.z.method()` chains used twice or more → cache to a local before the loop
  F-strings outside hot paths are fine.
- `gc.collect()`: forbidden in hot paths, required at end of `__init__.py` with substantial import-time state, recommended before returning from a method that handled a large blob. Large-blob: `del` the locals and call `gc.collect()` before returning.  Natural method-exit cleanup is too slow for large allocations; immediate collection reduces fragmentation + RAM pressure. Module-init: parsers / decoders, multi-class setups, runtime-specific adapter loads, module-scope `const()` tables earn it; tiny single-purpose libs don't. Mechanism + measured evidence: [Decision 0084](plans/decisions/0084-gc-collect-policy.md).
- `gc` is stdlib on every runtime.  `import gc` at module top and reuse it throughout the file. No alias-and-`del` dance: `gc` is sys.modules-resident either way, the deletion reclaims nothing, and any consumer can `import gc` directly.
- Sender-controlled allocations are heap-DoS surface. Any `bytearray(N)` / `bytes(N)` in inbound-parse code where `N` comes from a peer-controlled field (MQTT remaining-length varlen, HTTP `Content-Length`, WebSocket frame length) must either bound `N` at a documented cap-knob (`max_message_bytes`, `max_body_bytes`, `max_frame_bytes`) and refuse / drop above it, or use a pre-allocated steady-state buffer as a rolling sink. Comments claiming "heap-safety" do not substitute for a real bound.
- Changes touching I/O, hot paths, or runtime-specific behavior require real-board verification before "done." Unit-test green is necessary but not sufficient: deploy to the hardware tier the library targets (Pico W at minimum for the 256 KB cross-runtime contract), run a one-minute REPL tail under representative load, confirm no tracebacks / safe-mode banners / silent stalls. `chumicro-workspace deploy-example` or `chumicro-workspace deploy <project> --tail <seconds>` is the path; `chumicro-workspace repl --tail <seconds>` tails a board without redeploying. Audit passes touching hot paths default to this check; ADR-driven changes name the validation in the commit message.
- Always use constructor injection for time, I/O, and network dependencies. Fakes go in the library's `testing.py` submodule.
- Constructor-injected substrate stays runtime-optional. Declare the substrate (`chumicro-sockets`, `chumicro-timing`) in `pyproject.toml` `dependencies` but keep `src/<name>/` free of top-level `import chumicro_<substrate>`: keeps it off the deploy bundle and out of RAM for BYOS consumers. Duplicate trivial helpers per consumer rather than consuming a sibling library for them; hoisting helpers into a shared substrate to "share" them is the trap. Grep pre-edit `src/` for top-level `chumicro_<X>` imports before adding one.  Zero + declared dep means intentional optionality.
- Always use absolute imports in code written in the `libraries/` folder. Relative imports break CircuitPython RAM-mode deploys. Workbench and `scripts/` folders may use either. Enforced by ruff TID252.
- Always use PEP 604 / 585 syntax (`int | None`, `list[int]`) in library code. Never import `typing` and never write `from __future__ import annotations` in library code. MicroPython has no `__future__`. CPython-only trees may keep it.
- Always mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`). Test-support modules (`testing.py` fakes) declare `__chumicro_test_support__ = True` and no runtime marker.
- Always use f-strings. Always use `const()`, `memoryview`, and pre-allocated buffers in library code only.
- Never use `__slots__` in `libraries/`. MicroPython and CircuitPython have no `__slots__` implementation.
- Never write a pure-passthrough `@property` in `libraries/`. Properties that compute or transform values stay legitimate. Workbench packages are out of scope.
- Always use descriptive names. Never use single-letter variables except `_`. Always expand abbreviations to full words. For example, write `environment` rather than `env`, `buffer` rather than `buf`, `source` rather than `src`, `command` rather than `cmd`, `message` rather than `msg`, `error` rather than `err`, `reference` rather than `ref`, `address` rather than `addr`, `exception` rather than `exc`, and `execute` rather than `exec`. The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`. Suppress only when matching an upstream API.
- Always minimize dependencies. Always prefer pure-Python implementations compatible with all three runtimes.
- Library examples (`libraries/<name>/examples/`) import from the public package only.  No `from chumicro_<name>._private import …`. No `if __name__ == "__main__":` guard. Hardware examples are prefixed `circuitpython_*.py` / `micropython_*.py`; simulated examples run on CPython without hardware. Gated by `python scripts/run.py verify-examples --libraries <name>`.
- The rules above apply inside `libraries/` and inside `support/<name>/src/` (cross-runtime by default; same `__chumicro_runtimes__` / `__chumicro_test_support__` marker rules as `libraries/`). They do not apply to `workbench/` or `scripts/` (CPython-only trees).

### Workbench code rules

- Workbench packages never import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Always use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`). Embedding device-side code as raw bytes is fine.  That counts as payload data, not a library import.
- Workbench tools that touch hardware must classify failures. Every host-side tool exposes a closed-set failure-kind enum, classifier, and recovery plans in `<package>.recovery`. CLIs always wrap entry points in coaching loops. A generic `raise Exception` is a UX defect.
- Workbench CLIs and `scripts/run.py` tasks callable by humans and agents must support a non-interactive mode: TTY auto-detected via `sys.stdin.isatty()`, `--non-interactive` override, no prompts/tails when non-interactive, distinct exit codes per failure mode. Inherently-interactive subcommands must document the TTY requirement and exit cleanly without one.

### Code comments

- A code comment opens by naming the concrete thing it describes: the actual function, method, class, or value, never an abstract stand-in like 'the adapter' or 'the algorithm'. Then a plain-words statement of what it does or returns, written for a reader who has not read the code. State the non-obvious why after that, not before.
- A test docstring describes what the asserts actually check, not what the test name aspires to. Causal connectors (`so`, `because`, `therefore`) require real causation observable in the test body; independent checks join with `and` or a comma.
- Never name a private helper's callers in its comment. A helper does not know who calls it. No exceptions.
- Every comment must stand alone for a cold reader of this file. Do not write "see ``module``'s docstring", ":mod:`other` documents the rationale", "follows the pattern in X", or any upstream-repo / sibling-library name. No exceptions.
- Never duplicate rationale prose across modules. When the same rationale applies to more than one module, it is project policy.  Fix AGENTS.md or the relevant ADR and delete every per-module copy. Do not consolidate to one module and cross-reference from the rest.
- A comment documents the why of current code. Nothing else. Do not write history ("previously this did X"), dated incidents ("2026-05-09 ESP32-S2 bake"), removed-code explanations ("we used to also send Ctrl-C, dropped because…"), or workstream pointers ("Step 2 of workbench-deploy-reliability"). History belongs in the commit message. Rationale that outlives a commit belongs in the relevant ADR or workstream file. Applies to docstrings and test-body comments without exception.
- When a comment / docstring / doc disagrees with the code, the code is the source of truth. Fix the prose. Sole exception: when the prose plausibly encodes intent the code lost (a regressed feature, an aspirational claim never implemented), do not silently delete documented behavior.  Stop and ask the user which side is correct.
- Never write a comment to record an audit-pass finding. Per-change justification ("bench-validated -25% allocation", "skips the bytes() copy"), sweep narratives, before/after numbers, and the same comment repeated across many sites go in the commit message body, including "general framing" comments about the pass itself.
- Never trim a degraded comment further. A comment that loses legibility each time it is trimmed is deleted and rewritten from a fresh read of the code.

### Plans-doc brevity

- [`plans/next-up.md`](plans/next-up.md) tracks everything in flight. Always one bullet per item. Never add sub-bullets. Anything bigger always gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. Never add a `## Done` section. Enforced by `CHU011`.
- A `Phase N` / `Slice N` reference in a commit subject must always carry a sentence topic (`Phase 6. Implement circuitpython and micropython transport seams`, not bare `Phase 6`).

## Keeping plans and docs current

A feature that exists only in code is incomplete. Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable. Every unit of work touches them in lockstep:

- Behavior, command, library, config, pattern, or rule changed? Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update any doc your change made wrong, especially this file, ADR bodies, CI workflows, and scaffold templates. A drift class that *can* be deterministically linted must be, not just doc-fixed. A prose-only contract is exactly the drift class that ships wrong. See [Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md).
- Unit of work landed? Remove the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) in the *same* edit. No `## Done` section, `git log` carries history. Items grow only by promotion to [`plans/workstreams/<name>.md`](plans/workstreams/) referenced from the bullet, never by adding sub-bullets. Enforced by `CHU011`.
- Open question resolved? Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands. The file is not session-start reading. Consult on demand when working an area with a known open thread.
- User-specific preferences and per-session context live in the memory system; rules that apply to all contributors live here.

## Common pitfalls

- Don't `pip install -e` manually to fix imports. Run `python scripts/run.py setup`.
- If bare `python` errors `command not found`, the agent shell didn't inherit a `python` alias. Run `source .venv/bin/activate` once, or invoke `.venv/bin/python scripts/run.py …` directly.
- Don't critique an architectural split from docs alone. Read the code on both sides. Docstrings often encode constraints.
- `replace_all` is literal substring substitution. Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
- When editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json`), `cd` to the main checkout first. `sync-ide` from a worktree writes paths that break in main.
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`).  Deploy/transport owns it, and interference defeats its EACCES classifier. Destructive remediation: `chumicro-workspace reset-board --yes`.
- Two CP boards plugged in mount as `/Volumes/CIRCUITPY` + `/Volumes/CIRCUITPY 1`.  That's normal disambiguation, not a wedge. Check `chumicro-workspace devices` first. Parallel deploys to two CP boards race for the mount; run them sequentially.
- A `git rm` or `git add` stages immediately and rides into the next commit, even a later narrowly-scoped one. Before a scoped commit, run `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs.
- Device deploys strip docstrings and comments from every staged `.py` ([Decision 0090](plans/decisions/0090-deploy-strips-docstrings-and-comments.md)). An on-device file is shorter than its repo source and its runtime `__doc__` is empty, so compare against the repo source rather than the board copy, and never rely on `__doc__` in library code.

## Working style

- Grep is for verifying a specific claim, not for replacing the read on judgment tasks. When the deliverable is a judgment (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning. Split the target into smaller sequential passes; do not switch tools. Token cost is not the success metric when the work *is* the read.
- An error message is a symptom, not a root cause.  Capture the next layer of detail before naming the cause. A wrapped exception printed as `type(error).__name__: error` strips the traceback; a host-side `TypeError` can be observing a board-side crash; a USB-CDC drop can itself be the downstream effect of a hard fault. Re-run the smallest failing check with maximal detail (`traceback.print_exc()`, board stdout tail, kernel log) before theorizing.
- Surface tradeoffs early. When multiple reasonable approaches exist, name them. When ambiguity affects correctness, ask. When a simpler approach would work, say so.
- Detect missing content, not just bad content. For judgment tasks (audit, code review, design review, second opinion), draft what the ideal version would say from a fresh read of source first, then compare to the actual. Items present in your draft but absent from the actual are findings, the kind of gap mechanical checks miss because nothing is *wrong* with what's there; what's wrong is what's *not* there.
- Restate interpretation when a user reply is terse and ambiguous. A 3-word answer (*"yes"* / *"option 2"* / *"drop it"*) assumes shared context that may have drifted between turns. When the referent could plausibly mean more than one thing, restate what you think they mean before acting: *"confirming: drop X, not Y?"* One round-trip costs less than acting on the wrong referent. If misinterpretation persists across turns, point the user at [`docs/contributing/working-with-agents.md` § When a session feels off](docs/contributing/working-with-agents.md#when-a-session-feels-off).
- Default to action on reversible local work. File edits, tests, refactors, plans-doc updates: execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action*, not *skip the destructive-op check*.
- A named successor is a directive, not an off-ramp. When a skill or doc points at another step as the owner of what comes next, follow the pointer. Words like *"defer"*, *"later"*, *"elsewhere"* describe where to go, not that you're done. The same applies to a multi-item plan named in the conversation.  Finishing item N and asking "want me to do N+1 or wrap here" is an off-ramp dressed as a choice. Continue unless the conditions that justified N+1 changed.
- Subagents default to `model: "opus"`. When invoking the Agent tool for research, audit, or judgment tasks (Explore, general-purpose, audit-*), pass `model: "opus"` explicitly.  Subagents inherit the session model unless overridden, so an explicit pin keeps research and judgment depth independent of the session's model and of a `CLAUDE_CODE_SUBAGENT_MODEL` override; quality dominates token cost in this repo. Sonnet is fine for quick targeted lookups where speed beats depth.
- Same writing checks for user-facing responses. The concise / direct / concrete / professional checks from [Writing tone](#writing-tone) apply to your replies and status updates, not only to prose written into files. Read aloud before sending; if you wouldn't say it that way to a colleague, rewrite.
- Quality bar. Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Read each sentence aloud the way you'd say it to a colleague. If you wouldn't say it that way to a person, rewrite it. The test is the gate; the list below is what to listen for. Lint-backed rules (`Enforced by CHU…`) are absolute; everything else answers to the ear.

Four checks per sentence:

- Concise. Cut connectors that just restate what structure already implies.
- Direct. Lead with the load-bearing fact, not stage-setting.
- Concrete. Name actual classes, functions, files. Avoid abstract stand-ins (*shape*, *surface*, *the algorithm*, *the implementation*) when a specific name exists. "Shape" usually has a concrete swap: `layout` (files), `structure` (organization), `behavior` (semantics), `pattern` (reusable approach), `type` (category). "X-shaped" compounds are usually fat to cut.
- Professional. No colloquialisms (*feeds through*, *wires up*, *punts to*, *hooks into*). No implicit objects (*the caller is about to route*, route what?). No ambiguous pronouns.

Failures to listen for:

- Abstract subject + weak verb + coined noun. *"The win is..."* / *"its floor is..."* / *"the WFI-idle that `ipoll` gives"*.  Find the real actor and let it act. No regex catches this; it's a per-sentence judgment pass. Worked cases: [agent-style-guide.md § Concrete subject, real verb](docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule).
- Suspects to listen for. Em-dashes, semicolons, arrows, AI-tic framings (*"the X promise"*, *"the X pattern"*), empty adjectives (`comprehensive`, `robust`, `seamlessly`, `cutting-edge`, `best-in-class`), filler openers (*"It is worth noting"*, *"Let's dive into"*, *"In this section we will"*). Empty adjectives almost always fail (replace with what something covers or survives); the rest are case-by-case.
- Verify domain terminology before promoting a code identifier into authoritative prose.  `addCommand` does not make what's added a "command" in the domain sense; engineer names drift, check sibling code or ask.
- Article tics. The forward-reference test: `the X` requires X to be an established referent the reader already has.  For a forward reference or a category, use `a X` or bare X (`a code fence`, not `the code fence`, unless one was just introduced). Three secondary tics: `the` before brand names is usually wrong (`Pi Pico W`, not `the Pi Pico W`); `X is the one that Y` is wordier than `X does Y`; `the X of the Y of the Z` chains usually have one too many. Two nouns in one sentence often need different articles.  `the` is not the default. Apply per-noun in every sentence of a rewrite; inherited `the`s compound.
- Abstract opener + concrete restatement is throat-clearing, whatever glue joins them (an em-dash, a colon, a comma splice). *"The config is declarative: list your devices in YAML"* should be *"List your devices in `devices.yml`."* Ask whether the opener clause survives deletion.  It usually should.
- Paraphrasing keeps filler. When rewriting prose with AI-tic words, audit the net delta on flagged words.  `canonical` should drop, not survive paraphrased.
- Degraded prose is rewritten, not trimmed again. A passage rotted by repeated subtractive edits doesn't get fixed by removing another word. Discard, then rewrite from a fresh read of what the thing is and why it exists, with a concrete subject doing something. Applied by [`audit-comments`](.github/skills/audit-comments/SKILL.md), [`audit-docs`](.github/skills/audit-docs/SKILL.md), [`audit-skill`](.github/skills/audit-skill/SKILL.md), and the in-place-edit rule in [`plans/decisions/README.md`](plans/decisions/README.md).

Standing AI-tic regex, consumed by `/audit-docs`, `/audit-comments`, `/audit-skill`:

```bash
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|harness|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

A hit is a candidate, not a verdict. A swap that produces a worse sentence is a regression.  Read the rewrite aloud before accepting it.

Full reference (per-noun `the X` article test, full phrase-ban subsections, CHU-codes-in-prose lint): [docs/contributing/agent-style-guide.md](docs/contributing/agent-style-guide.md).

## Project overview

Family of cross-runtime Python libraries for embedded boards.

- CircuitPython + MicroPython are deployment runtimes (the boards).
- CPython is desktop development, testing, fakes, workbench tooling. Host-test seam, not a deployment target.

If a third-party library doesn't support CircuitPython or MicroPython, prefer a pure-Python alternative.

Minimum board class: 256 KB MCU RAM, 2 MB physical / ~800 KB usable flash. Tier detail in [Decision 0015](plans/decisions/0015-board-architecture-support.md).

## Workspace layout

| Tree | Purpose | Ships to |
|------|---------|----------|
| [`libraries/<name>/`](libraries/) | Cross-runtime device libraries | PyPI · `circup` · `mip` |
| [`workbench/<name>/`](workbench/) | Host-only laptop tools (CPython) | PyPI |
| [`support/<name>/`](support/) | Host-only shared packages, kept out of the device bundle | PyPI, once the package carries a `VERSION` file ([Decision 0111](plans/decisions/0111-workspace-acquisition-coherence.md)) |
| [`demos/<name>/`](demos/) | End-to-end multi-library showcases (host driver + device app) | Not published |
| [`scripts/`](scripts/) | Mono-repo dev tooling | Not published |
| [`plans/`](plans/) | Decisions, work queue, workstreams | Not published |
| [`docs/`](docs/) | Contributor + user docs | Published as the docs site |

When a library doesn't already exist for a job, check `plans/decisions/` for `00NN-chumicro-<name>.md` files, libraries designed but not yet built.

Per-library inventory + dependency graph: [`libraries/README.md`](libraries/README.md). Workbench tools: [`workbench/README.md`](workbench/README.md). Demos: [`demos/README.md`](demos/README.md).

## Commands

Activate any virtual environment first.

- Steady-state refresh: `python scripts/run.py setup` (reinstall deps, regenerate IDE configs).
- First-clone bootstrap: `python scripts/prepare_workspace.py` (creates `.venv`, installs deps, self-re-execs into the new venv).

### `python scripts/run.py <cmd>`: CI-mirror runner

Core commands for active development and troubleshooting:

| Command | Purpose |
|---------|---------|
| `setup` | Install deps + regenerate IDE configs |
| `preflight --coverage-threshold 94` | Full CI mirror. `--with-functional` adds hardware-gated tests; `--with-device-unit` appends the on-device sweep |
| `test --coverage-threshold 94` | CPython unit tests (changed packages by default; `--all` for full sweep) |
| `lint` | Ruff across the workspace |
| `test-all-runtimes` | CPython + MicroPython + CircuitPython unit tests (parallelized) |
| `check-api` / `check-version` | Diff public API surface, confirm VERSION bump level matches |
| `verify-examples` | Statically check each library's `examples/` for valid syntax and resolvable imports under CPython, no execution (`--libraries <name>` or all) |
| `new-library` | Scaffold a new device library (`--workbench` for a host-only tool) + regenerate IDE configs |
| `sync-ide` | Regenerate IDE configs |

`python scripts/run.py --help` lists every flag and the full command set.

`run.py` holds the argument parser and the dispatch table only.  Each task body lives in a [`scripts/run_tasks/`](scripts/run_tasks/) module (`preflight.py`, `checks.py`, `functional.py`, `testing_cpython.py`, `testing_crossruntime.py`, `docs_build.py`, `env_scaffold.py`, `bench.py`), so edit the task there.

### Workbench CLIs

| CLI | What it's for | When to reach |
|---|---|---|
| `chumicro-workspace` | Project deploys, `devices.yml` management, firmware install/upgrade, scaffolding, workspace health | Default front door for anything project-level or workspace-level.  Most agent work routes here |
| `chumicro-deploy` | Low-level transports: probe a board, flash firmware, raw file-push by directory or file-map | Non-project file trees staged by hand, or firmware flashing outside a workspace context |
| `chumicro-repl` | Interactive serial REPL with traceback highlighting and `--tail` follow mode | Driving a board interactively, watching deploy output, post-deploy smoke check |

Common `chumicro-workspace` subcommands (full list: `chumicro-workspace --help`):

| Subcommand | What it does |
|---|---|
| `deploy [<name>]` | Push a project to a board. Auto-detects boot-shim + import-graph for `app.py` + `run()` projects |
| `deploy-example` | Push a `libraries/<lib>/examples/<name>.py` example to a registered device |
| `demo` | Push a built-in sample to the active device, a quick cross-runtime smoke test (~5s) |
| `add-device` | Probe a board and register it in `devices.yml` |
| `devices` | List every entry in `devices.yml` |
| `probe` | Print the runtime identity reported by the selected board |
| `status` / `doctor` | Workspace health snapshot; `doctor` adds Python-version + `run()` AST checks |
| `reset-board --yes` | Destructive: wipe and re-prep a board |

Each subcommand's `--help` shows its flags. The CLI rejects wrong runtime / project-type combinations with actionable error messages.

## Reference implementations

Pinned local clones of runtime source trees live under `.tools/` (gitignored). Browse these first when inspecting C implementations or built-in module behavior.

```
python scripts/run.py prepare-micropython
python scripts/run.py prepare-circuitpython
```

## Deeper docs (pointer-only)

For deeper implementation detail:

- [plans/patterns.md](plans/patterns.md): implementation cookbooks. Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, and more.
- [docs/contributing/agent-style-guide.md](docs/contributing/agent-style-guide.md): per-phrase subsections with worked before/after, the per-noun `the X` article test, CHU-codes-in-prose lint (`CHU006`).
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md): naming, annotations, imports, layout, doc tone.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md): functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md) covers VERSION, SemVer, and experimental-to-stable promotion.
- CHU lint rules: the live index is [`workbench/checks/src/chumicro_checks/rules/`](workbench/checks/src/chumicro_checks/rules/).  One module per rule family: usually a single `CHU0NN` code, sometimes a related set (`chu002to005_018.py`, `chu009_chu010.py`).  Each docstring describes what its rules flag.  [Decision 0060](plans/decisions/0060-chu-rules-home.md) records why the rules live there.
- [docs/troubleshooting/](docs/troubleshooting/): hardware-issue recovery (FSKit wedge, read-only FAT, RingIO quirks).
