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
- **Maintain the coverage gate** per library — the human baseline is 85 % (configured in `pyproject.toml`). **Agents must pass `--coverage-threshold 94`** on every `test` and `preflight` invocation (Decision 0025). Use `# pragma: no cover` where code genuinely cannot be exercised in CPython tests (runtime-only branches, hardware fallbacks) — see the [coverage exclusions](docs/contributing/style-guide.md#coverage-exclusions) section in the style guide.
- **No `async`/`await`, no ISRs** — use the tick-based runner pattern from Decision 0014.  Every device library that owns time or I/O must be runner-shaped per [Decision 0051](plans/decisions/0051-runner-shaped-as-project-policy.md) (no `time.sleep(N)` for `N > 0.005`, no `select.poll(timeout > 0)`, no synchronous DNS that doesn't yield).
- **Use constructor injection** for time, I/O, and network dependencies. Put fakes in the library's `testing.py` submodule. See Decision 0010.
- **Use f-strings everywhere.** Use `const()`, `memoryview`, and pre-allocated buffers in library code only.
- **No single-letter variable names or abbreviated names we spell out** — `_` is the only exception for single-letter names. Human contributors may use single-letter for-loop targets (e.g., `for i in range(10)`), but **agents must always use descriptive names** like `index`, `key`, `value` even in loops. Abbreviations we spell out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`. Enforced by `CHU001` in `scripts/check_names.py`. Suppress with `# noqa: CHU001` only when matching an upstream API. See Decision 0022.
- **Use standard annotations and do not import `typing` in library code** — use PEP 604/585 syntax such as `int | None` and `list[int]`. **Do not write `from __future__ import annotations` in `libraries/*/src/` or `support/test_harness/src/`** — MicroPython has no `__future__` module and the import fails before annotations are evaluated. CPython-only trees (tests, scripts, workbench) may keep it. See Decision 0021.
- **Absolute imports only in code that runs on devices.** `libraries/*/src/` and `support/test_harness/` must use `from chumicro_foo.bar import baz`, never `from .bar import baz`. Relative imports break CircuitPython RAM-mode deploys — library modules are `exec()`'d without a `__package__`, so a leading `.` has nothing to resolve against. Workbench packages (`workbench/*/src/`) and tests may use either style. Enforced by ruff TID252; the `[tool.ruff.lint.per-file-ignores]` table in `pyproject.toml` relaxes the rule for `workbench/`, `scripts/`, `tests/`, `functional_tests/`, and `examples/` paths. See the style guide's "Imports" section for the full explanation.
- **Mark runtime-specific files with `__chumicro_runtimes__`.** Files under `libraries/*/src/` whose body only makes sense on one runtime (e.g. an adapter that does `import wifi`, a backend that does `import esp32`) declare a module-level `__chumicro_runtimes__ = ("circuitpython",)` (or `("micropython",)`, `("cpython",)`, etc.).  The marker is read via AST (no execution) by both the bundle pipeline (universal source bundle + per-runtime mpy bundles for circup / mip) **and** every host-side deploy path (`chumicro_workspace deploy`, `chumicro_deploy` CLI, pytest-device staging, examples, functional tests) — the wrong-runtime file never lands on the device.  Files without a marker ship everywhere (default-safe).  Test fakes go in `testing.py`, which declares `__chumicro_runtimes__ = ("cpython",)` so it lands only in the PyPI sdist / wheel — not in any bundle, not in any device deploy.  PyPI sdists and wheels always ship every file under `src/` unfiltered (every adapter, every backend, every fake) — `pip install chumicro-foo` on a CPython host gets the complete library.  See [Decision 0037](plans/decisions/0037-runtime-file-marking.md) and [Decision 0044](plans/decisions/0044-deploy-time-runtime-filtering.md).
- **Do not hard-code secrets.**
- **No backward-compatibility burden — pre-publish freedom.**  Nothing has shipped to PyPI yet (every library + workbench package is at a 0.x version with no real downstream users), so format / flag / layout / API changes ship cleanly.  Don't add migration logic, deprecation shims, dual-read paths, "old shape still accepted" branches, or compat re-exports.  Edit forward.  This rule retires when the first stable (1.0+) release lands; until then, treat compat code as drag.
- **Minimize dependencies** — prefer pure-Python implementations compatible with all three runtimes.
- **Workbench packages do not import library packages** — `workbench/<name>/src/` files must not `import chumicro_<libname>` from `libraries/`.  Use third-party PyPI equivalents (`pyserial`, `pyyaml`, `ruamel.yaml`, `msgpack`, etc.).  Templates / on-device payloads embedded as bytes are fine — that's payload, not import.  See [Decision 0052](plans/decisions/0052-workbench-no-library-imports.md).
- **Workbench tools that touch hardware classify failures** — every host-side tool exposes a closed-set failure-kind enum + classifier + recovery plans in `<package>.recovery`, and CLIs wrap entry points in coaching loops.  Generic `raise Exception` in workbench code is a UX defect.  See [Decision 0053](plans/decisions/0053-recovery-layer-philosophy.md); concrete instances in [Decision 0033](plans/decisions/0033-macos-circuitpy-deploy-hardening.md) and [Decision 0039](plans/decisions/0039-firmware-version-floor.md).
- **No mono-repo references in publishable library / workbench trees** — `libraries/*/`, `workbench/*/`, and `support/test_harness/` ship to PyPI / CircuitPython-bundle consumers who don't have the mono-repo checked out.  These trees must not point at `plans/...md` paths anywhere (docs, README, tests, pyproject.toml, src), and `src/` specifically must not name `Decision NNNN`, mention `scripts/run.py` (the mono-repo's developer command runner), name a bare `run.py` (the workspace-template's shim — only `chumicro_workspace` legitimately knows about it; everywhere else, name the installable CLI like `chumicro-deploy` instead), or use "chumicro mono-repo" framing.  Inline a one-line summary instead of cross-linking; rationale and history belong in commit messages.  Enforced by `CHU006` in [`scripts/check_no_repo_refs.py`](scripts/check_no_repo_refs.py): `plans/...` patterns fire across every package file, the rest are `src/`-only today (widening to docs / tests / pyproject is a tracked follow-up).  Suppress with `# noqa: CHU006` (Markdown: `<!-- noqa: CHU006 -->`) only when the reference is genuinely the only useful pointer (rare).
- **Workbench packages do not import library packages** — `workbench/*/src/` files must not `import chumicro_<libname>` from a `libraries/` package (Decision 0052).  Workbench is host-only and ships to laptops; libraries target devices and their CPython compatibility exists for testing/dev, not as a production runtime.  Use third-party PyPI equivalents (`pyserial`, `msgpack`, `ruamel.yaml`, etc.).  Templates / on-device payloads embedded as bytes are fine — that's payload, not import.  Enforced by `CHU007` in [`scripts/check_workbench_no_lib_imports.py`](scripts/check_workbench_no_lib_imports.py).  Suppress with `# noqa: CHU007` only on legitimate payload-style imports (rare).
- **Test skips must be loud, never silent** — bare `if <cond>: return` / `pass` from a test body is reported as PASS by the runner, hiding regressions.  Use `chumicro_test_harness.skip(reason)` for runtime skips (works under both the harness and pytest), declare runtime / per-board capability filters via module-level `__chumicro_runtimes__` / `__chumicro_features__` markers for collection-time gating, or `raise AssertionError(...)` if reaching the line is a conftest bug.  Every test must contain at least one assertion / raise / skip / fail / `with raises(...)`.  Enforced by `CHU009` (no bare-return in test body) + `CHU010` (every test asserts) in [`scripts/check_no_silent_test_skip.py`](scripts/check_no_silent_test_skip.py); both rules scope to `libraries/<name>/{tests,functional_tests}/`.  Suppress with `# noqa: CHU009` / `# noqa: CHU010` only when documenting why the test is genuinely an exception (rare).  See [Decision 0058](plans/decisions/0058-test-skips-must-be-loud.md).
- **Plans-doc brevity — `next-up.md` is the agent-managed work queue** — single source of truth for what's in flight, queued, blocked, or recently done.  Every top-level bullet is capped at 5 bullet markers (lead + sub-bullets together); anything bigger gets promoted to a workstream file under `plans/workstreams/` (open) or `plans/workstreams/archive/` (shipped) and replaced here by a one-line pointer.  `## Done (recent)` is capped at 25 entries — drop the oldest when adding a new one (commit messages + workstream archives keep the durable record).  Session warm-up: `git --no-pager log --oneline -20` then [`plans/next-up.md`](plans/next-up.md).  Enforced by `CHU011` in [`scripts/check_plans_brevity.py`](scripts/check_plans_brevity.py).  Suppress with `<!-- noqa: CHU011 -->` (sparingly).
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

Procedural knowledge lives in `.github/skills/` (the canonical home).  The same tree is also reachable at `.claude/skills/` via a symlink so Claude Code auto-discovers them there — read whichever path your tooling prefers; both resolve to the same files.

Read the relevant skill file before performing the task.

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
| `audit-library` | Code-quality audit on one library — duplication, abstraction honesty, method shape, dead code, top-to-bottom readability |
| `audit-integration` | Code-quality audit across two or more interacting libraries — boundary shapes, dependency direction, parallel implementations |
| `audit-workspace` | Code-quality audit at the mono-repo / ecosystem level — library-shape inventory, cross-library patterns, decision-ADR drift, workstream candidates |
| `audit-publishable-isolation` | Cross-repo audit for leaks of mono-repo-internal concepts (run.py / scripts/ / plans/ / Decision NNNN / upstream-repo names) into shipped artifacts — covers the seven leak patterns CHU006 doesn't catch (READMEs, bare run.py, reverse-direction template→mono-repo coupling, generator-output) |

`end-of-session` lives under `.github/skills/` for human contributors only — agents should use `task-checkpoint` after each unit of work instead.

### Context recovery

At the start of a session:

1. Run `git --no-pager log --oneline -20`
2. Read `plans/next-up.md`
3. Check `plans/decisions/` before proposing structural changes
4. Check `plans/open-questions.md` for unresolved relevant threads

Commit history is the primary fallback when planning docs are stale. Write commit messages that help future context recovery.

## Project overview

ChuMicro is a family of open-source Python libraries targeting three runtimes:

- **CircuitPython** and **MicroPython** for embedded boards (deployment runtimes).
- **CPython** for desktop development, testing, fakes, and the workbench tooling — the host-test seam, not a deployment target.  See [Decision 0049](plans/decisions/0049-three-runtime-trinity.md).

Libraries must be compatible across all three runtimes.  If a third-party library does not support CircuitPython or MicroPython, prefer a compatible pure-Python implementation rather than adding a runtime-specific dependency.

## Libraries (cross-runtime, run on a microcontroller)

| Library | Description |
|---------|-------------|
| [timing](libraries/timing/) | Wraparound-safe millisecond tick helpers, heartbeat scheduling, deterministic test fakes |
| [runner](libraries/runner/) | Tick-based task runner: check/handle gates, periodic tasks, shared timestamps |
| [compat](libraries/compat/) | Cross-runtime compatibility polyfills |
| [logging](libraries/logging/) | Levelled logging — runner-friendly, no chumicro deps; per-logger levels with hierarchy resolution |
| [events](libraries/events/) | Runner-shaped pub/sub event bus (bounded, drop-oldest); zero chumicro deps and no other library imports it ([Decision 0042](plans/decisions/0042-library-dependency-policy.md)) |
| [msgpack](libraries/msgpack/) | Compact MessagePack serialization with native CircuitPython C module delegation; wire-compatible subset of PyPI `msgpack(use_single_float=True)` |
| [config](libraries/config/) | Standardized `from_dict` + on-device `runtime_config.msgpack` reader; section-namespaced runtime-config convention (Decisions [0035](plans/decisions/0035-runtime-config-structure.md) / [0036](plans/decisions/0036-chumicro-config-library.md)) |
| [kvstore](libraries/kvstore/) | Mapping-shaped persistent key-value store with `auto` / `nvm` / `nvs` / `littlefs` / `memory` backends; CRC-framed CP NVM; atomic LittleFS commits ([Decision 0034](plans/decisions/0034-kvstore-api-and-backends.md)) |
| [wifi](libraries/wifi/) | Sole-supervisor WiFi service with state machine + reconnect supervisor; per-runtime adapters for CP, substrate-aware MP (auto-detects ESP-IDF vs CYW43), and CPython fake (commit `0304542` unified the previously-split MP-ESP32 / MP-RP2 adapters) |
| [sockets](libraries/sockets/) | Cross-runtime TCP + TLS + UDP sockets — one protocol per shape over CP `socketpool`, MP `socket`+`ssl`, and CPython stdlib ([Decision 0031](plans/decisions/0031-chumicro-sockets.md)); `ssl_context_with_ca` defaults to `CERT_REQUIRED`, `ssl_context_with_cert_and_key_paths` for CP/MP server-side TLS |
| [ntp](libraries/ntp/) | Runner-shaped SNTP client over an injected UDP socket; pure-Python, cross-runtime |
| [requests](libraries/requests/) | Non-blocking HTTP/1.1 client built on `chumicro-sockets` + `chumicro-timing`; LED keeps blinking through TLS handshake / mid-timeout / stalled peer; runner-shaped state machine |
| [http_server](libraries/http_server/) | Non-blocking HTTP/1.1 server built on `chumicro-sockets` + `chumicro-timing`; per-connection state machine advanced one chunk per tick; `@server.route` decorator with method dispatch + path params; TLS server supported on every runtime/board pair *except* CP-on-rp2 (`chumicro_sockets.tls_listening_socket` raises `UnsupportedSSLConfigError` there — use ESP32-family or MicroPython-on-rp2 for HTTPS) |
| [mqtt](libraries/mqtt/) | Non-blocking MQTT 3.1.1 client (QoS 0 + 1) on top of `chumicro-sockets` + `chumicro-timing`; runner-shaped `check`/`handle`; per-`packet_id` in-flight QoS 1 tracking; `recv_budget_per_tick` + `max_tx_queue_size` for cooperative-tick fairness; `WhenOversized` policy enum; `MQTTBackpressureError` on TX overflow |

## Workbench (host-only, run on a laptop)

| Package | Description |
|---------|-------------|
| [deploy](workbench/deploy/) | Push code to a board, probe identity, flash firmware (UF2 + esptool); recovery layer that classifies failures and walks the user through fixes |
| [repl](workbench/repl/) | Serial REPL with traceback highlighting, an `mpremote`-compatible TUI, `tail()` follow-mode for deploy orchestration, programmatic `ReplSession` |
| [workspace](workbench/workspace/) | One-stop host CLI + Python API for ChuMicro project workspaces — `init` clones a starter, `setup` creates the venv + materializes the workbench-owned starters (`devices.yml` / `workspace.yml` / `secrets.toml`), plus `add-device`, `deploy` (single project, `--all-devices`, or `--all-projects`), `repl <project>` (deploy-then-tail one-shot), `install-firmware`, `status` / `doctor` health checks, `new --library` / `new --from`, path-aware `rename`, `update` (re-flow tool-owned files from upstream).  Canonical starter lives at the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) repo (Decision 0038) |
| [pytest-device](workbench/pytest-device/) | Pytest plugin that intercepts collection under `functional_tests/`, stages source onto a connected CP / MP board via `chumicro-deploy`, runs the test in the device runtime, and parses the result back; auto-registers via `pytest11`; reads `devices.yml` (carved out of `scripts/{pytest_device,result_parser,device_testing}.py` 2026-04-27, commit `3e01cbf`) |

## Tech stack

- **Language:** Python 3 subset compatible with CircuitPython and MicroPython
- **Runtimes:** CircuitPython, MicroPython, CPython
- **Testing:** PyTest on host, lightweight on-device runner in `support/test_harness/`
- **Docs:** Zensical + mkdocstrings, versioned with mike

## Workspace structure

This is a mono-workspace.

- Publishable device libraries live under `libraries/<name>/` — installed code ends up on a microcontroller (via `circup install`, `mip install`, or `pip install` on a CPython-capable board). Ship to PyPI **and** the CircuitPython bundle.
- Publishable host-only tools live under `workbench/<name>/` — installed code ends up on a laptop (`pip install` only). Ship to PyPI only. See Decision 0032.
- Shared internal packages live under `support/<name>/` (not published).
- Developer tooling lives under `scripts/`.
- Planning docs live under `plans/`.

Conventions:

- **The installer's destination decides the folder.** Files a workbench package ships as *payload* — data a host CLI writes onto a device at deploy time — do not shift the folder. Payload is not an installable package. See Decision 0032 §Rules 1–2 for the worked example (`chumicro-workspace`).
- Workbench packages follow the **same release lifecycle** as libraries: `VERSION` (SemVer), `check-version` / `check-api` gates, experimental (`chumicro-deploy-experimental`) → stable (`chumicro-deploy`) promotion on PyPI. The only delta vs libraries is the absence of bundle staging and `.mpy` compilation — CP/MP-consumer concerns that don't apply to host-only packages.
- Publishable libraries use `libraries/<name>/` with `pyproject.toml` and `VERSION`. Use `[tool.chumicro].platforms` to declare runtime support (not to mark file-level host/device ownership).  Use `[tool.chumicro].requires_flash = true` to flag a library as "RAM mode often OOMs on smaller boards" — `chumicro-deploy`'s pre-flight reads this and auto-switches RAM-mode deploys to flash when the deploy graph contains a flagged library (Decision 0047).
- Publishable host-only tools use `workbench/<name>/` with `pyproject.toml` and `VERSION`. Same slots as libraries (`src/`, `tests/`, `docs/`, optional `functional_tests/` for hardware-touching host-side tests, optional `examples/` for runnable demos that aren't pytest-shaped) **minus** cross-runtime test coverage and the bundle / `.mpy` path — workbench is CPython-only. CPython-only third-party deps (`pyserial`, `pyyaml`, `rich`) are fine — `libraries/` avoids them only because a CPython-only dep can't be imported on a device, and workbench doesn't target devices.
- Support packages use `support/<name>/` and are not published.
- `scripts/run.py` auto-discovers packages by scanning for `pyproject.toml`.
- `python scripts/run.py new-library <name>` scaffolds a new device library and regenerates IDE configs. Host-only tools have no scaffolder yet — see [`docs/contributing/workbench.md`](docs/contributing/workbench.md) for the manual layout until the first workbench package lands.

### File routing

| Task | Where it goes |
|------|--------------|
| New device library (runs on CP + MP + CPython) | `python scripts/run.py new-library <name>` |
| New host-only tool (CPython only, PyPI only) | `workbench/<name>/` — hand-scaffolded for now; see [`docs/contributing/workbench.md`](docs/contributing/workbench.md) |
| Shared infrastructure (internal, not published) | `support/` |
| Build / CI tooling | `scripts/` |
| Design decision | `plans/decisions/NNNN-<slug>.md` |
| Docs assets | `support/docs/` |

### Key commands

| Command | Purpose |
|---------|---------|
| `python scripts/run.py setup` | Install dependencies and regenerate IDE configs |
| `python scripts/run.py add-device <id> --address <port>` | Register a board in `devices.yml` (probes hardware identity + fills in defaults on first registration).  Thin shim around `chumicro-workspace add-device` |
| `python scripts/run.py preflight` | Full CI mirror (lint + build + docs + unit tests on all runtimes + checks). Add `--with-functional` to also run hardware-gated functional tests at the end. |
| `python scripts/run.py test` | CPython unit tests (only changed packages by default; pass `--all` for the full sweep) |
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
| `python scripts/run.py test-micropython` | Run library unit tests on the MicroPython unix-port |
| `python scripts/run.py test-circuitpython` | Run library unit tests on the CircuitPython unix-port |
| `python scripts/run.py test-all-runtimes` | Run unit tests across CPython + MicroPython + CircuitPython (parallelized) |
| `python scripts/run.py test-functional` | Run every hardware-gated functional suite end-to-end (libraries + workbench, devices.yml defaults). For scoped runs, use the individual commands below. |
| `python scripts/run.py test-libraries-functional` | Run library functional tests on the default device target(s) from `devices.yml`. Scope with `--library`, `--file`, `--function`, `--runtime`, `--micropython-device`, `--circuitpython-device`, or `--deploy-mode`. See [docs/contributing/device-testing.md](docs/contributing/device-testing.md) for flag semantics and pytest-direct usage. |
| `python scripts/run.py test-workbench-functional` | Run hardware-gated functional tests for every `workbench/*/functional_tests/` suite. Device selection lives inside each suite's `conftest.py` (typically reading `devices.yml` defaults); scope with `--workbench`, `--file`, `--function`, `-v`, `-x`. |
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
- Prefer provided fakes over ad-hoc mocks when a library ships a `testing` submodule

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

- `plans/decisions/` — durable decisions affecting future work; see [`plans/decisions/README.md`](plans/decisions/README.md) for ADR format and editing conventions
- `plans/next-up.md` — active execution queue
- `plans/open-questions.md` — unresolved questions
- `plans/patterns.md` — reusable implementation patterns
- `plans/workstreams/` — phased deep work; archived to `plans/workstreams/archive/` once shipped

Housekeeping rules:

- Move checked-off items in `plans/next-up.md` into the top of `Done` in the same edit
- **Edit ADR bodies in place when the decision changes** — rewrite affected paragraphs so a cold reader gets accurate info; do not add `Revised:` banners, `## Update (YYYY-MM-DD)` sections, or `> **Note:** Amended by...` blockquotes.  `Date:` is the original decision date.  Status enum is exactly four values: `proposed` / `accepted` / `superseded` / `deferred` — never `revised`, `partial`, `shipped`, or `in-progress`.  When Decision N+1 supersedes part of Decision N, edit the affected paragraph in N to describe the current rule and cross-link N+1 inline (no banner blockquote at the head of the section).  Full rules in [`plans/decisions/README.md`](plans/decisions/README.md).
- When a decision resolves an open question, update `plans/open-questions.md`

## Contributing and code review

1. Keep PRs small and focused
2. Include tests and documentation with behavior changes
3. Do not commit build artifacts, bytecode, or secrets
4. Write commit messages that aid context recovery — imperative subject, body explaining why, and the affected libraries, decisions, or workstreams
