# ChuMicro Development Ecosystem

> This file is for AI coding agents. Human contributors should use [CONTRIBUTING.md](CONTRIBUTING.md).

## Instruction priority

When instructions overlap, use this order:

1. This file's hard rules
2. The relevant skill in `.github/skills/`
3. Accepted decisions in `plans/decisions/`
4. Repository docs such as the style guide and contributing docs

Before proposing a structural or pattern change, check `plans/decisions/` first.

## Non-negotiable rules

- **After each unit of work:** Run the `task-checkpoint` skill. Preflight must pass, then commit and push. Do not yield with uncommitted changes unless the work is explicitly partial. Do not tell the user work is done with untested or failing changes.
- **Use `git commit -F .scratch/commit-msg.txt`** — not `git commit -m`, so messages can be multi-line and descriptive. Read the `git-commit` skill before every commit. Write the message to `.scratch/commit-msg.txt` with a file tool first.
- **Scratch space:** `.scratch/` is gitignored and safe for temporary files, commit messages, and log captures.
- **Large output:** Pipe through `tail`, `head`, or `grep`. Redirect to `.scratch/` when full output is needed.
- **Disable pagers:** Use `git --no-pager` or `| cat`.
- **Use per-library pytest via `python scripts/run.py test`** — never run bare `pytest` from the repository root.
- **Maintain the coverage gate** per library (threshold is in `pyproject.toml`).
- **No `async`/`await`, no ISRs** — use the tick-based runner pattern from Decision 0014.
- **Use constructor injection** for time, I/O, and network dependencies. Put fakes in the library's `testing.py` submodule. See Decision 0010.
- **Use f-strings everywhere.** Use `const()`, `memoryview`, and pre-allocated buffers in library code only.
- **No single-letter variable names or abbreviated names we spell out** — `_` is the only exception for single-letter names. Human contributors may use single-letter for-loop targets (e.g., `for i in range(10)`), but **agents must always use descriptive names** like `index`, `key`, `value` even in loops. Abbreviations we spell out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`. Enforced by `CHU001` in `scripts/check_names.py`. Suppress with `# noqa: CHU001` only when matching an upstream API. See Decision 0022.
- **Use standard annotations and do not import `typing` in library code** — use PEP 604/585 syntax such as `int | None` and `list[int]`. See Decision 0021.
- **Do not hard-code secrets.**
- **Minimize dependencies** — prefer pure-Python implementations compatible with all three runtimes.
- **Do not use heredocs, `echo`, `printf`, or `cat` to create multi-line content** — write files with file tools, then reference them from the terminal.
- **Do not leave docs, templates, CI, and plans stale** — a feature that exists only in code is incomplete. When you add or change a task, command, library, config, pattern, or behavior, ask: *"If someone reads the docs tomorrow, will they find correct information about this?"* Update whatever your change makes wrong — READMEs, contributing guides, style guide, cheat sheet, CI workflows, scaffold templates, planning docs. Don't limit yourself to a fixed list of files.

## Common pitfalls

- Do not use `pip install -e` manually to fix imports. Run `python scripts/run.py setup`.
- Do not modify unrelated code when fixing a focused bug.

## Working style

- **Do not fabricate.** Verify claims about the codebase by reading the actual code, running tests, or checking command output. If you cannot verify something, say so explicitly rather than guessing.
- **Anchor claims to evidence** — reference a file, symbol, test, or command when making factual statements about how the codebase works.
- **Keep it simple.** Write the minimum code that solves the problem. No features beyond what was asked, no abstractions for single-use code, no speculative error handling. If 200 lines could be 50, rewrite it.
- **Surface tradeoffs early.** If multiple reasonable approaches exist, name them briefly. If ambiguity affects correctness, stop and ask. If a simpler approach would work, say so.
- **Clean up after yourself.** When your changes make an import, variable, function, or test unused, remove it. When your changes affect docs, update them. But do not fix pre-existing issues unless asked — mention them separately instead.

## Agent operations

### Skills

Procedural knowledge lives in `.github/skills/`. Read the relevant skill file before performing the task.

