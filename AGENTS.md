# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

## Non-negotiable rules

**Workflow**

- Preflight must pass before commit. If preflight is already red on `main` (not from your changes), surface and stop.
- End-of-work invokes the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill. It owns preflight, `plans/next-up.md` refresh, durable-lesson lift, commit, and push. Don't yield with uncommitted changes or untested behavior unless the work is explicitly partial, and say so.
- Anchor claims to evidence (file, symbol, test, or command). Don't fabricate. Verify by reading code, running tests, or checking command output. Training recall is not verification. For anything time-sensitive, version-specific, or newer than the model cutoff, web-search rather than asserting from memory.
- Verify sub-agent (Explore / audit-* / general-purpose) concrete claims before relaying. Grep or read the referenced files. Reports describe intent, not state.
- Don't modify unrelated code when fixing a focused bug. Mention pre-existing issues separately.
- Don't add features, abstractions, or speculative error handling beyond what was asked. Removing unnecessary complexity from code you're already touching is fine.
- Clean up after yourself. If you make an import, variable, function, or test unused, remove it. If your change affects docs, update them. Do not fix pre-existing issues unless asked.
- Re-verify state after recovery actions. When a fix depends on the user running a recovery action (replug, reset-board, unwedge), re-run the failing detection and the smallest failing test before committing. "Done" from the user is the signal to verify, not proof the fix worked.
- While the repo is private, commit directly to `main`. No feature branches, no PRs.
- Pass the commit message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`) so backticks, `$`, parens, and newlines pass literally. Read the [`git-commit`](.github/skills/git-commit/SKILL.md) skill before every commit.
- `.scratch/` is gitignored. Use this folder for temp files and log captures.
- Pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Disable pagers (`git --no-pager`, `| cat`).
- Use file tools to write or edit files, never heredocs, `echo`, `printf`, or `cat` for file content (the heredoc rule above is commit messages only).
- No backwards-compatibility burden until 1.0. Do not deprecate or provide legacy support.
- Don't hard-code or commit secrets. Wifi passwords, MQTT credentials, API tokens belong only in the gitignored `secrets.toml`.
- Pair lint suppressions with a brief explanation why so a reviewer can verify.
- Before writing implementation code in `libraries/` or `workbench/`, skim [`plans/patterns.md`](plans/patterns.md) for an established shape.
- Before creating or editing a file under `plans/decisions/`, read [`plans/decisions/README.md`](plans/decisions/README.md). New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill — invoke it, don't freehand. ADRs preserve **invariant and reasoning**, not mechanism. Class signatures, per-runtime substrate tables, state-machine migrations, phase plans, migration rosters, future-work checklists, and bake-validation logs do not belong in an ADR — they go to [`plans/workstreams/<name>.md`](plans/workstreams/) (see Decision 0081's slim-down at commit `4769706e` for a worked case). Equivalently: a decision, a rejected alternative, or a structural rule sitting inside a workstream belongs in `plans/decisions/`. The principle goes in the ADR; the mechanism goes in the workstream.
- A `plans/workstreams/<name>.md` file you're picking up is a **directive, not a research artifact**. Execute the next unshipped phase from its `## Implementation phases` / `## Plan` section. Don't pause to ask "should we still do this?" — when something looks like it may have changed, verify the specific claim (read the code it points at, run the failing test, check the cited commit), then proceed. As phases land, append one line per phase to the workstream's `## Validation history` section so the next agent doesn't redo work, and update the `Status:` line (`shipped`, `parked`, `superseded`) when the workstream is fully done. Pausing without a concrete blocker is the failure mode this rule exists to stop.
- When you don't know a subcommand or flag on `python scripts/run.py`, `chumicro-workspace`, `chumicro-deploy`, or `chumicro-repl`, run the tool (and each subcommand) with `--help` before asking the user or giving up. The full subcommand inventory is discoverable. Treating a workbench tool or `scripts/run.py` as opaque is a process failure.
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython).

**Testing**

- Maintain coverage gates. Every `test` and `preflight` invocation must pass `--coverage-threshold 94`.
- Test skips must be loud. Do not write a test with no assertions or validation. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- Cross-runtime test files must not `import pytest`. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under both CircuitPython and MicroPython. A PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems.

**Code shape (libraries, microcontroller only)**

