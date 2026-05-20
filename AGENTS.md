# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

## Session start

Every session, in this order:

1. `git --no-pager log --oneline -10` to see what just shipped.
2. Read [`plans/next-up.md`](plans/next-up.md) for the current open work items.
3. Read the ADR file name (slugs) at `ls plans/decisions/`.

Commit history is the primary fallback when planning docs are stale. Write commit messages that aid future context recovery.

## Non-negotiable rules

**Workflow**

- Preflight must pass before commit. If preflight is already red on `main` (not from your changes), surface and stop.
- While the repo is private, commit directly to `main`. No feature branches, no PRs.
- Pass the commit message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`) so backticks, `$`, parens, and newlines pass literally. Read the [`git-commit`](.github/skills/git-commit/SKILL.md) skill before every commit.
- `.scratch/` is gitignored. Use this folder for temp files and log captures.
- Pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Disable pagers (`git --no-pager`, `| cat`).
- Use file tools to write or edit files, never heredocs, `echo`, `printf`, or `cat` for file content (the heredoc rule above is commit messages only).
- No backwards-compatibility burden until 1.0. Do not deprecate or provide legacy support.
- Don't hard-code or commit secrets. Wifi passwords, MQTT credentials, API tokens belong only in the gitignored `secrets.toml`.
- Pair lint suppressions with a brief explanation why so a reviewer can verify.
- Before writing implementation code in `libraries/` or `workbench/`, skim [`plans/patterns.md`](plans/patterns.md) for an established shape.

**Testing**

- Maintain coverage gates. Every `test` and `preflight` invocation must pass `--coverage-threshold 94`.
- Test skips must be loud. Do not write a test with no assertions or validation. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- Cross-runtime test files must not `import pytest`. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under both CircuitPython and MicroPython. A PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems.

**Code shape (libraries — runs on a microcontroller)**

- Do not use `async` / `await` and ISRs. Use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped: no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule.
- Absolute imports only in code written in the `libraries/` folder. Relative imports break CircuitPython RAM-mode deploys. Workbench and scripts folder may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code. MicroPython has no `__future__`. CPython-only trees may keep it.
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`). Test-support modules (`testing.py` fakes) declare `__chumicro_test_support__ = True` and no runtime marker.
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- No `__slots__` in `libraries/`. MP/CP have no `__slots__` implementation.
- No pure-passthrough `@property` in `libraries/`. Computed non marked up properties (doing actual work) stay legitimate. Workbench packages are out of scope.
- Use descriptive names. No single-letter variables (except `_`); expand abbreviations to full words: `env`→`environment`, `buf`→`buffer`, `src`→`source`, `cmd`→`command`, `msg`→`message`, `err`→`error`, `ref`→`reference`, `addr`→`address`, `exc`→`exception`, `exec`→`execute`. The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`; suppress only when matching an upstream API.
- Minimize dependencies. Prefer pure-Python implementations compatible with all three runtimes.
- Do not apply embedded code shape rules to `workbench/` or `scripts/` folders.

**Code shape (workbench — runs on a laptop)**

- Workbench packages do not import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`). Embedded payload bytes are fine.
- Workbench tools that touch hardware must classify failures. Every host-side tool exposes a closed-set failure-kind enum, classifier, and recovery plans in `<package>.recovery`; CLIs wrap entry points in coaching loops. Generic `raise Exception` is a UX defect.
- Workbench CLIs and `scripts/run.py` tasks callable by humans and agents support a non-interactive mode: TTY auto-detected via `sys.stdin.isatty()`, `--non-interactive` override, no prompts/tails when non-interactive, distinct exit codes per failure mode. Inherently-interactive subcommands document the TTY requirement and exit cleanly without one.
- Code reaches a board only through the deploy stage + diff/`rsync --delete` primitive.

**Code comments**

- A code comment first states, in plain words, what the thing does or returns, written so a reader who has not read the code is oriented, then the non-obvious why.
- A confined helper's comment must not name its callers, it has no business knowing them.
- A comment must not point outside this code's world: no "mirrors the reference impl", no upstream-repo / sibling-project names.
- A comment documents the why of current code, nothing else. No history ("previously this did X"), no dated incidents ("2026-05-09 ESP32-S2 bake"), no removed-code explanations ("we used to also send Ctrl-C, dropped because…"), no workstream pointers ("Step 2 of workbench-deploy-reliability"). Defer to the commit message instead, or update the relevant ADR or workstream file. Applies to docstrings and test-body comments too.
- Audit-pass commits may add general "what this work is doing" framing, but never per-change justification ("bench-validated -25% allocation", "skips the bytes() copy") and never the same comment repeated across many sites. Per-change rationale goes in the commit message body.
- A comment so degraded that trimming it again only makes it less legible gets rewritten from a fresh read of the code, not subtracted further.

