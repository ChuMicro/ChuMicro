# Chumicro Development Ecosystem

## Quick reference

Hard rules an agent must never violate:

- **Verify before declaring done** — after making changes, run `task-checkpoint` (tests + commit).  Before ending a session, run `end-of-session` (preflight + clean tree).  Do not tell the user "done" with uncommitted or untested changes.
- **Preflight must pass before you stop** — `python scripts/run.py preflight 2>&1 | tail -5` must show `Preflight passed`.  If it fails, fix it.
- **`git commit -F .scratch/commit-msg.txt`** — never `git commit -m` (see `.github/skills/git-commit/SKILL.md`).
- **Per-library pytest** via `python scripts/run.py test` — never bare `pytest` from root.
- **94 % coverage gate** per library.
- **No `async`/`await`, no ISRs** — use the tick-based runner pattern (Decision 0014).
- **Constructor injection** for time, I/O, network — fakes in `testing.py` submodule (Decision 0010).
- **f-strings everywhere**, `const()` / `memoryview` / pre-allocated buffers in library code only.
- **Standard annotations, no `typing` imports** — use type annotations on signatures; do not `import typing` in library code (Decision 0021).  Use PEP 604/585 syntax (`int | None`, `list[int]`).  Docstrings carry descriptions only — **`Args:`** uses `name: description`, **`Returns:`** uses just a description.
- **Check `plans/decisions/`** before proposing structural or pattern changes.
- **Never hard-code secrets.**
- **No `pip install -e`** — IDE resolution uses generated configs (`sync-ide`).
- **Minimize dependencies** — prefer pure-Python implementations compatible with all three runtimes.

Common pitfalls:

- Don't tell the user you're done with uncommitted changes or without running tests — read the `task-checkpoint` and `end-of-session` skills.
- Don't run bare `pytest` from root — use `python scripts/run.py test`.
- Don't add `pip install -e` to fix imports — run `python scripts/run.py sync-ide`.
- Don't propose `asyncio`-based solutions — the project forbids `async`/`await`.
- Don't apply embedded patterns (`const()`, `memoryview`) to infrastructure code under `scripts/` or `support/`.
- Don't modify unrelated code when fixing a bug.
- Don't re-propose something already decided in `plans/decisions/` without referencing the original decision.
- Don't use heredocs, `echo`, `printf`, or `cat` to create multi-line content in the terminal — write files with file tools instead (see `run-script` skill).
- Don't run large-output commands (`preflight`, `test --all`, `lint`) without piping through `tail`, `head`, or `grep` (see `large-output` skill).

## Agent operations

### Skills

Procedural knowledge lives in `.github/skills/`.  **Read the relevant skill file before performing the task** — the rules there override general knowledge.

| Skill | When to read it |
|-------|-----------------|
| `git-commit` | **Every commit.** Never `git commit -m`.  The skill defines the full write → stage → commit procedure. |
| `end-of-session` | Before finishing work — preflight, VERSION bumps, planning doc audit, clean tree. |
| `task-checkpoint` | After completing a unit of work — quick validation and optional commit before yielding. |
| `debug-test-failure` | When tests fail — isolation, re-run, coverage gaps, cross-runtime diagnostics. |
| `large-output` | When running commands whose output may exceed the terminal buffer — pipe patterns. |
| `run-script` | When you need multi-line Python or structured file content — never use heredocs or terminal input. |
| `terminal-recovery` | When a terminal command hangs or shows a continuation prompt — Ctrl-C and retry. |
| `new-library` | Full lifecycle for adding a library — scaffolding through release-ready. |
| `new-decision` | Recording a structural or pattern tradeoff in `plans/decisions/`. |
| `guide-generation` | Writing or refreshing `docs/guide.md` for a library. |
| `validate-scripts` | Writing and running validation tests for `scripts/` infrastructure. |

### Context recovery

At the start of a session, orient yourself:

1. `git --no-pager log --oneline -20` — what changed recently.
2. Read `plans/next-up.md` — active work, priorities, blockers.
3. Check `plans/sessions/` for recent session logs — what was discussed, what's unfinished.
4. Read `plans/roadmap.md` if you need the big picture.
5. Check `plans/decisions/` before proposing structural changes — the decision may already exist.
6. Check `plans/open-questions.md` for unresolved threads relevant to your task.