- Do not use `async` / `await` and ISRs. Use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped: no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)` in a leaf service, no synchronous TCP connect or TLS handshake from a library method that callers may invoke inside a runner-tick handler ([Decision 0081](plans/decisions/0081-non-blocking-connect-via-tick-driven-connector.md) — use `chumicro_sockets`'s tick-driven connector). The runner's one central wait (`Runner.wait`) may block to the next deadline — that is the loop idling, not a service stalling it ([Decision 0080](plans/decisions/0080-runner-reactor.md)).
- All time math goes through `chumicro_timing` — `ticks_ms()`, `ticks_diff()`, `ticks_add()`, `Heartbeat`. This applies to `libraries/` source **and** to tests (in any package) that gate on deadlines or elapsed time. Never call `time.monotonic()`, `time.ticks_ms()`, or `supervisor.ticks_ms()` directly. `chumicro_timing` exists to unify three runtime time domains into one; bypassing it produces the two-time-domain trap where a `runner.tick()` deadline computed in `chumicro_timing` ticks is compared against a `time.monotonic()` wall clock, and the resulting "freeze" / "hang" looks like a stalled service while really being mismatched units. A single 6-hour misdiagnosed-freeze session is the recorded cost. Exception: `chumicro_timing`'s own tests, when they exercise the resolution mechanism itself.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule.
- Absolute imports only in code written in the `libraries/` folder. Relative imports break CircuitPython RAM-mode deploys. Workbench and scripts folder may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code. MicroPython has no `__future__`. CPython-only trees may keep it.
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`). Test-support modules (`testing.py` fakes) declare `__chumicro_test_support__ = True` and no runtime marker.
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- No `__slots__` in `libraries/`. MP/CP have no `__slots__` implementation.
- No pure-passthrough `@property` in `libraries/`. Properties that compute or transform values stay legitimate. Workbench packages are out of scope.
- Use descriptive names. No single-letter variables except `_`. Expand abbreviations to full words. For example, write `environment` rather than `env`, `buffer` rather than `buf`, `source` rather than `src`, `command` rather than `cmd`, `message` rather than `msg`, `error` rather than `err`, `reference` rather than `ref`, `address` rather than `addr`, `exception` rather than `exc`, and `execute` rather than `exec`. The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`. Suppress only when matching an upstream API.
- Minimize dependencies. Prefer pure-Python implementations compatible with all three runtimes.
- The rules above apply only inside `libraries/`. Do not apply them to `workbench/` or `scripts/`.

**Code shape (workbench, cpython only)**

- Workbench packages do not import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`). Embedding device-side code as raw bytes is fine. That counts as payload data, not a library import.
- Workbench tools that touch hardware must classify failures. Every host-side tool exposes a closed-set failure-kind enum, classifier, and recovery plans in `<package>.recovery`. CLIs wrap entry points in coaching loops. Generic `raise Exception` is a UX defect.
- Workbench CLIs and `scripts/run.py` tasks callable by humans and agents support a non-interactive mode: TTY auto-detected via `sys.stdin.isatty()`, `--non-interactive` override, no prompts/tails when non-interactive, distinct exit codes per failure mode. Inherently-interactive subcommands document the TTY requirement and exit cleanly without one.
- Code reaches a board only through `chumicro-deploy`, which uses a diff plus `rsync --delete`.

**Code comments**

- A code comment first states, in plain words, what the function, method, or class does or returns, written so a reader who has not read the code is oriented. Then state the non-obvious why.
- A private helper's comment must not name its callers. The helper has no business knowing them.
- A comment must not point outside this code's world: no "mirrors the reference impl", no upstream-repo / sibling-project names.
- A comment documents the why of current code, nothing else. No history ("previously this did X"), no dated incidents ("2026-05-09 ESP32-S2 bake"), no removed-code explanations ("we used to also send Ctrl-C, dropped because…"), no workstream pointers ("Step 2 of workbench-deploy-reliability"). Defer to the commit message instead, or update the relevant ADR or workstream file. Applies to docstrings and test-body comments too.
- Audit-pass commits may add general "what this work is doing" framing, but never per-change justification ("bench-validated -25% allocation", "skips the bytes() copy") and never the same comment repeated across many sites. Per-change rationale goes in the commit message body.
- A comment so degraded that trimming it again only makes it less legible gets rewritten from a fresh read of the code, not subtracted further.

**Plans-doc brevity**

- [`plans/next-up.md`](plans/next-up.md) tracks everything in flight. One bullet per item, no sub-bullets. Anything bigger gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. No `## Done` section. Enforced by `CHU011`.
- `Phase N` / `Slice N` references in commit subjects must carry a sentence topic (`Phase 6. Implement circuitpython and micropython transport seams`, not bare `Phase 6`).

## Keeping plans and docs current

