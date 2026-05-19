# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).
>
> This file is the directive. The *why* behind each rule — rationale, the
> incident that forced it, the decision record — lives in
> [`AGENTS.notes.md`](AGENTS.notes.md). Open it when a rule's reasoning is
> non-obvious or you're about to argue with one.

## Session start

Every session, in this order:

1. `git --no-pager log --oneline -20` — see what just shipped.
2. Read [`plans/next-up.md`](plans/next-up.md) — the work queue (`## Now`, `## Next`, `## Done (recent)`). A queued session-handoff pointer in `## Now` is not a resume directive; invoke [`session-resume`](.github/skills/session-resume/SKILL.md) only on an explicit user signal.
3. `ls plans/decisions/` — the filename slug carries topic *and* lifecycle; treat the listing as the index. A `SUPERSEDED-BY-NNNN` or `INERT` marker means a dead record — skip it on the scan; open it only to trace *why* something changed (`SUPERSEDED-BY-NNNN` names the replacement). For live candidates, `head -n 10` for the gist; full read before any structural / pattern / tooling change. ADRs are co-located with the code they govern.
4. Check [`plans/open-questions.md`](plans/open-questions.md) for unresolved threads on what you're touching.
5. Read the relevant [`.github/skills/<name>/SKILL.md`](.github/skills/) before starting (also at `.claude/skills/` via symlink).
6. Before writing implementation code in `libraries/` or `workbench/`, skim [`plans/patterns.md`](plans/patterns.md) for an established shape.

Commit history is the primary fallback when planning docs are stale. Write commit messages that aid future context recovery.

## Keeping plans and docs current — load-bearing

**A feature that exists only in code is incomplete.** Docs, ADRs, planning files, scaffold templates, and CI are part of the deliverable. Every unit of work touches them in lockstep:

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update READMEs, [style guide](docs/contributing/style-guide.md), [cheat sheet](docs/contributing/cheat-sheet.md), CI workflows, scaffold templates, this file, ADR bodies — whatever your change made wrong. A drift class that *can* be deterministically linted must be, not just doc-fixed.
- **Unit of work landed?** Move the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) to the top of `## Done (recent)` in the *same* edit. `## Done (recent)` is a ledger, not a synopsis — cap 5, drop the oldest. Top-level bullets cap at 5 sub-bullets; bigger items promote to [`plans/workstreams/<name>.md`](plans/workstreams/) and surface here as a one-line pointer.
- **Open question resolved?** Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands.
- **Adding or changing an ADR?** Read [`plans/decisions/README.md`](plans/decisions/README.md) **first** — it carries the load-bearing authoring rules and they apply to editing an existing decision as much as to a new one. New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill.
- **End of every unit of work** → run the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill: preflight green, plans-doc updated, docs in sync, commit + push. Don't yield with uncommitted changes or untested behavior unless the work is explicitly partial — and say so.

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

Before proposing a structural or pattern change, check `plans/decisions/` first.

## Non-negotiable rules

Ground rules. The *why* and edge cases live in [`AGENTS.notes.md`](AGENTS.notes.md) and the linked decisions.

**Workflow**

- Preflight must pass before commit. If preflight is already red on `main` (not from your changes), surface and stop — don't ship onto a broken `main`.
- While the repo is private, commit directly to `main` — no feature branches, no PRs.
- Pass the commit message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`) so backticks, `$`, parens, and newlines pass literally. Read the [`git-commit`](.github/skills/git-commit/SKILL.md) skill before every commit.
- `.scratch/` is gitignored — temp files, log captures.
- Pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Disable pagers (`git --no-pager`, `| cat`).
- Use file tools to write or edit files — never heredocs, `echo`, `printf`, or `cat` for file content (the heredoc rule above is commit messages only).
- No backwards-compatibility burden until 1.0 — edit forward, no migration shims, dual-read paths, or compat re-exports. A symbol with zero callers across this repo *and* the [workspace-template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo is dead code, not future surface.
- Don't hard-code or commit secrets — Wifi passwords, MQTT credentials, API tokens belong only in the gitignored `secrets.toml`.
- Every `CHU0NN` lint has a `# noqa: CHU0NN` escape (`<!-- noqa: CHU0NN -->` in Markdown); `# pragma: no cover` is the coverage equivalent. Use only when the rule legitimately doesn't apply, and pair every suppression with a verifiable one-line *why*.

**Testing**