Commit history is the primary fallback when planning docs are stale.  Write commit messages accordingly (see Contributing below).

### Completion protocol

**After every unit of work** (feature, fix, refactor), run the `task-checkpoint` skill before telling the user you're done.  The short version:

1. `git status --short` — review what changed.
2. Run the narrowest test that covers your changes (see the skill for the table).
3. Commit and push if the work is coherent.  Read the `git-commit` skill for mechanics.

**Before ending a session**, run the `end-of-session` skill.  The short version:

1. `python scripts/run.py preflight 2>&1 | tail -5` — must show `Preflight passed`.
2. Check VERSION bumps for changed libraries.
3. Commit any remaining work.  `git status --short` must produce no output.

**Do not skip these.**  Telling the user "done" with failing tests or uncommitted changes is a hard failure.

### Terminal rules

- **`.scratch/` is agent scratch space** — gitignored, safe for temporary files, commit messages, and log captures.
- **Never use heredocs, `echo`, `printf`, or `cat`** to create multi-line content.  Write files with file tools, then reference them from the terminal.
- **Pipe large output** through `tail`, `head`, or `grep`.  Redirect to `.scratch/` when full output is needed.
- **Disable pagers:** `git --no-pager`, `| cat`.
- If a terminal hangs, send Ctrl-C.  See the `terminal-recovery` skill.

## Project overview

Chumicro is a family of open-source Python libraries targeting three runtimes:

- **CircuitPython** and **MicroPython** for embedded boards (ESP32-S2, ESP32-S3, RP2040, etc.).
- **CPython** for desktop development, testing (PyTest), and standard tooling.

Libraries must be compatible across all three runtimes.  If a third-party library doesn't support CircuitPython/MicroPython, re-implement the functionality rather than importing it.

## Libraries

| Library | Version | Description |
|---------|---------|-------------|
| [timing](libraries/timing/) | 0.1.16 | Wraparound-safe millisecond tick helpers, heartbeat scheduling, deterministic test fakes |
| [runner](libraries/runner/) | 0.1.16 | Tick-based task runner: check/handle gates, periodic tasks, shared timestamps — no async |
| [compat](libraries/compat/) | 0.1.16 | Cross-runtime compatibility polyfills — `functools.partial` and more |
| [msgpack](libraries/msgpack/) | 0.1.16 | Compact MessagePack serialization with native CircuitPython C module delegation |

## Tech stack