| Skill | When to read it |
|-------|-----------------|
| `git-commit` | Before every commit |
| `task-checkpoint` | After completing a unit of work |
| `debug-test-failure` | When tests fail |
| `large-output` | Before running commands with large output |
| `run-script` | When creating multi-line Python or structured file content |
| `terminal-recovery` | When a terminal command hangs or shows a continuation prompt |
| `new-library` | When adding a new library |
| `new-decision` | When recording a structural or pattern decision |
| `guide-generation` | When writing or refreshing `docs/guide.md` |
| `validate-scripts` | When changing or validating `scripts/` infrastructure |

### Context recovery

At the start of a session:

1. Run `git --no-pager log --oneline -20`
2. Read `plans/next-up.md`
3. Read `plans/roadmap.md` if you need the big picture
4. Check `plans/decisions/` before proposing structural changes
5. Check `plans/open-questions.md` for unresolved relevant threads

Commit history is the primary fallback when planning docs are stale. Write commit messages that help future context recovery.

## Project overview

ChuMicro is a family of open-source Python libraries targeting three runtimes:

- **CircuitPython** and **MicroPython** for embedded boards
- **CPython** for desktop development, testing, and standard tooling

Libraries must be compatible across all three runtimes. If a third-party library does not support CircuitPython or MicroPython, prefer a compatible pure-Python implementation rather than adding a runtime-specific dependency.

## Libraries

| Library | Description |
|---------|-------------|
| [timing](libraries/timing/) | Wraparound-safe millisecond tick helpers, heartbeat scheduling, deterministic test fakes |
| [runner](libraries/runner/) | Tick-based task runner: check/handle gates, periodic tasks, shared timestamps |
| [compat](libraries/compat/) | Cross-runtime compatibility polyfills |
| [msgpack](libraries/msgpack/) | Compact MessagePack serialization with native CircuitPython C module delegation |

## Tech stack

- **Language:** Python 3 subset compatible with CircuitPython and MicroPython
- **Runtimes:** CircuitPython, MicroPython, CPython
- **Testing:** PyTest on host, lightweight on-device runner in `support/test_harness/`
- **Docs:** MkDocs + Material + mkdocstrings, versioned with mike

## Workspace structure

This is a mono-workspace.

- Publishable libraries live under `libraries/<name>/`
- Shared internal packages live under `support/`
- Developer tooling lives under `scripts/`
- Planning docs live under `plans/`

Conventions:

- Publishable libraries use `libraries/<name>/` with `pyproject.toml` and `VERSION`
- Support packages use `support/<name>/` and are not published
- `scripts/run.py` auto-discovers packages by scanning for `pyproject.toml`
- `python scripts/run.py new-library <name>` scaffolds a new library and regenerates IDE configs

### File routing

| Task | Where it goes |
|------|--------------|
| New library | `python scripts/run.py new-library <name>` |
| Shared infrastructure | `support/` |
| Build / CI tooling | `scripts/` |
| Design decision | `plans/decisions/NNNN-<slug>.md` |
| Docs assets | `support/docs/` |

### Key commands

| Command | Purpose |
|---------|---------|
| `python scripts/run.py setup` | Install dependencies and regenerate IDE configs |
| `python scripts/run.py preflight` | Full CI mirror |
| `python scripts/run.py test` | CPython tests |
| `python scripts/run.py test-scripts` | Run scripts infrastructure tests |
| `python scripts/run.py lint` | Ruff across the workspace |
| `python scripts/run.py build` | Build publishable packages |
| `python scripts/run.py sync-ide` | Regenerate IDE configs |
| `python scripts/run.py docs` | Build library docs |
| `python scripts/run.py docs-preview` | Serve versioned local docs preview |
| `python scripts/run.py docs-deploy --channel <ch>` | Deploy versioned docs |
| `python scripts/run.py validate-mip --bundle-repo <repo>` | Validate mip install + import against a live bundle repo |
| `python scripts/run.py validate-mip --staging-dir <dir>` | Validate mip install + import from locally staged bundle |
| `python scripts/run.py new-library <name>` | Scaffold a new library |
| `python scripts/run.py prepare-micropython` | Prepare MicroPython unix-port |
| `python scripts/run.py prepare-circuitpython` | Prepare CircuitPython unix-port |
| `python scripts/run.py prepare-mpy-cross` | Build mpy-cross compilers for both runtimes |
| `python scripts/run.py verify-examples` | Import-check example scripts |
| `python scripts/run.py test-micropython-compatibility` | MicroPython cross-runtime unit tests |
| `python scripts/run.py test-circuitpython-compatibility` | CircuitPython cross-runtime unit tests |
| `python scripts/run.py test-runtime-matrix` | Test all packages on CPython + MicroPython + CircuitPython |
| `python scripts/run.py test-device` | Device validation information |
| `python scripts/run.py check-version` | Check VERSION enforcement for changed libraries |
| `python scripts/run.py check-api` | Check API breakages against last release tag |