- Use `python scripts/run.py test` for commit-gating runs — per-package subprocess, parallelized, what CI runs. Per-library coverage gating fires **only when `--coverage-threshold N` is passed**. Bare `pytest` from the repo root works for ad-hoc / IDE runs but gates no coverage. See [Decision 0009](plans/decisions/0009-per-library-test-runs.md).
- Maintain coverage gates — every `test` and `preflight` invocation must pass `--coverage-threshold 94` (a scoped figure; see notes). The `pyproject.toml` baseline is 85 % for humans; agent-generated code uses the higher gate per [Decision 0025](plans/decisions/0025-dual-coverage-thresholds.md). Use `# pragma: no cover` only where code genuinely can't be exercised in CPython.
- Test skips must be loud — a bare `if <cond>: return` in a test body is reported as PASS. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- Cross-runtime test files must not `import pytest` — it auto-scopes the file to CPython only. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under **both** CircuitPython and MicroPython. A file that OOMs there even with `--per-file` is a tracked defect, fixed by splitting it (lossless) until each sub-file fits.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems — build a minimal in-repo fixture under `<package>/(functional_)tests/fixtures/`.

**Code shape (libraries — runs on a microcontroller)**

- No `async` / `await`, no ISRs — use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped: no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`, no synchronous DNS that doesn't yield.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule.
- Absolute imports only in code that runs on devices — `libraries/*/src/` and `support/test_harness/` must use `from chumicro_foo.bar import baz`. Relative imports break CircuitPython RAM-mode deploys. Workbench / scripts / tests may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code — MicroPython has no `__future__`. CPython-only trees may keep it.
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`); wrong-runtime files never land on the device. Test-support modules (`testing.py` fakes) instead declare `__chumicro_test_support__ = True` and **no** runtime marker.
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- No `__slots__` in `libraries/*/src/`, and no pure-passthrough `@property` — name the attribute publicly instead. Computed properties (doing actual work) stay legitimate. Workbench packages are out of scope.
- Use descriptive names — no single-letter variables (except `_`); expand abbreviations to full words (`buffer` not `buf`, `command` not `cmd`, …). The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`; suppress only when matching an upstream API.
- Minimize dependencies — prefer pure-Python implementations compatible with all three runtimes.

**Code shape (workbench — runs on a laptop)**

- Workbench packages do not import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`). Embedded payload bytes are fine — that's payload, not import. Enforced by `CHU007`.
- Workbench tools that touch hardware classify failures. Every host-side tool exposes a closed-set failure-kind enum + classifier + recovery plans in `<package>.recovery`; CLIs wrap entry points in coaching loops. Generic `raise Exception` is a UX defect.
- Workbench CLIs and `scripts/run.py` tasks callable by humans and agents support a non-interactive mode: TTY auto-detected via `sys.stdin.isatty()`, `--non-interactive` override, no prompts/tails when non-interactive, distinct exit codes per failure mode. Inherently-interactive subcommands document the TTY requirement and exit cleanly without one.
- One device-staging path: code reaches a board only through the deploy stage + diff/`rsync --delete` primitive. Clean-slate is the default (`--no-wipe` opts out to additive, `--wipe` is full erase); a closed keep set `{boot.py, boot_out.txt, _chu_kv.msgpack}` survives, `settings.toml` never does. No command or context grows its own staging path, delete semantics, or keep/exclude policy — per-context variance is only the payload and the post-stage step. [Decision 0077](plans/decisions/0077-one-device-staging-path.md).

**Code comments**

- Code comments document the *why* of current code, nothing else. No history, no dated incidents, no removed-code explanations, no workstream pointers — that belongs in the commit message, the ADR body, or the workstream file. Applies to docstrings and test-body comments too.
- Audit-pass commits may add general "what this work is doing" framing, but never per-change justification (*"bench-validated -25% allocation"*) and never the same comment repeated across many sites. Flash is ~800 KB total; bloaty comment patterns multiplied across libraries fill it fast.

**Cross-repo isolation**

- No mono-repo references in publishable trees. `libraries/*/`, `workbench/*/`, and `support/test_harness/` ship to PyPI / `circup` / `mip` without the mono-repo. These trees must not name `plans/...md` paths, `Decision NNNN` / `ADR NNNN`, `scripts/run.py`, bare `run.py` (only `chumicro_workspace` legitimately knows about it), or "chumicro mono-repo" framing. Inline a one-line summary instead. Enforced by `CHU006`; suppress only when the reference is genuinely the only useful pointer.

**Plans-doc brevity**

- [`plans/next-up.md`](plans/next-up.md) is the single source of truth for what's in flight. Top-level bullet capped at 5 sub-bullets; anything bigger gets a [`plans/workstreams/<name>.md`](plans/workstreams/) file. `## Done (recent)` capped at 5 entries. Enforced by `CHU011`.
- `Phase N` / `Slice N` references in commit subjects and `Done` entries must carry a 3-word topic (`Phase 6 — transport seams`, not bare `Phase 6`).

