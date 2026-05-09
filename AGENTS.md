# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

## Session start

Every session, in this order:

1. `git --no-pager log --oneline -20` — see what just shipped.
2. Read [`plans/next-up.md`](plans/next-up.md) — the agent-managed work queue (`## Now`, `## Next`, `## Done (recent)`).
3. Skim [`plans/decisions/`](plans/decisions/) before any structural / pattern / tooling change. ADRs are co-located with the code they govern.
4. Check [`plans/open-questions.md`](plans/open-questions.md) for unresolved threads on the area you're touching.
5. Read the relevant skill at [`.github/skills/<name>/SKILL.md`](.github/skills/) before starting (also reachable at `.claude/skills/` via symlink).
6. Before writing or modifying implementation code in `libraries/` or `workbench/`, skim [`plans/patterns.md`](plans/patterns.md) for an established shape (recv-buffer reuse, Runner-shaped services, lazy adapter selection, FIFO deque, etc.).

Commit history is the primary fallback when planning docs are stale. Write commit messages that aid future context recovery.

## Keeping plans and docs current — load-bearing

**A feature that exists only in code is incomplete.** Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable, not commentary on it. Every unit of work touches them in lockstep:

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update READMEs, the [style guide](docs/contributing/style-guide.md), the [cheat sheet](docs/contributing/cheat-sheet.md), CI workflows, scaffold templates, this file, ADR bodies — whatever your change made wrong. Don't limit yourself to a fixed list.
- **Unit of work landed?** Move the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) to the top of `## Done (recent)` in the *same* edit. Cap is 25 entries — drop the oldest. CHU011 caps each top-level bullet at 5 sub-bullets; bigger items get promoted to [`plans/workstreams/<name>.md`](plans/workstreams/) and surface here as a one-line pointer.
- **Open question resolved?** Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands.
- **Decision changed?** Edit the ADR body in place (rewrite affected paragraphs so a cold reader gets accurate info) — no `Revised:` banners, no `## Update (YYYY-MM-DD)` sections. Status enum is `proposed` / `accepted` / `superseded` / `deferred` only. See [`plans/decisions/README.md`](plans/decisions/README.md).
- **End of every unit of work** → run the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill: preflight green, plans-doc updated, docs in sync, commit + push. Do not yield with uncommitted changes or untested behavior unless the work is explicitly partial — and say so.

Stale docs are a defect like any other. Treat them that way.

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

Before proposing a structural or pattern change, check `plans/decisions/` first.

## Non-negotiable rules

Ground rules. Each links to its source of truth where the *why* and edge cases live.

**Suppressions.** Every `CHU0NN` lint has a `# noqa: CHU0NN` escape (`<!-- noqa: CHU0NN -->` in Markdown); `# pragma: no cover` is the coverage equivalent. Use them when the rule legitimately doesn't apply — matching an upstream API, payload-style imports, runtime-only branches, hardware fallbacks. Pair every suppression with a one-line *why* a reviewer can verify.

**Workflow**

- Preflight must pass before commit. If preflight is already red on `main` (not from your changes), surface and stop — don't ship onto a broken `main`.
- While the repo is private, commit directly to `main` — no feature branches, no PRs. This retires when the repo opens to outside contributors.
- Use `git commit -F .scratch/commit-msg.txt`, never `git commit -m`. Read the [`git-commit`](.github/skills/git-commit/SKILL.md) skill before every commit.
- `.scratch/` is gitignored — temp files, commit messages, log captures.
- Pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Disable pagers (`git --no-pager`, `| cat`).
- Use file tools for multi-line file content — never heredocs, `echo`, `printf`, or `cat`.
- No backwards-compatibility burden. Nothing has shipped to PyPI yet (every package is `0.x`); edit forward, don't add migration shims, dual-read paths, or compat re-exports. "Public API" today means "us using it" — symbols with zero callers across this repo *and* the [workspace-template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo are dead code, not preserved future surface. Retires at the first stable (1.0+) release.
- Don't hard-code or commit secrets. Wifi passwords, MQTT credentials, API tokens, and the like belong only in the gitignored `secrets.toml` — never in `workspace.yml`, `project_config.toml`, example fixtures, or test data. See [Decision 0057](plans/decisions/0057-two-file-config.md).

**Testing**