## Development guidance

This file is the operational summary. Use the authoritative docs and decisions for full detail.

### Library code versus infrastructure code

- **Library code under `libraries/`** runs on constrained devices. Use embedded-conscious patterns there.
- **Infrastructure code under `scripts/`** is CPython-only. Prefer normal Python clarity there.
- **`support/test_harness/`** must remain compatible with all three runtimes.

### Performance and memory rules for library code

- Pre-allocate reusable buffers
- Use `memoryview` to avoid copies
- Avoid dynamic string building in loops
- Use `const()` for numeric constants where appropriate
- Cache frequently used attributes in hot paths
- Call `gc.collect()` deliberately in long-running tasks when needed

### Style and annotations

Follow `docs/contributing/style-guide.md`. The naming, annotation, and docstring rules are in Non-negotiable rules above (Decision 0021, Decision 0022).

### API and compatibility

- Prefer CPython-compatible API naming
- Do not add non-CPython APIs into standard-library-shaped modules
- Avoid `u*` naming such as `usocket`
- Prefer one implementation across runtimes with thin shims where needed

### Networking and scheduling

- All network I/O must be non-blocking
- Use `sock.setblocking(False)` and `select.Poll`
- Handle `POLLHUP` and `POLLERR` promptly
- Read and write incrementally
- Poll once per tick and return quickly

### Storage and logging

- Batch writes and defer them to idle periods
- Do not write to flash in tight loops
- Provide configuration hooks such as `config.py`
- Keep logging lightweight and avoid noisy tight-loop logging

## Testing strategy

Use `python scripts/run.py test` for host-side tests.

Key rules:

- Tests live under each library's `tests/`
- Shared fakes belong in `src/chumicro_<name>/testing.py`
- Do not mock what you do not own when usable upstream fakes already exist

See Decision 0009 and Decision 0010.

On-device tests live under `functional_tests/` and use `support/test_harness/`.

## Versioning and releases

- Use Semantic Versioning
- Each library's `VERSION` file is the source of truth
- Bump only affected libraries
- Keep development code as plain `.py`; `.mpy` compilation happens in the release pipeline

## Board support

Minimum supported class:

- 256 KB MCU RAM
- 4 MB flash

See Decision 0015 for support tiers and details. Use `sys.platform` or feature checks for runtime detection and provide clear fallbacks or errors when features are missing.

## Reference implementations

Pinned local clones of runtime source trees live under `.tools/` and are gitignored.

Use:

- `python scripts/run.py prepare-micropython`
- `python scripts/run.py prepare-circuitpython`

Browse these first when inspecting C implementations or built-in module behavior.

## Planning documents

Planning docs under `plans/` are part of the repository's working state. See `plans/README.md` for the full index.

Key files:

- `plans/decisions/` — durable decisions affecting future work
- `plans/history.md` — build-up timeline and design history
- `plans/next-up.md` — active execution queue
- `plans/open-questions.md` — unresolved questions
- `plans/patterns.md` — reusable implementation patterns
- `plans/roadmap.md` — milestone status

Housekeeping rules:

- Move checked-off items in `plans/next-up.md` into the top of `Done` in the same edit
- When revisiting an earlier decision, reference it explicitly
- When a decision resolves an open question, update `plans/open-questions.md`

## Contributing and code review

1. Keep PRs small and focused
2. Include tests and documentation with behavior changes
3. Do not commit build artifacts, bytecode, or secrets
4. Write commit messages that aid context recovery — imperative subject, body explaining why, and the affected libraries, decisions, or workstreams
