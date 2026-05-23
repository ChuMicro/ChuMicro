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
- Anchor claims to evidence (file, symbol, test, or command). Verify by reading code, running tests, or checking command output. Training recall is not verification. For anything time-sensitive, version-specific, or newer than the model cutoff, web-search rather than asserting from memory.
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
- Before creating or editing a file under `plans/decisions/`, read [`plans/decisions/README.md`](plans/decisions/README.md). New ADRs route through the [`new-decision`](.github/skills/new-decision/SKILL.md) skill — invoke it, don't freehand. An ADR contains **only** context, decision, invariant, rationale, and rejected alternatives with reasoning. Everything else — phase plans, migration rosters, bake-validation logs, class signatures, per-runtime substrate tables, future-work checklists — is mechanism and goes to [`plans/workstreams/<name>.md`](plans/workstreams/). A decision, rejected alternative, or structural rule sitting inside a workstream belongs in `plans/decisions/`.
- A `plans/workstreams/<name>.md` file you're picking up is a **directive, not a research artifact**. Execute the next unshipped phase from its `## Implementation phases` / `## Plan` section. When something looks like it may have changed, verify the specific claim (read the code it points at, run the failing test, check the cited commit), then proceed — don't bounce to the user without a concrete blocker. As phases land, append one line per phase to the workstream's `## Validation history` section, and update the `Status:` line (`shipped`, `parked`, `superseded`) when fully done.
- When you don't know a subcommand or flag on `python scripts/run.py`, `chumicro-workspace`, `chumicro-deploy`, or `chumicro-repl`, run the tool (and each subcommand) with `--help` before asking the user or giving up. The full subcommand inventory is discoverable. Treating a workbench tool or `scripts/run.py` as opaque is a process failure.
- **The standard way to deploy a project is `chumicro-workspace deploy [<name>]`.** For an `app.py` + `run()` project (no `code.py` / `main.py`), that single command auto-detects boot-shim + import-graph and ships only the modules the entrypoint transitively imports from `libraries/` and `shared/`. The auto-detect matrix lives in `workbench/workspace/src/chumicro_workspace/cli/deploy.py:_resolve_layout`. `chumicro-deploy deploy --directory` is the low-level escape hatch for non-project file trees staged by hand; it ships the *whole tree* including unused libraries, wastes flash, and can OOM at boot. `workbench/<tool>/examples/` carries worked invocations (`import_graph_deploy.py`, `file_map_deploy.py`); check there before picking flags.
- Library public-API or behavior change ⇒ bump the library's `VERSION` file in the same commit (once per coherent unit of work — a full audit pass is one bump, not one per commit). `python scripts/run.py check-api` confirms the minimum level (patch / minor / major). Behavior-only, docstring-only, and shipped-comment-only changes still bump `patch` so users see the change land in their version pin. Detail in [docs/contributing/releases.md](docs/contributing/releases.md).
- Never deploy `code.py` / `main.py` containing `microcontroller.reset()` (CircuitPython) or `machine.reset()` (MicroPython).

**Testing**

- Maintain coverage gates. Every `test` and `preflight` invocation must pass `--coverage-threshold 94`.
- Test skips must be loud. Do not write a test with no assertions or validation. Use `chumicro_test_harness.skip(reason)`, declare `__chumicro_runtimes__` / `__chumicro_features__` markers, or `raise AssertionError(...)`.
- A **cross-runtime test file** is any test file whose name does not end in `_pytest.py`. The `_pytest.py` suffix marks CPython-only tests (free to `import pytest`, use `monkeypatch`, simulate other runtimes). Test files without the suffix are loaded by `chumicro_test_harness` on MicroPython and CircuitPython directly. The file's top docstring must say which kind it is.
- Cross-runtime test files must not `import pytest`. Use plain `assert` and constructor-injected fakes from each library's `testing.py`.
- Every cross-runtime test file must run green on a freshly-reset Pi Pico W (264 KB) under both CircuitPython and MicroPython. A PSRAM-only pass does not validate the 256 KB HAL these libraries exist for. A file that OOMs there even with `--per-file` is a tracked defect.
- Tests in any package may depend only on: the package's own `src/` + `testing.py`, stdlib, pytest + plugins, and `support/test_harness/`. Don't `import chumicro_<other-package>` for inputs or read sibling-repo filesystems.

**Code shape (libraries, microcontroller only)**