**Plans-doc brevity**

- [`plans/next-up.md`](plans/next-up.md) is the single source of truth for what's in flight. One bullet per item, no sub-bullets. Anything bigger gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. No `## Done` section. Enforced by `CHU011`.
- `Phase N` / `Slice N` references in commit subjects must carry a sentence topic (`Phase 6. Implement circuitpython and micropython transport seams`, not bare `Phase 6`).

## Keeping plans and docs current

**A feature that exists only in code is incomplete.** Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable. Every unit of work touches them in lockstep:

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update READMEs, [style guide](docs/contributing/style-guide.md), [cheat sheet](docs/contributing/cheat-sheet.md), CI workflows, scaffold templates, this file, ADR bodies. Whatever your change made wrong. A drift class that *can* be deterministically linted must be, not just doc-fixed. A prose-only contract is exactly the drift class that ships wrong. See [Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md).
- **Unit of work landed?** Remove the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) in the *same* edit. No `## Done` section, `git log` carries history. Items grow only by promotion to [`plans/workstreams/<name>.md`](plans/workstreams/) referenced from the bullet, never by adding sub-bullets. Enforced by `CHU011`.
- **Open question resolved?** Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands. The file is not session-start reading; consult on demand when working an area with a known open thread.
- **Adding or changing an ADR?** See [`plans/decisions/README.md`](plans/decisions/README.md) for the rules (in-place edits, in-place correction of wrong reasoning, state the principle not the mechanism). New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill.
- **End of every unit of work** → run the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill: preflight green, plans-doc updated, docs in sync, commit + push. Don't yield with uncommitted changes or untested behavior unless the work is explicitly partial, and say so.

## Common pitfalls