- Use `python scripts/run.py test` for commit-gating runs — it's the only path that enforces per-library coverage thresholds (per-package subprocess + per-library `pyproject.toml` `addopts`). Bare `pytest` from the repo root is supported for ad-hoc / IDE Testing-panel runs — root [`pyproject.toml`](pyproject.toml) + [`conftest.py`](conftest.py) handle imports, importlib mode for test-name collisions, and `functional_tests/` deselection — but it does not gate coverage. See [Decision 0009](plans/decisions/0009-per-library-test-runs.md).
- Maintain coverage gates — every `test` and `preflight` invocation must pass `--coverage-threshold 94`. The `pyproject.toml` baseline is 85 % for human contributors; agent-generated code must use the higher gate per [Decision 0025](plans/decisions/0025-dual-coverage-thresholds.md). Use `# pragma: no cover` only where code genuinely cannot be exercised in CPython tests; see also the [coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions) section.
- Test skips must be loud — bare `if <cond>: return` in a test body is reported as PASS by the runner. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`. Enforced by `CHU009` + `CHU010` in [`scripts/check_no_silent_test_skip.py`](scripts/check_no_silent_test_skip.py); see [Decision 0058](plans/decisions/0058-test-skips-must-be-loud.md).
- Cross-runtime test files must not `import pytest`. A pytest import auto-scopes the file to CPython only — files without pytest imports are expected to run unmodified on MicroPython and CircuitPython unix-ports under `test-all-runtimes` / `test-micropython` / `test-circuitpython`. Use plain `assert` and constructor-injected fakes from each library's `testing.py`. See [Decision 0003](plans/decisions/0003-test-runtime-boundaries.md) + [Decision 0016](plans/decisions/0016-cross-runtime-unit-tests.md).

**Code shape (libraries — runs on a microcontroller)**

- No `async` / `await`, no ISRs — use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped per [Decision 0051](plans/decisions/0051-runner-shaped-as-project-policy.md): no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`, no synchronous DNS that doesn't yield.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule. See [Decision 0010](plans/decisions/0010-library-testability.md).
- Absolute imports only in code that runs on devices — `libraries/*/src/` and `support/test_harness/` must use `from chumicro_foo.bar import baz`. Relative imports break CircuitPython RAM-mode deploys (modules are `exec()`'d without a `__package__`). Workbench / scripts / tests may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code — MicroPython has no `__future__` module. CPython-only trees (tests, scripts, workbench) may keep it. See [Decision 0021](plans/decisions/0021-docstring-type-policy.md).
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`). Read via AST by bundles + every host-side deploy path; wrong-runtime files never land on the device. Test fakes in `testing.py` declare `("cpython",)`. See [Decision 0037](plans/decisions/0037-runtime-file-marking.md) + [Decision 0044](plans/decisions/0044-deploy-time-runtime-filtering.md).
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- Use descriptive names — no single-letter variables (except `_`); abbreviations we spell out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`. The `for i in range(10)` exemption is for human contributors — agent-generated code must use descriptive loop targets there too. Enforced by `CHU001`; see [Decision 0022](plans/decisions/0022-naming-conventions.md). Suppress with `# noqa: CHU001` only when matching an upstream API.
- Minimize dependencies — prefer pure-Python implementations compatible with all three runtimes.

**Code shape (workbench — runs on a laptop)**

- Workbench packages do not import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`, etc.). Templates / on-device payloads embedded as bytes are fine — that's payload, not import. Enforced by `CHU007` in [`scripts/check_workbench_no_lib_imports.py`](scripts/check_workbench_no_lib_imports.py); see [Decision 0052](plans/decisions/0052-workbench-no-library-imports.md).
- Workbench tools that touch hardware classify failures. Every host-side tool exposes a closed-set failure-kind enum + classifier + recovery plans in `<package>.recovery`, and CLIs wrap entry points in coaching loops. Generic `raise Exception` in workbench code is a UX defect. See [Decision 0053](plans/decisions/0053-recovery-layer-philosophy.md).

**Code comments**

- Code comments document the *why* of current code, nothing else. No history ("previously this did X"), no dated incidents ("2026-05-09 ESP32-S2 bake"), no removed-code explanations ("we used to also send Ctrl-C, dropped because…"), no workstream pointers ("Step 2 of workbench-deploy-reliability"). That belongs in the commit message, the ADR body, or the workstream file — all of which the next reader can find via `git log` / `plans/`. Same principle as the ADR-edit rule above: rewrite in place so a cold reader gets accurate info, don't layer dated annotations. Applies to docstrings and test-body comments too.

**Cross-repo isolation**

- No mono-repo references in publishable trees. `libraries/*/`, `workbench/*/`, and `support/test_harness/` ship to PyPI, CircuitPython-bundle (`circup`), and MicroPython-bundle (`mip`) consumers without the mono-repo. These trees must not name `plans/...md` paths, `Decision NNNN`, `scripts/run.py`, bare `run.py` (only `chumicro_workspace` legitimately knows about it), or "chumicro mono-repo" framing. Inline a one-line summary instead. Enforced by `CHU006` in [`scripts/check_no_repo_refs.py`](scripts/check_no_repo_refs.py). Suppress with `# noqa: CHU006` (Markdown: `<!-- noqa: CHU006 -->`) only when the reference is genuinely the only useful pointer.

**Plans-doc brevity**

- [`plans/next-up.md`](plans/next-up.md) is the agent-managed work queue and the single source of truth for what's in flight. Each top-level bullet is capped at 5 sub-bullets (CHU011); anything bigger gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. `## Done (recent)` is capped at 25 entries. Enforced by `CHU011` in [`scripts/check_plans_brevity.py`](scripts/check_plans_brevity.py). Suppress with `<!-- noqa: CHU011 -->` sparingly.

## Common pitfalls

- Don't `pip install -e` manually to fix imports — run `python scripts/run.py setup`.
- Don't modify unrelated code when fixing a focused bug. Mention pre-existing issues separately.
- Don't fabricate. Verify claims by reading code, running tests, or checking command output. If you can't verify, say so.
- Don't add features, abstractions, or speculative error handling beyond what was asked. If 200 lines could be 50, rewrite.
- Don't critique an architectural split from docs alone — read the code on both sides; docstrings often encode constraints (e.g. `scripts/prepare_workspace.py` exists separately from `scripts/run.py setup` because the former bootstraps the venv the latter assumes).
- Verify sub-agent (Explore / audit-* / general-purpose) concrete claims about existing code before relaying — grep or read the referenced files. Reports describe intent, not state.
- `replace_all` does literal substring substitution — before renaming a short identifier like `_foo`, grep for longer names that contain it (`_apply_foo`); the rename will silently corrupt them.
- When editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json` with path content), `cd` to the main checkout first — `sync-ide` from inside `.claude/worktrees/<name>/` writes `$MODULE_DIR$`-relative paths that resolve there but break in main.

## Working style

- **Anchor claims to evidence** — file, symbol, test, or command. No guessing.
- **Surface tradeoffs early.** Multiple reasonable approaches → name them. Ambiguity affects correctness → ask. Simpler approach would work → say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates — execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo (PRs, public posts), or scope expansion that wasn't asked. Auto mode amplifies *lean toward action* — not *skip the destructive-op check*.
- **Clean up after yourself.** Make an import / variable / function / test unused → remove it. Affect docs → update them. But don't fix pre-existing issues unless asked.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Cut AI-tic phrases.  They sound non-human, drop information, and make prose harder to skim.  The fix is usually structural, not vocabulary — when you write *"the X promise"* or *"the X pattern"*, **name X concretely in the same sentence** so the reader doesn't have to infer it.

Specific bans:

- **"the canonical promise" / "the canonical pattern"** → just name the promise or pattern.  Bad: *"Verifies the canonical promise: an LED keeps blinking…"*  Good: *"Verifies the LED-blink invariant: an LED keeps blinking…"*
- **"the canonical X" generally** → check whether *"the X"* or *"the standard X"* is enough.  Keep `canonical encoding`, `canonical form`, `canonical path` — those are real technical terms with no fluff substitute.
- **"comprehensive" / "robust" / "seamlessly" / "cutting-edge" / "best-in-class"** → drop outright.  If a thing is comprehensive, list what it covers.  If a thing is robust, name what it survives.
- **"It is worth noting that" / "It should be noted that" / "Note that"** (as a sentence opener) → just say the thing.
- **"Let's dive into" / "Let's explore" / "In this section, we will"** → start with the content, not the meta-commentary.
- **CHU lint codes in prose** (`CHU009`, `CHU010`, etc.) → name the rule's intent (*"silent test skips"*) instead of the code.  CHU codes are workspace-internal jargon a published-doc reader has no context for.  Enforced by `CHU006` — exempts `# noqa: CHUNNN` directives, flags everything else.

When you catch yourself writing one, rewrite the sentence to *demonstrate* the property concretely instead of asserting it abstractly.

## Project overview

Family of cross-runtime Python libraries for embedded boards.

- **CircuitPython** + **MicroPython** — deployment runtimes (the boards).
- **CPython** — desktop development, testing, fakes, workbench tooling. Host-test seam, not a deployment target. See [Decision 0049](plans/decisions/0049-three-runtime-trinity.md).

If a third-party library doesn't support CircuitPython or MicroPython, prefer a pure-Python alternative over a runtime-specific dep.

**Minimum board class:** 256 KB MCU RAM, 4 MB flash. Tier detail in [Decision 0015](plans/decisions/0015-board-architecture-support.md).

## Workspace layout

| Tree | Purpose | Ships to |
|------|---------|----------|
| [`libraries/<name>/`](libraries/) | Cross-runtime device libraries | PyPI + CircuitPython bundle (`circup`) + MicroPython bundle (`mip`) |
| [`workbench/<name>/`](workbench/) | Host-only laptop tools (CPython) | PyPI |
| [`support/<name>/`](support/) | Internal shared packages | Not published |
| [`scripts/`](scripts/) | Mono-repo dev tooling | Not published |
| [`plans/`](plans/) | Decisions, work queue, workstreams | Not published |
| [`docs/`](docs/) | Contributor + user docs | Published as the docs site |

The installer's destination decides the folder. Workbench-shipped *payload* (template files written onto a device) lives inside the workbench package — it's not an installable. See [Decision 0032](plans/decisions/0032-workbench-host-tools.md).

### Libraries

`ls libraries/` is the live inventory; each has a `README.md` and `docs/guide.md`. The set grows — don't depend on a list here. The dependency stack, broadly:

- **Primitives** — `timing`, `runner`, `compat`, `logging`, `events`. Owned-by-no-one, depended-on-by-everyone.
- **Persistence + serialization** — `msgpack`, `config`, `kvstore`. Live on top of the primitives.
- **Networking transport + protocols** — `wifi` (link), `sockets` (TCP/TLS/UDP), then app protocols: `ntp`, `requests`, `http_server`, `websockets`, `mqtt`.

Per-library deps are declared in each `pyproject.toml`; cross-library policy is [Decision 0042](plans/decisions/0042-library-dependency-policy.md). When a library doesn't already exist for a job, check the latest `plans/decisions/` for a chartered design (`00NN-chumicro-<name>.md`).

### Workbench (host-only)

`ls workbench/` is the live inventory. Currently four packages:

- **`deploy`** — push code, probe identity, flash firmware; failure-classifying recovery layer
- **`repl`** — serial REPL with traceback highlighting and `tail()` follow-mode
- **`workspace`** — one-stop project workspace CLI (composes `deploy` + `repl` + config); canonical starter is the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo ([Decision 0038](plans/decisions/0038-workspace-bootstrap-via-clone.md))
- **`pytest-device`** — pytest plugin (auto-registered via `pytest11`) that stages source onto a board and runs tests in the device runtime

## Commands

The mono-repo itself has workspace shape (`workspace.yml` + `devices.yml` at root), so the workbench CLIs work directly here too.

`python scripts/run.py setup` does an editable install of every package into `.venv/`. Activate it (`source .venv/bin/activate`) or use `.venv/bin/<cli>` / `.venv/bin/python -m <pkg>` — system `python3` won't find `chumicro_*` packages, and `chumicro-workspace` / `chumicro-deploy` / `chumicro-repl` only end up on PATH from the venv.

### `python scripts/run.py <cmd>` — CI-mirror runner

| Command | Purpose |
|---------|---------|
| `setup` | Install deps + regenerate IDE configs |
| `preflight` | Full CI mirror (lint + build + docs + unit tests on all runtimes + checks). `--with-functional` adds hardware-gated tests |
| `test` | CPython unit tests (changed packages by default; `--all` for full sweep) |
| `lint` | Ruff across the workspace |
| `build` | Build publishable packages |
| `docs` / `docs-preview` / `docs-deploy` | Build / serve / deploy versioned docs |
| `test-all-runtimes` | CPython + MicroPython + CircuitPython unit tests (parallelized) |
| `test-micropython` / `test-circuitpython` | One runtime |
| `test-functional` | All hardware-gated suites (libraries + workbench) |
| `test-libraries-functional` / `test-workbench-functional` | Scoped functional runs |
| `test-scripts` | Scripts infrastructure tests |
| `prepare-micropython` / `prepare-circuitpython` / `prepare-mpy-cross` | Build / pin runtime sources under `.tools/` (gitignored) |
| `verify-examples` | Import-check example scripts |
| `validate-mip` | Validate `mip install` against a bundle repo or local staging |
| `check-version` / `check-api` / `check-dep-graph` | Release-gate checks |
| `add-device` | Register a board (thin shim around `chumicro-workspace add-device`) |
| `new-library` | Scaffold a new device library + regenerate IDE configs |
| `sync-ide` | Regenerate IDE configs |

`--help` lists every flag. Functional-test flag semantics: [docs/contributing/device-testing.md](docs/contributing/device-testing.md).

### Workbench CLIs — directly invocable from the mono-repo

- **`chumicro-workspace`** — top-level dispatcher. Project-workspace lifecycle (`init`, `setup`, `update`, `new`), device registry (`add-device`, `probe`, `discover`, `devices`), running things on a board (`deploy`, `repl`, `demo`, `bootstrap`), config (`dump-config`, `config-validate`), firmware (`install-firmware`, `reset-board`, `install-libraries`, `upgrade-firmware`), health (`status`, `doctor`), and quality gates (`test`, `lint`, `preflight`). Run `chumicro-workspace --help` for the live subcommand list.
- **`chumicro-deploy`** — lower-level transport: `probe`, `flash`, `deploy`, `resolve-firmware-url`. Prefer `chumicro-workspace` wrappers; reach for this when composing custom flows.
- **`chumicro-repl`** — direct REPL without a workspace project.

`<cli> --help` and `<cli> <sub> --help` for full flag lists. Workflow walkthroughs in [docs/contributing/device-testing.md](docs/contributing/device-testing.md) and [docs/contributing/working-with-agents.md](docs/contributing/working-with-agents.md).

## Skills

Procedural knowledge lives in [`.github/skills/<name>/SKILL.md`](.github/skills/) (also reachable at `.claude/skills/` via symlink). Read the relevant skill before performing the task.

| Skill | When |
|-------|------|
| `git-commit` | Before every commit |
| `task-checkpoint` | After each unit of work |
| `debug-test-failure` | Tests fail |
| `large-output` | Commands that produce big output |
| `run-script` | Multi-line Python or structured file content |
| `terminal-recovery` | Terminal hangs or shows a continuation prompt |
| `new-library` | Adding a new device library |
| `new-decision` | Recording a structural / pattern / tooling decision |
| `guide-generation` | Writing or refreshing a library's `docs/guide.md` |
| `validate-scripts` | Changing or validating `scripts/` infrastructure |
| `audit-library` | Single-library code-quality audit |
| `audit-integration` | Cross-library boundary audit |
| `audit-workspace` | Mono-repo-wide audit |
| `audit-publishable-isolation` | Cross-repo audit for mono-repo concept leaks into shipped artifacts |

`end-of-session` is a human-only checklist; agents use `task-checkpoint`.

## File routing

| Task | Where |
|------|-------|
| New device library | `python scripts/run.py new-library <name>` |
| New host-only tool | `workbench/<name>/` — hand-scaffold; see [docs/contributing/workbench.md](docs/contributing/workbench.md) |
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

For the *what* and *why* behind each rule, the authoritative docs are:

- [plans/patterns.md](plans/patterns.md) — agent-targeted implementation cookbooks. The *how* paired with each non-negotiable's *what*: Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, IDE Testing-panel show-but-deselect, and more.
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md) — naming, annotations, imports, layout, doc tone. Linter enforces most of it.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md) — functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md) — VERSION, SemVer, experimental → stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md) — PR conventions.

Tests live under each library's `tests/`; shared fakes in `src/chumicro_<name>/testing.py` (see [Decision 0009](plans/decisions/0009-per-library-test-runs.md), [Decision 0010](plans/decisions/0010-library-testability.md)). On-device tests live under `functional_tests/` and use `support/test_harness/`.

Each library's `VERSION` file is the source of truth — bump only affected libraries. Development code stays as plain `.py`; `.mpy` compilation happens in the release pipeline.
