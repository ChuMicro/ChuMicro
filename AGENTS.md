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
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython). The runtime re-runs the file every boot, an infinite loop until safe mode (physical replug to recover). Trigger hard reset via raw REPL exec, one-shot, never persisted. The pattern is `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py::_reset_into_bootloader`.

**Testing**

- Maintain coverage gates. Every `test` and `preflight` invocation must pass `--coverage-threshold 94`.
- Test skips must be loud. Do not write a test with no assertions or validation. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- Cross-runtime test files must not `import pytest`. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under both CircuitPython and MicroPython. A PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems.

**Code shape (libraries, microcontroller only)**

- Do not use `async` / `await` and ISRs. Use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped: no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`.
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

- [`plans/next-up.md`](plans/next-up.md) is the single source of truth for what's in flight. One bullet per item, no sub-bullets. Anything bigger gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. No `## Done` section. Enforced by `CHU011`.
- `Phase N` / `Slice N` references in commit subjects must carry a sentence topic (`Phase 6. Implement circuitpython and micropython transport seams`, not bare `Phase 6`).

## Keeping plans and docs current

**A feature that exists only in code is incomplete.** Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable. Every unit of work touches them in lockstep:

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update READMEs, the [style guide](docs/contributing/style-guide.md), the [cheat sheet](docs/contributing/cheat-sheet.md), CI workflows, scaffold templates, this file, ADR bodies, and anything else your change made wrong. A drift class that *can* be deterministically linted must be, not just doc-fixed. A prose-only contract is exactly the drift class that ships wrong. See [Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md).
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