- Don't `pip install -e` manually to fix imports. Run `python scripts/run.py setup`.
- If bare `python` errors `command not found`, the agent shell didn't inherit a `python` alias. Run `source .venv/bin/activate` once, or invoke `.venv/bin/python scripts/run.py …` directly.
- Don't modify unrelated code when fixing a focused bug. Mention pre-existing issues separately.
- Don't fabricate. Verify by reading code, running tests, or checking command output. Training recall is not verification. For anything time-sensitive, version-specific, or newer than the model cutoff, web-search it rather than asserting from memory.
- Don't add features, abstractions, or speculative error handling beyond what was asked. If 200 lines could be 50, rewrite.
- Don't critique an architectural split from docs alone. Read the code on both sides; docstrings often encode constraints.
- Verify sub-agent (Explore / audit-* / general-purpose) concrete claims before relaying. Grep or read the referenced files. Reports describe intent, not state.
- `replace_all` is literal substring substitution. Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
- Editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json`): `cd` to the main checkout first; `sync-ide` from a worktree writes paths that break in main.
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`). The deploy/transport code owns mount state, and manual interference defeats its mount probing + EACCES classifier (a macOS FSKit wedge can leave the volume unmountable). Destructive remediation: `chumicro-workspace reset-board --yes`.
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython). The runtime re-runs the file every boot, an infinite loop until safe mode (physical replug to recover). Trigger hard reset via raw REPL exec, one-shot, never persisted. The pattern is `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py::_reset_into_bootloader`.
- A `git rm` / `git add` stages immediately and rides into the *next* commit, even a later narrowly-scoped one. Before a scoped commit, `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs. A pre-staged `mqtt/test_client.py` deletion once rode into an unrelated `http_server` split. Main carried a deleted-but-not-replaced suite for one commit; cost a fixup and a broken-main window.

## Working style

- **Anchor claims to evidence:** file, symbol, test, or command. No guessing.
- **Grep is for verifying a specific claim, not for replacing the read on judgment tasks.** When the deliverable is a judgment that requires holding context (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning. Split the target into smaller sequential passes; do not switch tools. Token cost is not the success metric when the work *is* the read. Grep is the right primary tool when the deliverable is *finding* something specific (callers of X, occurrences of a pattern); it is the wrong primary tool when the deliverable is *judging* prose, structure, or design. Worked application for code comments: [`audit-comments`](.github/skills/audit-comments/SKILL.md) "Method discipline: read fully, do not grep-shortcut." Other audit-* skills inherit this rule; `audit-publishable-isolation` is exempt (grep is its right primary tool, cross-repo leak hunting).
- **Surface tradeoffs early.** Multiple reasonable approaches → name them. Ambiguity affects correctness → ask. Simpler approach would work → say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates: execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action*, not *skip the destructive-op check*.
- **Clean up after yourself.** Make an import / variable / function / test unused → remove it. Affect docs → update them. But don't fix pre-existing issues unless asked.
- **Re-verify state after recovery actions.** When a fix depends on the user running a recovery action (replug, reset-board, unwedge), re-run the failing detection and the smallest failing test *before* committing. "Done" from the user is the signal to verify, not proof the fix worked.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Cut AI-tic phrases. They sound non-human, drop information, and make prose harder to skim. The fix is usually structural, not vocabulary. When you write *"the X promise"* or *"the X pattern"*, name X concretely in the same sentence. When you catch yourself writing one, rewrite the sentence to *demonstrate* the property concretely instead of asserting it abstractly.

**Degraded prose is rewritten, not trimmed again.** A passage rotted by repeated subtractive edits (each pass removed a word, none asked *what should this say?*) is not fixed by removing another word. That only makes it shorter and no clearer. Discard it and rewrite from a fresh read of what the thing is and why it exists. This is the *why* of the entire comment/doc-audit family: code comments → [`audit-comments`](.github/skills/audit-comments/SKILL.md), user-facing markdown → [`audit-docs`](.github/skills/audit-docs/SKILL.md), SKILL.md bodies → [`audit-skill`](.github/skills/audit-skill/SKILL.md), ADR bodies → in-place edit per [`plans/decisions/README.md`](plans/decisions/README.md). Those skills carry the scope-specific application; this is the rule they apply.

Specific bans:

- **"the canonical promise" / "the canonical pattern"** → just name the promise or pattern. Bad: *"Verifies the canonical promise: an LED keeps blinking…"* Good: *"Verifies the LED-blink invariant: an LED keeps blinking…"*
- **"the canonical X" generally** → check whether *"the X"* or *"the standard X"* is enough. Keep `canonical encoding`, `canonical form`, `canonical path`; these are real technical terms with no fluff substitute.
- **"the one/single/sole X that …"** as a definition opener → same tic as "the canonical X"; define the thing plainly (*"`run.py` enforces coverage"*, not *"`run.py` is the single mechanism that enforces coverage"*). Applies to comments and docstrings in `src/`, not just prose docs. Tone guidance, not a lint. Legitimate invariant prose (*"the single owner of the staging path"*, Decision 0077's *"exactly one mechanism"*) is correct and stays; this is judgement, not a mechanizable matcher (see the CHU020 entry in [`plans/next-up.md`](plans/next-up.md)).
- **`the X` only when X is a specific established instance** → per-noun forward-reference test for every `the` in prose; the failure mode that compounds across REWRITE passes the way the superlative tic above does. Three-way call: **`the X`** when the reader already has a definite singular referent (established by surrounding code, the prior sentence, or method lifecycle, e.g. *"the open raw-REPL session"* after `_enter_raw_repl` has run); **`a / an X`** when X is a category or a forward reference the reader has not acquired yet (*"send an autoreload-off REPL command"*, one of many commands the call could send, named for the first time); **bare `X`** when X is a system / category / brand name where the article is decoration (*"per-user launchd respawns the agent"*, *"ESP32-S2 USB-CDC firmware"*). Two nouns in one sentence often deserve different choices, e.g. *"Send an autoreload-off REPL command on the open raw-REPL session"*: command is forward-reference (`an`), session is established singular (`the`). "Without it the prose reads telegraphic" is a defense of `the → bare`, never of `the → an/a` (an indefinite article is not clinical); conflating them is how `the`s the rewrite did not earn survive. Tone guidance, not a lint.
- **"comprehensive" / "robust" / "seamlessly" / "cutting-edge" / "best-in-class"** → drop outright. If you'd reach for *"comprehensive"*, list what it covers; for *"robust"*, name what it survives.
- **"It is worth noting that" / "It should be noted that" / "Note that"** (sentence opener) → just say the thing.
- **"Let's dive into" / "Let's explore" / "In this section, we will"** → start with the content.
- **CHU lint codes in prose** in publishable trees → name the rule's intent (*"silent test skips"*). Enforced by `CHU006`, which exempts `# noqa: CHUNNN` directives.

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