## Common pitfalls

- Don't `pip install -e` manually to fix imports — run `python scripts/run.py setup`.
- If bare `python` errors `command not found`, the agent shell didn't inherit a `python` alias. Run `source .venv/bin/activate` once, or invoke `.venv/bin/python scripts/run.py …` directly.
- Don't modify unrelated code when fixing a focused bug. Mention pre-existing issues separately.
- Don't fabricate. Verify by reading code, running tests, or checking command output. Training recall is not verification — for anything time-sensitive, version-specific, or newer than the model cutoff, web-search it rather than asserting from memory.
- Don't add features, abstractions, or speculative error handling beyond what was asked. If 200 lines could be 50, rewrite.
- Don't critique an architectural split from docs alone — read the code on both sides; docstrings often encode constraints.
- Verify sub-agent (Explore / audit-* / general-purpose) concrete claims before relaying — grep or read the referenced files. Reports describe intent, not state.
- `replace_all` is literal substring substitution — before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
- Editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json`) — `cd` to the main checkout first; `sync-ide` from a worktree writes paths that break in main.
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`) — the deploy/transport code owns it. Destructive remediation: `chumicro-workspace reset-board --yes`.
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython) — the runtime re-runs the file every boot, producing an infinite boot loop. Trigger hard reset via raw REPL exec, one-shot, never persisted. See [`AGENTS.notes.md`](AGENTS.notes.md) for the pattern location.
- A `git rm` / `git add` stages immediately and rides into the *next* commit, even a later narrowly-scoped one. Before a scoped commit, `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs. (This bit `main` once — see notes.)

## Working style

- **Anchor claims to evidence** — file, symbol, test, or command. No guessing.
- **Surface tradeoffs early.** Multiple reasonable approaches → name them. Ambiguity affects correctness → ask. Simpler approach would work → say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates — execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action* — not *skip the destructive-op check*.
- **Clean up after yourself.** Make an import / variable / function / test unused → remove it. Affect docs → update them. But don't fix pre-existing issues unless asked.
- **Re-verify state after recovery actions.** When a fix depends on the user running a recovery action (replug, reset-board, unwedge), re-run the failing detection and the smallest failing test *before* committing. "Done" from the user is the signal to verify, not proof the fix worked.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Cut AI-tic phrases. The fix is usually structural — when you write *"the X promise"* or *"the X pattern"*, name X concretely in the same sentence.

Specific bans:

- **"the canonical promise" / "the canonical pattern"** → just name the promise or pattern. Keep real technical terms (`canonical encoding`, `canonical form`, `canonical path`).
- **"comprehensive" / "robust" / "seamlessly" / "cutting-edge" / "best-in-class"** → drop outright. If a thing is comprehensive, list what it covers.
- **"It is worth noting that" / "It should be noted that" / "Note that"** (sentence opener) → just say the thing.
- **"Let's dive into" / "Let's explore" / "In this section, we will"** → start with the content.
- **CHU lint codes in prose** in publishable trees → name the rule's intent (*"silent test skips"*). Enforced by `CHU006`, which exempts `# noqa: CHUNNN` directives.

## Project overview

Family of cross-runtime Python libraries for embedded boards.

- **CircuitPython** + **MicroPython** — deployment runtimes (the boards).
- **CPython** — desktop development, testing, fakes, workbench tooling. Host-test seam, not a deployment target.

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

The installer's destination decides the folder. Workbench-shipped *payload* (template files written onto a device) lives inside the workbench package — it's not an installable.

### Libraries

`ls libraries/` is the live inventory; each has a `README.md` and `docs/guide.md`. The dependency stack, broadly:

- **Primitives** — `timing`, `runner`, `compat`, `logging`, `events`. Depended-on-by-everyone.
- **Persistence + serialization** — `msgpack`, `config`, `kvstore`.
- **Networking transport + protocols** — `wifi` (link), `sockets` (TCP/TLS/UDP), then app protocols: `ntp`, `requests`, `http_server`, `websockets`, `mqtt`.

Per-library deps are declared in each `pyproject.toml`. When a library doesn't already exist for a job, check `plans/decisions/` for a chartered design (`00NN-chumicro-<name>.md`).

### Workbench (host-only)

`ls workbench/` is the live inventory. Currently:

- **`deploy`** — push code, probe identity, flash firmware; failure-classifying recovery layer
- **`repl`** — serial REPL with traceback highlighting and `tail()` follow-mode
- **`workspace`** — one-stop project workspace CLI (composes `deploy` + `repl` + config); starter is the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo
- **`pytest-device`** — pytest plugin (auto-registered via `pytest11`) that stages source onto a board and runs tests in the device runtime
- **`checks`** — the `CHU0NN` lint rules (`chumicro-checks`)

## Commands

The mono-repo has workspace shape (`workspace.yml` + `devices.yml` at root), so the workbench CLIs work directly here. `python scripts/run.py setup` editable-installs every package into `.venv/`; activate it or use `.venv/bin/<cli>` — system `python3` won't find `chumicro_*`.

### `python scripts/run.py <cmd>` — CI-mirror runner

| Command | Purpose |
|---------|---------|
| `setup` | Install deps + regenerate IDE configs |
| `preflight` | Full CI mirror (lint + build + docs + all-runtime unit tests + checks). `--with-functional` adds hardware-gated tests; `--with-device-unit` appends the on-device sweep |
| `test` | CPython unit tests (changed packages by default; `--all` for full sweep) |
| `lint` | Ruff across the workspace |
| `build` | Build publishable packages |
| `docs` / `docs-preview` / `docs-deploy` | Build / serve / deploy versioned docs |
| `test-all-runtimes` | CPython + MicroPython + CircuitPython unit tests (parallelized) |
| `test-micropython` / `test-circuitpython` | One runtime |
| `test-functional` | All hardware-gated suites (libraries + workbench) |
| `test-libraries-functional` / `test-workbench-functional` | Scoped functional runs |
| `test-unit-on-device` | Cross-runtime *unit* suite on real boards (the on-device sweep): per-library mode resolution, RAM-preferred, behavioral pass/fail only. `--per-file` semantics and the Pico W must-fix rule are in [`AGENTS.notes.md`](AGENTS.notes.md) |
| `test-scripts` | Scripts infrastructure tests |
| `prepare-micropython` / `prepare-circuitpython` / `prepare-mpy-cross` | Build / pin runtime sources under `.tools/` (gitignored) |
| `verify-examples` | Import-check example scripts |
| `validate-mip` | Validate `mip install` against a bundle repo or local staging |
| `check-version` / `check-api` / `check-dep-graph` | Release-gate checks |
| `add-device` | Register a board (thin shim around `chumicro-workspace add-device`) |
| `new-library` | Scaffold a new device library (`--workbench` for a host-only tool) + regenerate IDE configs |
| `sync-ide` | Regenerate IDE configs |

`--help` lists every flag. Functional-test flag semantics: [docs/contributing/device-testing.md](docs/contributing/device-testing.md).

### Workbench CLIs — directly invocable from the mono-repo

- **`chumicro-workspace`** — top-level dispatcher: project-workspace lifecycle, device registry, running things on a board, config, firmware, curated libraries, health, and quality gates. Run `chumicro-workspace --help` for the live subcommand list.
- **`chumicro-deploy`** — lower-level transport: `probe`, `flash`, `deploy`, `resolve-firmware-url`. Prefer the `chumicro-workspace` wrappers; reach for this when composing custom flows.
- **`chumicro-repl`** — direct REPL without a workspace project.

`<cli> --help` and `<cli> <sub> --help` for full flag lists. Walkthroughs in [docs/contributing/device-testing.md](docs/contributing/device-testing.md) and [docs/contributing/working-with-agents.md](docs/contributing/working-with-agents.md).

## Skills

Procedural knowledge lives in [`.github/skills/<name>/SKILL.md`](.github/skills/) (also at `.claude/skills/` via symlink). The session-start reminder lists every skill with a one-line trigger — read the matching `SKILL.md` body before performing that task. After each unit of work, run `task-checkpoint`.

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

For the *what* and *why* behind each rule:

- [AGENTS.notes.md](AGENTS.notes.md) — rationale + the incident behind each rule, keyed by commit hash.
- [plans/patterns.md](plans/patterns.md) — implementation cookbooks: Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, and more.
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md) — naming, annotations, imports, layout, doc tone.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md) — functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md) — VERSION, SemVer, experimental → stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md) — PR conventions.

Tests live under each library's `tests/`; shared fakes in `src/chumicro_<name>/testing.py`. On-device tests live under `functional_tests/` and use `support/test_harness/`.

Each library's `VERSION` file is the source of truth — bump only affected libraries. Development code stays as plain `.py`; `.mpy` compilation happens in the release pipeline.