- **Grep is for verifying a specific claim, not for replacing the read on judgment tasks.** When the deliverable is a judgment that requires holding context (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning. Split the target into smaller sequential passes. Do not switch tools. Token cost is not the success metric when the work *is* the read. Grep is the right primary tool when the deliverable is *finding* something specific, like callers of X or occurrences of a pattern. It is the wrong primary tool when the deliverable is *judging* prose, structure, or design. Worked application for code comments lives in [`audit-comments`](.github/skills/audit-comments/SKILL.md) under "Method discipline: read fully, do not grep-shortcut." Other audit-* skills inherit this rule. `audit-publishable-isolation` is exempt, since grep is its right primary tool for cross-repo leak hunting.
- **Surface tradeoffs early.** When multiple reasonable approaches exist, name them. When ambiguity affects correctness, ask. When a simpler approach would work, say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates: execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action*, not *skip the destructive-op check*.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Write in sentences. Don't use em-dashes, semicolons, or arrows as shortcuts that paper over missing connective tissue. If two ideas are linked, write them as two sentences or join with a comma and a connector. This applies to code comments, docstrings, and all markdown prose.

Cut AI-tic phrases. They sound non-human, drop information, and make prose harder to skim. The fix is usually structural, not vocabulary. When you write "the X promise" or "the X pattern", name X concretely in the same sentence. When you catch yourself writing one, rewrite the sentence to demonstrate the property concretely instead of asserting it abstractly.

**Degraded prose is rewritten, not trimmed again.** A passage rotted by repeated subtractive edits is not fixed by removing another word. That only makes it shorter and no clearer. Discard it and rewrite from a fresh read of what the thing is and why it exists. Several skills apply this rule in their scope: [`audit-comments`](.github/skills/audit-comments/SKILL.md) for code comments, [`audit-docs`](.github/skills/audit-docs/SKILL.md) for user-facing markdown, [`audit-skill`](.github/skills/audit-skill/SKILL.md) for SKILL.md bodies, and the in-place-edit rule in [`plans/decisions/README.md`](plans/decisions/README.md) for ADR bodies.

Specific bans:

- Avoid "the canonical X" framing. Often "the X" or "the standard X" works as well, and frequently the bare phrase reads better still. Keep canonical encoding, canonical form, and canonical path. These are real technical terms with no fluff substitute.
- Avoid "the one / single / sole X that…" as a definition opener. It is the same tic as canonical X. Say plainly what X does. Legitimate invariant prose like "the single owner of the staging path" stays. Tone guidance, not a lint.
- Use "the X" only when X is an established singular referent the reader already has. Use "a X" or "an X" for forward references or categories the reader has not acquired yet. Use bare X for systems and brand names where the article is decoration. For example, write "ESP32-S2 firmware" rather than "the ESP32-S2 firmware". Two nouns in one sentence often need different articles. Indefinite articles are not clinical. Reaching for "the" everywhere to sound terse is a frequent miss.
- Don't open sentences with "this is the" or "this is a" to point back at what was just said. Restate the subject directly, or drop the meta sentence entirely. For example, instead of "Run preflight before every commit. This is the rule the recovery skill enforces", write "The recovery skill enforces preflight before every commit".
- Drop adjectives that don't carry information: comprehensive, robust, seamlessly, cutting-edge, best-in-class. If you'd reach for "comprehensive", list what it covers. If you'd reach for "robust", name what it survives.
- Don't open sentences with filler like "It is worth noting that", "It should be noted that", "Note that", "Let's dive into", "Let's explore", or "In this section, we will". Start with the content.
- In publishable trees, don't cite CHU lint codes in prose. Name the rule's intent instead. For example, write "silent test skips" rather than "CHU009". Enforced by CHU006. The `# noqa: CHUNNN` directive is exempt.

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

### Libraries

`ls libraries/` is the live inventory. Each library has a `README.md` and `docs/guide.md`. The dependency stack, broadly:

- **Primitives:** `timing`, `runner`, `compat`, `logging`, `events`. Depended-on-by-everyone.
- **Persistence + serialization:** `msgpack`, `config`, `kvstore`.
- **Networking transport + protocols:** `wifi` (link), `sockets` (TCP/TLS/UDP), then app protocols: `ntp`, `requests`, `http_server`, `websockets`, `mqtt`.

Per-library deps are declared in each `pyproject.toml`. When a library doesn't already exist for a job, check `plans/decisions/` for a planned design. Look for `00NN-chumicro-<name>.md` files, which name libraries that have been designed but not yet built.

### Workbench (host-only)

`ls workbench/` is the live inventory. Currently:

- **`deploy`** pushes code, probes identity, and flashes firmware. It also provides a failure-classifying recovery layer.
- **`repl`** is a serial REPL with traceback highlighting and a `tail()` follow-mode.
- **`workspace`** is the project workspace CLI. It composes `deploy`, `repl`, and config. The starter is the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo.
- **`pytest-device`** is a pytest plugin (auto-registered via `pytest11`) that stages source onto a board and runs tests in the device runtime.
- **`checks`** carries the `CHU0NN` lint rules (`chumicro-checks`).

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

### Workbench CLIs, directly invocable from the mono-repo

- **`chumicro-workspace`** is the top-level dispatcher. It covers project-workspace lifecycle, device registry, running things on a board, config, firmware, curated libraries, health, and quality gates. Run `chumicro-workspace --help` for the live subcommand list.
- **`chumicro-deploy`** is the lower-level transport, with subcommands `probe`, `flash`, `deploy`, and `resolve-firmware-url`. Prefer the `chumicro-workspace` wrappers. Reach for this when composing custom flows.
- **`chumicro-repl`** is a direct REPL without a workspace project.

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
- [docs/contributing/releases.md](docs/contributing/releases.md) covers VERSION, SemVer, and experimental-to-stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md): PR conventions.

Tests live under each library's `tests/`. Shared fakes live in `src/chumicro_<name>/testing.py`. On-device tests live under `functional_tests/` and use `support/test_harness/`.

Each library's `VERSION` file is the source of truth. Bump only affected libraries. Development code stays as plain `.py`. `.mpy` compilation happens in the release pipeline.
