# ChuMicro Development Ecosystem

> Operating manual for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

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

- **Behavior, command, library, config, pattern, or rule changed?** Ask: *"If someone reads the docs tomorrow, will they find correct information?"* Update READMEs, [style guide](docs/contributing/style-guide.md), [cheat sheet](docs/contributing/cheat-sheet.md), CI workflows, scaffold templates, this file, ADR bodies — whatever your change made wrong. A drift class that *can* be deterministically linted must be, not just doc-fixed — a prose-only contract is exactly the drift class that ships wrong. See [Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md).
- **Unit of work landed?** Move the matching `## Now` / `## Next` bullet in [`plans/next-up.md`](plans/next-up.md) to the top of `## Done (recent)` in the *same* edit. `## Done (recent)` is a ledger, not a synopsis — cap 5, drop the oldest. Top-level bullets cap at 5 sub-bullets; bigger items promote to [`plans/workstreams/<name>.md`](plans/workstreams/) and surface here as a one-line pointer.
- **Open question resolved?** Update [`plans/open-questions.md`](plans/open-questions.md) the moment the answer lands.
- **Adding or changing an ADR?** Hard rules below; they bind editing an existing decision as much as a new one. Full detail + rejected alternatives in [`plans/decisions/README.md`](plans/decisions/README.md). New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill.
  - **Edit the body in place.** An `accepted` ADR describes *current* state. Scope changed, path renamed, alternative now rejected → rewrite the affected paragraphs. No `Amended by` banners, no `## Update` sections, no "this was revised twice" preambles — `git log` carries history.
  - **A correction of reasoning that was *wrong* is an in-place edit — never a new ADR.** A new superseding ADR is only for a genuine reasoning *shift*. If you fix the old ADR's prose, you do not also mint a standalone ADR repeating the corrected rule: one invariant, one home. A partial-supersession that leaves the same corrected principle stated in full in *both* records is the bloat this rule exists to stop (worked case: 0038 §3 ↔ 0075).
  - **State the principle, not the mechanism.** The decision sentence states the invariant, not the implementation that prompted it. Treat any "Rejected: [the stricter thing actually asked for], because [convenience]" bullet as the narrowing happening in real time — challenge it before the ADR lands. (Cautionary case: 0038's clone-not-pip wording let a clone-based `init` CLI through the hole.)
  - **Argument-stopping rationale is part of the directive — it lives inline.** A *why* clause is directive if an agent reading only the bare rule would plausibly argue it, take a shortcut it forecloses, or misapply it for want of the concrete form. Such clauses stay inline in this file and in ADRs; they may not move to any separate location (auto-loaded or not). A compaction pass that can't keep one within budget has found the budget wrong, not the clause optional. Size is not the success metric.
- **End of every unit of work** → run the [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill: preflight green, plans-doc updated, docs in sync, commit + push. Don't yield with uncommitted changes or untested behavior unless the work is explicitly partial — and say so.

## Instruction priority

When instructions overlap:

1. This file's hard rules
2. The relevant skill in [`.github/skills/`](.github/skills/)
3. Accepted decisions in [`plans/decisions/`](plans/decisions/)
4. Repository docs ([style guide](docs/contributing/style-guide.md), [contributing/](docs/contributing/))

Before proposing a structural or pattern change, check `plans/decisions/` first.

## Non-negotiable rules

**Workflow**

- Preflight must pass before commit. If preflight is already red on `main` (not from your changes), surface and stop.
- While the repo is private, commit directly to `main` — no feature branches, no PRs.
- Pass the commit message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`) so backticks, `$`, parens, and newlines pass literally. Read the [`git-commit`](.github/skills/git-commit/SKILL.md) skill before every commit.
- `.scratch/` is gitignored — temp files, log captures.
- Pipe large output through `tail` / `head` / `grep`, or redirect to `.scratch/`. Disable pagers (`git --no-pager`, `| cat`).
- Use file tools to write or edit files — never heredocs, `echo`, `printf`, or `cat` for file content (the heredoc rule above is commit messages only).
- No backwards-compatibility burden until 1.0 — edit forward, no migration shims, dual-read paths, or compat re-exports. A symbol with zero callers across this repo *and* the [workspace-template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo is dead code, not future surface.
- Don't hard-code or commit secrets — Wifi passwords, MQTT credentials, API tokens belong only in the gitignored `secrets.toml`.
- Every `CHU0NN` lint has a `# noqa: CHU0NN` escape (`<!-- noqa: CHU0NN -->` in Markdown); `# pragma: no cover` is the coverage equivalent. Use only when the rule legitimately doesn't apply — matching an upstream API, payload-style imports, runtime-only branches, hardware fallbacks — and pair every suppression with a one-line *why* a reviewer can verify.

**Testing**

- Use `python scripts/run.py test` for commit-gating runs — per-package subprocess, parallelized, what CI runs. Per-library coverage gating fires **only when `--coverage-threshold N` is passed**. Bare `pytest` from the repo root works for ad-hoc / IDE runs but gates no coverage. See [Decision 0009](plans/decisions/0009-per-library-test-runs.md).
- Maintain coverage gates — every `test` and `preflight` invocation must pass `--coverage-threshold 94`. With no flag, coverage is a single post-`combine` repo-wide 85 % aggregate — there is no per-library `pyproject.toml` coverage config. The 85 % baseline is for human contributors; agent-generated code uses the 94 % gate per [Decision 0025](plans/decisions/0025-dual-coverage-thresholds.md). 94 % is **CPython-reachable, post-`# pragma: no cover`, with no device-execution signal** — not 94 % of shipped code; cite it only with that scope. Use `# pragma: no cover` only where code genuinely can't run in CPython (device adapters blanket-pragma — their imports don't exist there).
- Test skips must be loud — a bare `if <cond>: return` in a test body is reported as PASS by the runner. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`. Enforced by `CHU009` + `CHU010`.
- Cross-runtime test files must not `import pytest` — it auto-scopes the file to CPython only. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under **both** CircuitPython and MicroPython — a PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect, fixed by splitting it source-module-shaped, then mechanically (lossless), until each sub-file fits. No fixed tests-per-file cap — it's bench-determined per library and differs CP vs MP.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems — build a minimal in-repo fixture under `<package>/(functional_)tests/fixtures/`.

**Code shape (libraries — runs on a microcontroller)**

- No `async` / `await`, no ISRs — use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md). Every device library that owns time or I/O must be runner-shaped: no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`, no synchronous DNS that doesn't yield.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule.
- Absolute imports only in code that runs on devices — `libraries/*/src/` and `support/test_harness/` must use `from chumicro_foo.bar import baz`. Relative imports break CircuitPython RAM-mode deploys. Workbench / scripts / tests may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code — MicroPython has no `__future__`. CPython-only trees may keep it.
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`); wrong-runtime files never land on the device. Test-support modules (`testing.py` fakes) instead declare `__chumicro_test_support__ = True` and **no** runtime marker.
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- No `__slots__` in `libraries/*/src/` — MP/CP have no `__slots__` implementation, so the only payoff is CPython-test attribute locking, paid for in flash on every board. No pure-passthrough `@property` either — name the attribute publicly instead. Computed properties (doing actual work) stay legitimate. Workbench packages are out of scope.
- Use descriptive names — no single-letter variables (except `_`); expand abbreviations to full words: `env`→`environment`, `buf`→`buffer`, `src`→`source`, `cmd`→`command`, `msg`→`message`, `err`→`error`, `ref`→`reference`, `addr`→`address`, `exc`→`exception`, `exec`→`execute`. The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`; suppress only when matching an upstream API.
- Minimize dependencies — prefer pure-Python implementations compatible with all three runtimes.
- These code-shape rules (`const()` / `memoryview` / pre-alloc, no `typing` / `__future__` / `__slots__`, absolute imports) exist *because* the code runs on MicroPython / CircuitPython, and they stop at that boundary: `scripts/` and `support/` (except `support/test_harness/`) are CPython-only — use the full stdlib and standard modern Python there. Applying the embedded patterns to infra code is cost with no payoff.

**Code shape (workbench — runs on a laptop)**

- Workbench packages do not import library packages. `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`. Use third-party PyPI equivalents (`pyserial`, `ruamel.yaml`, `msgpack`). Embedded payload bytes are fine — that's payload, not import. Enforced by `CHU007`.
- Workbench tools that touch hardware classify failures. Every host-side tool exposes a closed-set failure-kind enum + classifier + recovery plans in `<package>.recovery`; CLIs wrap entry points in coaching loops. Generic `raise Exception` is a UX defect.
- Workbench CLIs and `scripts/run.py` tasks callable by humans and agents support a non-interactive mode: TTY auto-detected via `sys.stdin.isatty()`, `--non-interactive` override, no prompts/tails when non-interactive, distinct exit codes per failure mode. Inherently-interactive subcommands document the TTY requirement and exit cleanly without one.
- One device-staging path: code reaches a board only through the deploy stage + diff/`rsync --delete` primitive. Clean-slate is the default (`--no-wipe` opts out to additive, `--wipe` is full erase); a closed keep set `{boot.py, boot_out.txt, _chu_kv.msgpack}` survives, `settings.toml` never does. No command or context grows its own staging path, delete semantics, or keep/exclude policy — per-context variance is only the payload and the post-stage step. Library acquisition is host-local: `chumicro-workspace library add` / `library browse` pulls a library's full editable tree + its pyproject closure from a published snapshot channel into **committed** `libraries/`, edit-preserving (`_library-backups/`); the one deploy then bundles it. [Decision 0077](plans/decisions/0077-one-device-staging-path.md), [Decision 0078](plans/decisions/0078-library-acquisition-is-host-local.md).

**Code comments**

- A code comment first states, in plain words, **what the thing does or returns**, written so a reader who has *not* read the code is oriented — then the non-obvious *why*. "Document the why" is not enough alone: *"the one true path for getting this string from this area"* breaks none of the prohibitions below and still says nothing; *"Returns the product ID string."* is the fix. Full shape and the trim-vs-rewrite call: the [`audit-comments`](.github/skills/audit-comments/SKILL.md) skill.
- Two comment failures agents commit while writing, not just in audits: a confined helper's comment must not name its callers — it has no business knowing them; state the contract, not *"called from the deploy CLI"*. And a comment must not point outside this code's world: no *"mirrors the reference impl"*, no upstream-repo / sibling-project names — the reader here cannot act on them (for shipped trees `CHU006` also mechanizes the mono-repo subset).
- Beyond the what+why shape, the comment documents the *why of current code*, nothing else. No history (*"previously this did X"*), no dated incidents (*"2026-05-09 ESP32-S2 bake"*), no removed-code explanations (*"we used to also send Ctrl-C, dropped because…"*), no workstream pointers (*"Step 2 of workbench-deploy-reliability"*) — that belongs in the commit message, the ADR body, or the workstream file, all reachable via `git log` / `plans/`. Applies to docstrings and test-body comments too.
- Audit-pass commits may add general "what this work is doing" framing, but never per-change justification (*"bench-validated -25% allocation"*, *"skips the bytes() copy"*) and never the same comment repeated across many sites. Per-change rationale goes in the commit message body. Flash is ~800 KB total; bloaty comment patterns multiplied across libraries fill it fast.
- A comment so degraded that trimming it again only makes it less legible gets *rewritten from a fresh read of the code*, not subtracted further — repeated trim-only audit passes are how comments rot to illegibility. That rewrite work routes through the [`audit-comments`](.github/skills/audit-comments/SKILL.md) skill (the judgment counterpart to the mechanized comment-lint subset; `/audit-library`'s comment checks detect and trim only).

**Cross-repo isolation**

- No mono-repo references in publishable trees. `libraries/*/`, `workbench/*/`, and `support/test_harness/` ship to PyPI / `circup` / `mip` without the mono-repo. These trees must not name `plans/...md` paths, `Decision NNNN` / `ADR NNNN`, `scripts/run.py`, bare `run.py` (only `chumicro_workspace` legitimately knows about it), or "chumicro mono-repo" framing. Inline a one-line summary instead. Enforced by `CHU006`; suppress only when the reference is genuinely the only useful pointer. `.scratch/` is the *agent* scratch convention (see line 53) — publishable code must never read or write it, as a doc/comment pointer *or* a constructed runtime path; a generated artifact uses the gitignored `_generated/` build-artifact convention instead (acquired chumicro libraries land in *committed* `libraries/`; only the edit-preservation backup tree `_library-backups/` is gitignored — Decision 0078). The `CHU006` `.scratch/` extension is tracked in [`plans/next-up.md`](plans/next-up.md) (routes through `new-decision` per Decision 0074).

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
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`) — the deploy/transport code owns mount state, and manual interference defeats its mount probing + EACCES classifier (a macOS FSKit wedge can leave the volume unmountable). Destructive remediation: `chumicro-workspace reset-board --yes`.
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython) — the runtime re-runs the file every boot, an infinite loop until safe mode (physical replug to recover). Trigger hard reset via raw REPL exec, one-shot, never persisted — the pattern is `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py::_reset_into_bootloader`.
- A `git rm` / `git add` stages immediately and rides into the *next* commit, even a later narrowly-scoped one. Before a scoped commit, `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs. A pre-staged `mqtt/test_client.py` deletion once rode into an unrelated `http_server` split — `main` carried a deleted-but-not-replaced suite for one commit; cost a fixup and a broken-`main` window.

## Working style

- **Anchor claims to evidence** — file, symbol, test, or command. No guessing.
- **Grep is for verifying a specific claim, not for replacing the read on judgment tasks.** When the deliverable is a judgment that requires holding context (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning — split the target into smaller sequential passes; do not switch tools. Token cost is not the success metric when the work *is* the read. Grep is the right primary tool when the deliverable is *finding* something specific (callers of X, occurrences of a pattern); it is the wrong primary tool when the deliverable is *judging* prose, structure, or design. Worked application for code comments: [`audit-comments`](.github/skills/audit-comments/SKILL.md) "Method discipline — read fully, do not grep-shortcut." Other audit-* skills inherit this rule; `audit-publishable-isolation` is exempt (grep is its right primary tool, cross-repo leak hunting).
- **Surface tradeoffs early.** Multiple reasonable approaches → name them. Ambiguity affects correctness → ask. Simpler approach would work → say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates — execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action* — not *skip the destructive-op check*.
- **Clean up after yourself.** Make an import / variable / function / test unused → remove it. Affect docs → update them. But don't fix pre-existing issues unless asked.
- **Re-verify state after recovery actions.** When a fix depends on the user running a recovery action (replug, reset-board, unwedge), re-run the failing detection and the smallest failing test *before* committing. "Done" from the user is the signal to verify, not proof the fix worked.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Cut AI-tic phrases. They sound non-human, drop information, and make prose harder to skim. The fix is usually structural, not vocabulary — when you write *"the X promise"* or *"the X pattern"*, name X concretely in the same sentence. When you catch yourself writing one, rewrite the sentence to *demonstrate* the property concretely instead of asserting it abstractly.

**Degraded prose is rewritten, not trimmed again — the single rule, all prose.** A passage rotted by repeated subtractive edits (each pass removed a word, none asked *what should this say?*) is not fixed by removing another word — that only makes it shorter and no clearer. Discard it and rewrite from a fresh read of what the thing is and why it exists. This is the *why* of the entire comment/doc-audit family: code comments → [`audit-comments`](.github/skills/audit-comments/SKILL.md), user-facing markdown → [`audit-docs`](.github/skills/audit-docs/SKILL.md), SKILL.md bodies → [`audit-skill`](.github/skills/audit-skill/SKILL.md), ADR bodies → in-place edit per [`plans/decisions/README.md`](plans/decisions/README.md). Those skills carry the scope-specific application; this is the rule they apply.

Specific bans:

- **"the canonical promise" / "the canonical pattern"** → just name the promise or pattern. Bad: *"Verifies the canonical promise: an LED keeps blinking…"* Good: *"Verifies the LED-blink invariant: an LED keeps blinking…"*
- **"the canonical X" generally** → check whether *"the X"* or *"the standard X"* is enough. Keep `canonical encoding`, `canonical form`, `canonical path` — real technical terms with no fluff substitute.
- **"the one/single/sole X that …"** as a definition opener → same tic as "the canonical X"; define the thing plainly (*"`run.py` enforces coverage"*, not *"`run.py` is the single mechanism that enforces coverage"*). Applies to comments and docstrings in `src/`, not just prose docs. Tone guidance, not a lint — legitimate invariant prose (*"the single owner of the staging path"*, Decision 0077's *"exactly one mechanism"*) is correct and stays; this is judgement, not a mechanizable matcher (see the CHU020 entry in [`plans/next-up.md`](plans/next-up.md)).
- **"comprehensive" / "robust" / "seamlessly" / "cutting-edge" / "best-in-class"** → drop outright. If a thing is comprehensive, list what it covers; if it's robust, name what it survives.
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
- **`workspace`** — project workspace CLI (composes `deploy` + `repl` + config); starter is the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo
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
| `test-unit-on-device` | Cross-runtime *unit* suite on real boards (the on-device sweep): per-library mode resolution, RAM-preferred, behavioral pass/fail only. `--per-file` acts only in flash/copy sessions (no-op in RAM mode); a per-library on-silicon failure doesn't turn `preflight` red, but a Pico W per-file OOM (CP or MP) is a tracked must-fix per [Decision 0072](plans/decisions/0072-large-test-modules-on-constrained-boards.md), not an accepted end-state |
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

For deeper implementation detail:

- [plans/patterns.md](plans/patterns.md) — implementation cookbooks: Service pattern, recv-buffer + memoryview, lazy adapter selection, FIFO deque, mpremote internals, and more.
- [docs/contributing/style-guide.md](docs/contributing/style-guide.md) — naming, annotations, imports, layout, doc tone.
- [docs/contributing/device-testing.md](docs/contributing/device-testing.md) — functional tests, deploy modes, devices.yml.
- [docs/contributing/releases.md](docs/contributing/releases.md) — VERSION, SemVer, experimental → stable promotion.
- [docs/contributing/pull-requests.md](docs/contributing/pull-requests.md) — PR conventions.

Tests live under each library's `tests/`; shared fakes in `src/chumicro_<name>/testing.py`. On-device tests live under `functional_tests/` and use `support/test_harness/`.

Each library's `VERSION` file is the source of truth — bump only affected libraries. Development code stays as plain `.py`; `.mpy` compilation happens in the release pipeline.