- **Language:** Python 3 (subset compatible with CircuitPython & MicroPython).  PEP 8 naming.
- **Runtimes:** CircuitPython, MicroPython, CPython.  Pinned versions in `target-runtimes.toml`.
- **Testing:** PyTest (host), lightweight on-device runner in `support/test_harness/`.
- **Docs:** MkDocs + Material + mkdocstrings.  Per-library `mkdocs.yml`.  Versioned with [mike](https://github.com/jimporter/mike) via `docs-deploy.yml`.  Preview locally with `python scripts/run.py docs-preview`.

## Workspace structure

Mono-workspace.  Each publishable library lives under `libraries/<name>/` with `src/`, `tests/`, `functional_tests/`, `docs/`, and `examples/`.  Shared internal packages live under `support/`.  Developer tasks in `scripts/`.  Planning docs in `plans/`.

Conventions:

- Publishable libraries: `libraries/<name>/` with `pyproject.toml` and `VERSION` file.
- Support packages: `support/<name>/` — workspace-internal, not published.
- `scripts/run.py` auto-discovers all packages by scanning for `pyproject.toml`.  No hard-coded lists.
- `python scripts/run.py new-library <name>` scaffolds a new library and regenerates IDE configs.

### File routing

| Task | Where it goes |
|------|--------------|
| New library | `python scripts/run.py new-library <name>` |
| Shared infra | `support/` |
| Build / CI tooling | `scripts/` |
| Design decision | `plans/decisions/NNNN-<slug>.md` |
| Docs assets (CSS, favicon) | `support/docs/` |

### Key commands

| Command | Purpose |
|---------|---------|
| `python scripts/run.py setup` | Install dependencies and regenerate IDE configs |
| `python scripts/run.py preflight` | Full CI mirror: lint, build, docs, test, examples, version-check, api-check, compat |
| `python scripts/run.py test` | CPython tests (changed packages, or `--all` / `--libraries name`) |
| `python scripts/run.py lint` | Ruff across workspace |
| `python scripts/run.py build` | Build all publishable packages |
| `python scripts/run.py sync-ide` | Regenerate PyCharm / VS Code configs |
| `python scripts/run.py docs` | Build library docs |
| `python scripts/run.py docs-preview` | Deploy to local gh-pages and serve versioned preview |
| `python scripts/run.py docs-deploy --channel <ch>` | Deploy versioned docs (CI) |
| `python scripts/run.py new-library <name>` | Scaffold a new library |

## Development guidelines

### Memory & performance (library code only)

These rules apply to **publishable library code under `libraries/`** — code that runs on microcontrollers.  Infrastructure code (`scripts/`, `support/`) should follow standard Python conventions instead (see next section).

1. **Pre-allocate buffers:** Allocate a `bytearray` once in the constructor and reuse it with `readinto()`.
2. **Use `memoryview` for slicing:** Avoids copies; use instead of `bytearray` slicing.
3. **Avoid dynamic string building in loops.**
4. **f-strings exclusively** for string formatting.  `%`-style only when f-strings are unavailable.
5. **`const()` for numeric constants:** Import from `micropython`.  Prefix internal constants with `_`.
6. **Cache frequently used attributes** in local variables within performance-critical methods.
7. **Control garbage collection:** Call `gc.collect()` periodically in long-running tasks.

### Infrastructure code

Code under `scripts/` and `support/` runs **exclusively on CPython**.  Use the full standard library freely.  Do **not** use `const()`, `memoryview`, pre-allocated buffers, or other embedded patterns.  Prefer f-strings for readability.

### Naming & style

PEP 8.  Descriptive names (`service`, `test_device`), not abbreviations (`svc`, `dut`).  Document **all** functions and methods with concise docstrings.  Use standard Python type annotations on function signatures (Decision 0021).  Do not `import typing` in library code — use PEP 604 (`int | None`) and PEP 585 (`list[int]`) syntax instead.  Docstrings use Google-style sections for descriptions: `Args:` uses `name: description`, `Returns:` uses just the description, `Raises:` uses `ExceptionType: description`.  When writing CircuitPython drivers: initialize hardware in `__init__`, provide `deinit()` or context-manager support.

### API & compatibility

Follow CPython's API names for portable functionality.  Do not add non-CPython APIs to the same module — create separate modules for microcontroller-specific features.  Avoid the `u*` prefix convention (e.g., `usocket`); choose a distinct name.

### Platform abstraction & shims

Prefer a single implementation across all runtimes.  When platform differences exist, write a thin shim that detects the runtime (via `sys.platform` or feature checks) and imports the correct backend.  Keep function names aligned with CPython's standard library.  Minimize dependencies.

### Networking & non-blocking I/O

All network operations must be non-blocking.  Use `sock.setblocking(False)` and `select.Poll` to multiplex I/O.  Handle `POLLHUP`/`POLLERR` immediately.  Read and write incrementally into pre-allocated buffers.  Integrate with the tick scheduler — poll once per tick, return quickly.

### Long operations & storage

Batch writes and defer them to idle periods.  Do not write to flash in tight loops (flash wear).  Break long computations into smaller steps across multiple ticks.

### Scheduling & concurrency

No `async`/`await`.  No ISRs.  Use the tick-based runner pattern (Decision 0014): services implement `check(now_ms) -> bool`, the `Runner` captures time once per tick and dispatches handlers in batch.  Use polling and helper modules like `countio`/`keypad` for state change detection.

### Secrets & configuration

Never hard-code secrets.  Provide configuration hooks so users store credentials in a separate file on the device (e.g., `config.py` with `wifi_ssid` / `wifi_password`).

### Logging

Provide a lightweight logging facility with levels (`ERROR`, `WARNING`, `INFO`, `DEBUG`).  Use f-strings.  Don't log in tight loops.

## Testing strategy

### Host-based unit tests (PyTest)

1. Tests go under `tests/` inside each library.
2. Per-library pytest runs avoid test-directory collisions (Decision 0009).  `scripts/run.py test` runs a separate subprocess per package.
3. 94 % coverage threshold per library.
4. Root `conftest.py` auto-discovers `src/` directories and adds them to `sys.path`.
5. Shared test fakes ship as `testing` submodules (e.g., `from chumicro_timing.testing import FakeTicks`).

### Library testability rules (Decision 0010)

- **Constructor injection** — classes that depend on time, I/O, or network accept those as constructor parameters.
- **Provide fakes for things you own** — `src/chumicro_<name>/testing.py` with ready-made fakes.
- **Don't mock what you don't own** — use the upstream library's provided fakes.

### On-device tests

Lightweight runner in `support/test_harness/`.  Tests under `functional_tests/` per library.

### CI pipeline

PRs and pushes to `main` run: lint (Ruff), test (CPython 3.11/3.12/3.13), verify-examples, docs-build (PRs), build, version-check, api-check, MicroPython compat, CircuitPython compat.

## Versioning & releases

[Semantic Versioning](https://semver.org/).  Each library's `VERSION` file is the single source of truth.  `pyproject.toml` reads from it dynamically.

Bump rules: `major` for breaking changes, `minor` for new features, `patch` for bug fixes.  Bump only affected libraries.

Releases are automated: bump `VERSION` and merge to `main` for experimental; run `promote.yml` for stable.  Release workflow publishes to PyPI, creates tags, deploys to bundle repos, and publishes docs.

Keep code as plain `.py` during development.  `.mpy` compilation happens in the release pipeline via `mpy-cross`.

## Board support

Minimum: 256 KB MCU RAM, 4 MB flash.  See Decision 0015 for tier details.

- **Tier 1:** ESP32, ESP32-S3, ESP32-C6, RP2350, ESP32-S2/C3 with PSRAM.
- **Tier 2:** RP2040, ESP32-S2/C3 without PSRAM.
- **Unsupported:** SAMD21, SAMD51, nRF52, ESP8266, small STM32.

Use `sys.platform` or feature checks for runtime detection.  Provide fallbacks or clear errors when features are missing.

## Reference implementations

Local clones of pinned runtime source trees live under `.tools/` (gitignored).  Run `python scripts/run.py prepare-micropython` / `prepare-circuitpython` to set them up.  Browse these first when inspecting C implementations or built-in module behavior.

## Planning documents

Planning docs under `plans/` are part of the repository's working state.  See `plans/README.md` for the full index.

- `plans/decisions/` — durable decisions affecting future work
- `plans/history.md` — design principles, rejected approaches, build-up timeline
- `plans/next-up.md` — active execution queue
- `plans/open-questions.md` — unresolved questions that need thought but aren't blocking
- `plans/patterns.md` — reusable implementation patterns with code examples
- `plans/roadmap.md` — milestone status
- `plans/sessions/` — session logs for context that doesn't survive in commits alone

**`next-up.md` housekeeping:** move checked-off items from Now/Next/Blocked to the top of Done in the same edit.

**Before proposing structural changes**, check `plans/decisions/` for existing decisions.  If revisiting, reference the original decision explicitly.

**When a decision resolves an open question**, update `plans/open-questions.md` — move the question to Resolved with a one-line answer and link.

## Contributing & code review

1. Keep PRs small and focused.  Include tests and documentation.
2. Code review checks: style, coverage, memory usage, API consistency across runtimes.
3. Do not commit build artifacts, bytecode, or secret configuration files.
4. **After completing a unit of work**, run the `task-checkpoint` skill — validate, commit, push.  Do not yield to the user with uncommitted changes unless the work is explicitly partial.
5. **Before ending a session**, run the `end-of-session` skill — preflight, VERSION bumps, planning doc audit, clean tree.  Preflight must pass.  Tree must be clean.
6. **Write commit messages that aid context recovery** — imperative subject, body explaining *why*, name affected libraries/decisions/workstreams.  A future agent scanning `git log` should be able to reconstruct project state.
7. **Commit mechanics:** Read the `git-commit` skill before every commit.  Never `git commit -m`.  Write the message to `.scratch/commit-msg.txt` with a file tool, then `git commit -F .scratch/commit-msg.txt`.