- **Runner-tick invariant: no library call blocks the loop more than ~5 ms.** That's the runner's per-tick budget; the only sanctioned blocking point is `Runner.wait`, which idles to the next deadline ([Decision 0080](plans/decisions/0080-runner-reactor.md)). Use the tick-based runner pattern from [Decision 0014](plans/decisions/0014-runner-pattern.md); no `async` / `await` and no ISRs. Named violations (examples, not an exhaustive list): `time.sleep(N > 0.005)`, `select.poll(timeout > 0)` in a leaf service, synchronous TCP connect or TLS handshake from a runner-tick-reachable method ([Decision 0081](plans/decisions/0081-non-blocking-connect-via-tick-driven-connector.md) — use `chumicro_sockets`'s tick-driven connector), blocking `getaddrinfo`, `machine.lightsleep(ms)`, blocking `socket.recv()`, `os.urandom(N)` on MP, any other syscall that takes the loop offline. The test is the budget, not the list.
- All time math goes through `chumicro_timing` — `ticks_ms()`, `ticks_diff()`, `ticks_add()`, `Heartbeat`. Applies to `libraries/` source and to tests (any package) that gate on deadlines or elapsed time. Never call `time.monotonic()`, `time.ticks_ms()`, or `supervisor.ticks_ms()` directly. `chumicro_timing` unifies three runtime time domains; bypassing it pits a `chumicro_timing`-tick deadline against a `time.monotonic()` wall clock and produces a "freeze" that looks like a stalled service but is really mismatched units. Exception: `chumicro_timing`'s own tests exercising the resolution mechanism.
- **Steady-state zero allocation per tick.** Inside `tick()` / `handle()` / `check()` / any parser inner loop, the allocation delta over 1000 ticks must be ≤ 64 bytes — verify with `gc.mem_alloc()` before/after with `gc.disable()` bracketing (recipe in [audit-embedded §10](.github/skills/audit-embedded/SKILL.md)). Named offenders: f-strings / `.format()` (each allocates a new `str` — use `log.info("...%d...", n)` or guard with `is_enabled`); dict / list / set / tuple literals (reuse a module-level constant or cleared scratch); `bytes(view[a:b])` to feed `struct.unpack` → `unpack_from(fmt, buf, offset)`; `bytes(view).decode("utf-8")` → `str(view, "utf-8")`; `int.from_bytes(bytes(buffer[a:b]), ...)` → drop the `bytes()` wrapper; `enumerate` / `zip` / `reversed` in a hot loop (each allocates an iterator); `self.x.y.z.method()` chains used twice or more → cache to a local. F-strings outside hot paths are fine.
- **`gc.collect()` is two-sided.** Forbidden inside `tick()` / `handle()` / any per-message callback — the underlying bug is missing pre-allocation; fix that instead. *Required* at the end of every library `__init__.py` (the `import gc as _gc; _gc.collect(); del _gc` block), and between submodule imports when a library spans more than one `.py` file. MicroPython's compiler leaves AST scratch + transient tuples interleaved with the library's persistent state, and auto-GC may not fire to reclaim it — measured +33 KB contiguous heap on Pi Pico W MP, enough to flip TLS handshakes from ENOMEM to ROUND_TRIP. Allowed between major state changes (post-handshake, post-bulk-decode, post-`connect()`) where pre-emptive collection is cheaper than triggering one inside the next allocation. Benign on CPython.
- **Sender-controlled allocations are heap-DoS surface.** Any `bytearray(N)` / `bytes(N)` in inbound-parse code must either bound `N` at a documented cap-knob (`max_message_bytes`, `max_body_bytes`, `max_frame_bytes`) and refuse / drop above it, or use a pre-allocated steady-state buffer as a rolling sink. When `N` comes from a peer-controlled field (MQTT remaining-length varlen, HTTP `Content-Length`, WebSocket frame length) and the allocation is unbounded, a hostile peer claims whatever heap the board has. Comments claiming "heap-safety" do not substitute for a real bound.
- Constructor injection for time, I/O, network deps. Fakes go in the library's `testing.py` submodule.
- Absolute imports only in code written in the `libraries/` folder. Relative imports break CircuitPython RAM-mode deploys. Workbench and scripts folder may use either. Enforced by ruff TID252.
- Use PEP 604 / 585 syntax (`int | None`, `list[int]`). Don't import `typing` and don't write `from __future__ import annotations` in library code. MicroPython has no `__future__`. CPython-only trees may keep it.
- Mark runtime-specific files with `__chumicro_runtimes__ = ("circuitpython",)` (or `"micropython"`, `"cpython"`). Test-support modules (`testing.py` fakes) declare `__chumicro_test_support__ = True` and no runtime marker.
- Use f-strings. Use `const()`, `memoryview`, pre-allocated buffers in library code only.
- No `__slots__` in `libraries/`. MP/CP have no `__slots__` implementation.
- No pure-passthrough `@property` in `libraries/`. Properties that compute or transform values stay legitimate. Workbench packages are out of scope.
- Use descriptive names. No single-letter variables except `_`. Expand abbreviations to full words. For example, write `environment` rather than `env`, `buffer` rather than `buf`, `source` rather than `src`, `command` rather than `cmd`, `message` rather than `msg`, `error` rather than `err`, `reference` rather than `ref`, `address` rather than `addr`, `exception` rather than `exc`, and `execute` rather than `exec`. The `for i in range(10)` exemption is humans-only. Enforced by `CHU001`. Suppress only when matching an upstream API.
- Minimize dependencies. Prefer pure-Python implementations compatible with all three runtimes.
- The rules above apply inside `libraries/`. They also apply to `support/<name>/src/` packages by default — `chumicro_test_harness` and other shared internals must stay cross-runtime unless a file marks itself `__chumicro_runtimes__ = ("cpython",)`. They do **not** apply to `workbench/` or `scripts/` (CPython-only trees).

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

## Common pitfalls

- Don't `pip install -e` manually to fix imports. Run `python scripts/run.py setup`.
- If bare `python` errors `command not found`, the agent shell didn't inherit a `python` alias. Run `source .venv/bin/activate` once, or invoke `.venv/bin/python scripts/run.py …` directly.
- Don't critique an architectural split from docs alone. Read the code on both sides. Docstrings often encode constraints.
- `replace_all` is literal substring substitution. Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
- When editing IDE config files (`.iml`, `.idea/`, `pyrightconfig.json`, `.vscode/settings.json`), `cd` to the main checkout first. `sync-ide` from a worktree writes paths that break in main.
- Don't manipulate CIRCUITPY mount state from the host (`diskutil unmount` / `eject` / `mount`, `rm /Volumes/CIRCUITPY*`). The deploy/transport code owns mount state, and manual interference defeats its mount probing + EACCES classifier (a macOS FSKit wedge can leave the volume unmountable). Destructive remediation: `chumicro-workspace reset-board --yes`.
- A `git rm` or `git add` stages immediately and rides into the next commit, even a later narrowly-scoped one. Before a scoped commit, run `git --no-pager diff --cached --stat` and `git restore --staged <unrelated>`, or stage with explicit pathspecs. A pre-staged `mqtt/test_client.py` deletion once rode into an unrelated `http_server` split. Main carried a deleted-but-not-replaced suite for one commit, which cost a fixup and a broken-main window.

## Working style

- **Grep is for verifying a specific claim, not for replacing the read on judgment tasks.** When the deliverable is a judgment (audit, code review, comprehending unfamiliar code), workload size is not permission to drop to pattern-scanning. Split the target into smaller sequential passes. Grep is the right primary tool when the deliverable is *finding* something specific (callers of X, occurrences of a pattern); it is the wrong primary tool when the deliverable is *judging* prose, structure, or design.
- **Surface tradeoffs early.** When multiple reasonable approaches exist, name them. When ambiguity affects correctness, ask. When a simpler approach would work, say so.
- **Default to action on reversible local work.** File edits, tests, refactors, plans-doc updates: execute, don't ask. Surface before destructive ops (deletions, force-pushes, breaking API changes), anything visible outside this repo, or unasked scope expansion. Auto mode amplifies *lean toward action*, not *skip the destructive-op check*.
- **A named successor is a directive, not an off-ramp.** When a skill or doc points at another step as the owner of what comes next, follow the pointer. Words like *"defer"*, *"later"*, *"elsewhere"* describe where to go, not that you're done.
- **Same writing checks for user-facing responses.** The concise / direct / concrete / professional checks from [Writing tone](#writing-tone) apply to your replies and status updates, not only to prose written into files. Read aloud before sending; if you wouldn't say it that way to a colleague, rewrite.
- **Quality bar.** Small focused diffs, preflight green, commit messages that name the rule / decision / pattern applied.

## Writing tone

Read each sentence the way you'd say it out loud to a colleague. If you wouldn't say it that way to a person, rewrite it. Everything below is a shape that tends to fail that test; the test is the gate, the list is what to listen for. Lint-backed rules (`Enforced by CHU…`) are absolute; everything else answers to the ear.

Four checks per sentence:

- **Concise.** Cut connectors that just restate what structure already implies.
- **Direct.** Lead with the load-bearing fact, not stage-setting.
- **Concrete.** Name actual classes, functions, files. Avoid abstract stand-ins (*shape*, *surface*, *the algorithm*, *the implementation*) when a specific name exists.
- **Professional.** No colloquialisms (*feeds through*, *wires up*, *punts to*, *hooks into*). No implicit objects (*the caller is about to route* — route what?). No ambiguous pronouns.

The deepest fault no regex catches: an abstract subject (*"the win is"*, *"its floor is"*) joined by a weak verb to a coined noun that hides an action (*"the WFI-idle that `ipoll` gives"*). Find the real actor and let it act: *"a connected board idles the CPU between events, which is what `ipoll` does."* Per-sentence judgment pass, not a sweep — worked cases in [agent-style-guide.md § Concrete subject, real verb](docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule).

Em-dashes, semicolons, arrows, AI-tic framings (*"the X promise"*, *"the X pattern"*), empty adjectives (`comprehensive`, `robust`, `seamlessly`, `cutting-edge`, `best-in-class`), and filler openers (*"It is worth noting"*, *"Let's dive into"*, *"In this section we will"*) are suspects. Empty adjectives almost always fail (replace with what something covers or survives); the rest are case-by-case. Verify domain terminology before promoting a code identifier into authoritative prose — engineer names drift from the domain.

Standing AI-tic regex, consumed by `/audit-docs`, `/audit-comments`, `/audit-skill`:

```bash
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|harness|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

A hit is a candidate, not a verdict. A swap that produces a worse sentence is a regression — read the rewrite aloud before accepting it.

**Degraded prose is rewritten, not trimmed again.** A passage rotted by repeated subtractive edits doesn't get fixed by removing another word. Discard, then rewrite from a fresh read of what the thing is and why it exists, with a concrete subject doing something. Applied by [`audit-comments`](.github/skills/audit-comments/SKILL.md), [`audit-docs`](.github/skills/audit-docs/SKILL.md), [`audit-skill`](.github/skills/audit-skill/SKILL.md), and the in-place-edit rule in [`plans/decisions/README.md`](plans/decisions/README.md).

Full reference (per-noun `the X` article test, full phrase-ban subsections, CHU-codes-in-prose lint): [docs/contributing/agent-style-guide.md](docs/contributing/agent-style-guide.md).

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

When a library doesn't already exist for a job, check `plans/decisions/` for `00NN-chumicro-<name>.md` files — libraries designed but not yet built.

## Commands

Activate any virtual environment first. Two distinct setup commands:

- **First-clone bootstrap.** `python scripts/prepare_workspace.py` — creates `.venv`, installs deps, runs lint + host tests as a smoke check. Use exactly once per fresh clone, before any other command. The script self-re-execs into the new `.venv` so a system Python without `tomllib` still works.
- **Steady-state refresh.** `python scripts/run.py setup` — reinstall deps, regenerate IDE configs against the current pyproject. Run after pulling dependency changes or adding a library. Already-active venv assumed.

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

| CLI | What it's for | When to reach |
|---|---|---|
| `chumicro-workspace` | Project deploys, `devices.yml` management, firmware install/upgrade, scaffolding, workspace health | Default front door for anything project-shaped or workspace-level — most agent work routes here |
| `chumicro-deploy` | Low-level transports: probe a board, flash firmware, raw file-push by directory or file-map | Non-project file trees staged by hand, or firmware flashing outside a workspace context |
| `chumicro-repl` | Interactive serial REPL with traceback highlighting and `--tail` follow mode | Driving a board interactively, watching deploy output, post-deploy smoke check |

**Common `chumicro-workspace` subcommands** (full list: `chumicro-workspace --help`):

| Subcommand | What it does |
|---|---|
| `deploy [<name>]` | Push a project to a board. Auto-detects boot-shim + import-graph for `app.py` + `run()` projects |
| `deploy-example` | Push a `libraries/<lib>/examples/<name>.py` example to a registered device |
| `demo` | Push a built-in hello-world to the active device (~5s; cross-runtime smoke test) |
| `add-device` | Probe a board and register it in `devices.yml` |
| `devices` | List every entry in `devices.yml` |
| `probe` | Print the runtime identity reported by the selected board |
| `new` | Scaffold `projects/<path>/` from a template or example tree |
| `status` / `doctor` | Workspace health snapshot (workspace.yml, devices.yml, projects tree; `doctor` adds Python-version + per-project `run()` AST scan) |
| `reset-board --yes` | Destructive: wipe and re-prep a board (FSKit-wedge remediation; only command authorized to manipulate CIRCUITPY mount state) |
| `install-firmware` / `upgrade-firmware` | Firmware flash / version-bump for a registered device |
| `library` | Manage the workspace's local library copies (sync from mono-repo, list, etc.) |

Each subcommand's `--help` shows its flags. The CLI rejects wrong runtime / project-shape combinations with actionable error messages.

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
- [Decision 0060](plans/decisions/0060-chu-rules-home.md): the CHU lint index — every `CHU0NN` code referenced in this file is enumerated and described here.
- [docs/troubleshooting/](docs/troubleshooting/): hardware-issue recovery (FSKit wedge, read-only FAT, RingIO quirks).