**A feature that exists only in code is incomplete.** Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable. Every unit of work touches them in lockstep:

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update any doc your change made wrong, especially this file, ADR bodies, CI workflows, and scaffold templates. A drift class that *can* be deterministically linted must be, not just doc-fixed. A prose-only contract is exactly the drift class that ships wrong. See [Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md).
- **Unit of work landed?** Remove the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) in the *same* edit. No `## Done` section, `git log` carries history. Items grow only by promotion to [`plans/workstreams/<name>.md`](plans/workstreams/) referenced from the bullet, never by adding sub-bullets. Enforced by `CHU011`.
- **Open question resolved?** Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands. The file is not session-start reading. Consult on demand when working an area with a known open thread.
- **Adding or changing an ADR?** See [`plans/decisions/README.md`](plans/decisions/README.md) for the rules (in-place edits, in-place correction of wrong reasoning, state the principle not the mechanism). New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill.
- **End of every unit of work.** Run the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill. It verifies preflight is green, plans-doc is updated, and docs are in sync, then commits and pushes. Don't yield with uncommitted changes or untested behavior unless the work is explicitly partial, and say so.

## Common pitfalls

- Don't `pip install -e` manually to fix imports. Run `python scripts/run.py setup`.
- If bare `python` errors `command not found`, the agent shell didn't inherit a `python` alias. Run `source .venv/bin/activate` once, or invoke `.venv/bin/python scripts/run.py …` directly.
- Don't critique an architectural split from docs alone. Read the code on both sides. Docstrings often encode constraints.
- `replace_all` is literal substring substitution. Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
- When editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json`), `cd` to the main checkout first. `sync-ide` from a worktree writes paths that break in main.
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`). The deploy/transport code owns mount state, and manual interference defeats its mount probing + EACCES classifier (a macOS FSKit wedge can leave the volume unmountable). Destructive remediation: `chumicro-workspace reset-board --yes`.
- A `git rm` or `git add` stages immediately and rides into the next commit, even a later narrowly-scoped one. Before a scoped commit, run `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs. A pre-staged `mqtt/test_client.py` deletion once rode into an unrelated `http_server` split. Main carried a deleted-but-not-replaced suite for one commit, which cost a fixup and a broken-main window.

## Working style

- **Grep is for verifying a specific claim, not for replacing the read on judgment tasks.** When the deliverable is a judgment that requires holding context (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning. Split the target into smaller sequential passes. Do not switch tools. Token cost is not the success metric when the work *is* the read. Grep is the right primary tool when the deliverable is *finding* something specific, like callers of X or occurrences of a pattern. It is the wrong primary tool when the deliverable is *judging* prose, structure, or design.
- **Surface tradeoffs early.** When multiple reasonable approaches exist, name them. When ambiguity affects correctness, ask. When a simpler approach would work, say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates: execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action*, not *skip the destructive-op check*.
- **A named successor is a directive, not an off-ramp.** When a skill or doc points at another step as the owner of what comes next, follow the pointer. Words like *"defer"*, *"later"*, *"elsewhere"* describe where to go, not that you're done.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Aim for prose that reads aloud like one colleague explaining something to another. Four checks per sentence:

- **Concise.** Cut connectors that just restate what structure already implies.
- **Direct.** Lead with the load-bearing fact. Skip stage-setting ("in this section we will", "it is worth noting that").
- **Concrete.** Name actual classes, functions, files, identifiers. Avoid abstract stand-ins like *shape*, *surface*, *the algorithm*, *the implementation* when a specific name exists.
- **Professional.** No colloquialisms (*feeds through*, *wires up*, *punts to*, *hooks into*). No implicit objects (*the caller is about to route* — route what?). No ambiguous pronouns.

One structural fault no regex catches: an abstraction in the subject slot ("the win is", "its floor is") joined by a weak verb (is, gives, provides) to a coined noun that hides an action ("the WFI-idle that `ipoll` gives"). Find the real actor and let it act, as in "a connected board idles the CPU between events, which is what `ipoll` does." The test: read each sentence the way you'd say it out loud to a colleague. If you would not say it that way to a person, rewrite it. Worked cases in [agent-style-guide.md](docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule).

Verify domain terminology before using it as if authoritative. Code identifiers are not canonical domain vocabulary — a method named `addCommand` does not make what's added a "command" in the domain sense. Engineers name things for code-local convenience and the names drift. Check sibling code, prior usage, or ask before promoting an engineer-named identifier into prose.

Em-dashes, semicolons, and arrows are suspects, not bans. They often paper over missing connective tissue, in which case two sentences or a comma-and-connector reads better. When the connective tissue is there and the sentence reads well out loud, keep them.

AI-tic phrases are suspects too. They sound non-human, drop information, make prose harder to skim. When you reach for "the X promise" or "the X pattern", either name X concretely in the same sentence or rephrase.

Other shapes to listen for, all subject to the read-aloud test (keep when it reads fine):

- "The canonical X", "the one / single / sole X that…" as openers. Say what X is or does directly.
- Empty adjectives (`comprehensive`, `robust`, `seamlessly`, `cutting-edge`, `best-in-class`). Name what something covers or what it survives.
- Filler sentence-openers ("It is worth noting that", "Let's dive into", "In this section, we will"). Start with the content.

Full reference, including the `the X` forward-reference test, the CHU-codes-in-prose lint, and the rewrite-don't-trim discipline the audit skills apply, lives in [docs/contributing/agent-style-guide.md](docs/contributing/agent-style-guide.md).

## Project overview

Family of cross-runtime Python libraries for embedded boards.

- **CircuitPython** + **MicroPython** are deployment runtimes (the boards).
- **CPython** is desktop development, testing, fakes, workbench tooling. Host-test seam, not a deployment target.

If a third-party library doesn't support CircuitPython or MicroPython, prefer a pure-Python alternative.

**Minimum board class:** 256 KB MCU RAM, 4 MB flash. Tier detail in [Decision 0015](plans/decisions/0015-board-architecture-support.md).

## Workspace layout

| Tree | Purpose | Ships to |
|------|---------|----------|
| [`libraries/<name>/`](libraries/) | Cross-runtime device libraries | PyPI · `circup` · `mip` |
| [`workbench/<name>/`](workbench/) | Host-only laptop tools (CPython) | PyPI |
| [`support/<name>/`](support/) | Internal shared packages | Not published |
| [`scripts/`](scripts/) | Mono-repo dev tooling | Not published |
| [`plans/`](plans/) | Decisions, work queue, workstreams | Not published |
| [`docs/`](docs/) | Contributor + user docs | Published as the docs site |

See [`libraries/README.md`](libraries/README.md) and [`workbench/README.md`](workbench/README.md) for the live inventory and per-package summaries.

When a library doesn't already exist for a job, check `plans/decisions/` for a planned design.  Look for `00NN-chumicro-<name>.md` files, which name libraries that have been designed but not yet built.

## Commands

Activate any virtual environment first. If one isn't installed yet, run `python scripts/prepare_workspace.py` to bootstrap.

### `python scripts/run.py <cmd>`: CI-mirror runner

Core commands for active development and troubleshooting:

| Command | Purpose |
|---------|---------|
| `setup` | Install deps + regenerate IDE configs |
| `preflight` | Full CI mirror (lint + build + docs + all-runtime unit tests + checks). `--with-functional` adds hardware-gated tests; `--with-device-unit` appends the on-device sweep |
| `test` | CPython unit tests (changed packages by default; `--all` for full sweep) |
| `lint` | Ruff across the workspace |
| `test-all-runtimes` | CPython + MicroPython + CircuitPython unit tests (parallelized) |
| `new-library` | Scaffold a new device library (`--workbench` for a host-only tool) + regenerate IDE configs |
| `sync-ide` | Regenerate IDE configs |

`python scripts/run.py --help` lists every flag and the full command set.

### Workbench CLIs

`chumicro-workspace`, `chumicro-deploy`, and `chumicro-repl` are invocable directly from the mono-repo.  See [`workbench/README.md`](workbench/README.md) and each tool's `--help` for the live subcommand inventory.

## Reference implementations

Pinned local clones of runtime source trees live under `.tools/` (gitignored). Browse these first when inspecting C implementations or built-in module behavior.

```
python scripts/run.py prepare-micropython
python scripts/run.py prepare-circuitpython
```

## Deeper docs (pointer-only)

For deeper implementation detail:

- [plans/patterns.md](plans/patterns.md): implementation cookbooks. Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, and more.
- [docs/contributing/agent-style-guide.md](docs/contributing/agent-style-guide.md): full phrase bans, the `the X` forward-reference test, the rewrite-not-trim discipline.
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md): naming, annotations, imports, layout, doc tone.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md): functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md) covers VERSION, SemVer, and experimental-to-stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md): PR conventions.
- [docs/troubleshooting/](docs/troubleshooting/): hardware-issue recovery (FSKit wedge, read-only FAT, RingIO quirks).