The installer's destination decides the folder. Workbench-shipped *payload* (template files written onto a device) lives inside the workbench package, not an installable.

### Libraries

`ls libraries/` is the live inventory; each has a `README.md` and `docs/guide.md`. The dependency stack, broadly:

- **Primitives:** `timing`, `runner`, `compat`, `logging`, `events`. Depended-on-by-everyone.
- **Persistence + serialization:** `msgpack`, `config`, `kvstore`.
- **Networking transport + protocols:** `wifi` (link), `sockets` (TCP/TLS/UDP), then app protocols: `ntp`, `requests`, `http_server`, `websockets`, `mqtt`.

Per-library deps are declared in each `pyproject.toml`. When a library doesn't already exist for a job, check `plans/decisions/` for a chartered design (`00NN-chumicro-<name>.md`).

### Workbench (host-only)

`ls workbench/` is the live inventory. Currently:

- **`deploy`:** push code, probe identity, flash firmware; failure-classifying recovery layer.
- **`repl`:** serial REPL with traceback highlighting and `tail()` follow-mode.
- **`workspace`:** project workspace CLI (composes `deploy` + `repl` + config); starter is the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo.
- **`pytest-device`:** pytest plugin (auto-registered via `pytest11`) that stages source onto a board and runs tests in the device runtime.
- **`checks`:** the `CHU0NN` lint rules (`chumicro-checks`).

## Commands

The mono-repo has workspace shape (`workspace.yml` + `devices.yml` at root), so the workbench CLIs work directly here. `python scripts/run.py setup` editable-installs every package into `.venv/`; activate it or use `.venv/bin/<cli>`. System `python3` won't find `chumicro_*`.

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

### Workbench CLIs, directly invocable from the mono-repo

- **`chumicro-workspace`:** top-level dispatcher: project-workspace lifecycle, device registry, running things on a board, config, firmware, curated libraries, health, and quality gates. Run `chumicro-workspace --help` for the live subcommand list.
- **`chumicro-deploy`:** lower-level transport: `probe`, `flash`, `deploy`, `resolve-firmware-url`. Prefer the `chumicro-workspace` wrappers; reach for this when composing custom flows.
- **`chumicro-repl`:** direct REPL without a workspace project.

`<cli> --help` and `<cli> <sub> --help` for full flag lists. Walkthroughs in [docs/contributing/device-testing.md](docs/contributing/device-testing.md) and [docs/contributing/working-with-agents.md](docs/contributing/working-with-agents.md).

## File routing

| Task | Where |
|------|-------|
| New device library | `python scripts/run.py new-library <name>` |
| New host-only tool | `python scripts/run.py new-library --workbench <name>`; see [docs/contributing/workbench.md](docs/contributing/workbench.md) |
| Shared infra (internal) | `support/` |
| Build / CI tooling | `scripts/` |
| Design decision | `plans/decisions/NNNN-<slug>.md` (use [`new-decision`](.github/skills/new-decision/SKILL.md) skill) |
| Docs assets | `support/docs/` |

## Reference implementations

Pinned local clones of runtime source trees live under `.tools/` (gitignored). Browse these first when inspecting C implementations or built-in module behavior.

```
python scripts/run.py prepare-micropython
python scripts/run.py prepare-circuitpython
```

## Deeper docs (pointer-only)

For deeper implementation detail:

- [plans/patterns.md](plans/patterns.md): implementation cookbooks. Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, and more.
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md): naming, annotations, imports, layout, doc tone.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md): functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md): VERSION, SemVer, experimental → stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md): PR conventions.

Tests live under each library's `tests/`; shared fakes in `src/chumicro_<name>/testing.py`. On-device tests live under `functional_tests/` and use `support/test_harness/`.

Each library's `VERSION` file is the source of truth, bump only affected libraries. Development code stays as plain `.py`; `.mpy` compilation happens in the release pipeline.
