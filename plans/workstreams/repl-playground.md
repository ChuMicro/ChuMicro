# Workstream: REPL Playground

Status: `phase-1-shipped` — Phase 1a/1b/1c landed across commits
`abc81ff4` (line mode + per-device history), `835eb5c2` (`:edit` /
`:save` / `:load` / `:snippets`), and `730301f6` (tab completion),
followed by audit pass `2ff929d4`.  Phase 2+ (device introspection,
recording, multi-device, fun layer) remains unscoped — see
`## Phase 1 — shipped` below for what landed and `## Feature buckets`
for what's still on the menu.

## Purpose

Grow `chumicro-repl` from "serial TUI with traceback highlighting" into a side-portal experience for people who want to play with a CircuitPython or MicroPython board interactively — no project, no workspace, no saved scripts.  Also make it less tedious to author multi-line code in the REPL, which today is the single biggest friction in both `mpremote` and CP's default serial console.

This workstream is **deliberately separate from `archive/project-workspace.md`**.  The minimum-viable `chumicro-repl` core (in project-workspace Phase 2) is enough for deploy-tail and basic interactive use.  The playground features are valuable on their own terms but do not block the workspace template.  Sequencing, priority, and even whether to pursue some features at all can be decided independently.

## Scope

- Richer interactive authoring (history, search, completion, editor handoff, syntax highlighting).
- Snippet library (save, name, replay, promote-to-file).
- On-device introspection commands (pins, modules, memory, filesystem, GPIO toggles).
- Multi-device concurrent sessions (split-pane, broadcast to N boards).
- Session recording and replay.
- Fun/discovery (`:demo`, themes, board banner art).
- Programmatic test-fixture use beyond the minimum `ReplSession` shipped in project-workspace Phase 2.

Out of scope:

- On-device debugger / breakpoints — distinct problem, different architecture.
- IDE integration (VS Code / PyCharm REPL panes) — deferred until the CLI experience is compelling enough to warrant editor bindings.
- File-watching auto-deploy (that's the workspace's job, not the REPL's).

## Not-core-to-workspace

This workstream deliberately assumes zero blocking dependency on the project workspace workstream.  A user can `pip install chumicro-repl` and use it against any board they have, with no `workspace.yml`, no `devices.yml`, no `things/`.  The minimum in project-workspace Phase 2 is the shared foundation; everything here extends it.

When both workstreams are active:

- Features that benefit the workspace path (e.g. `:deploy <thing>` as a REPL command) are called out explicitly.
- Features that only make sense standalone (`:demo`, `:whoami` banner art) are independent.
- The library is one package (`chumicro-repl`); the evolution is two-lane.

## Feature buckets

### Interactive authoring

- [ ] **Multi-line edit with line editor.**  Arrow keys, bracket/paren matching, Ctrl-A / Ctrl-E, reverse-search with Ctrl-R.  Likely via `prompt_toolkit` (host-side dependency, not device-side).
- [ ] **Persistent history per device UID** under `~/.chumicro-repl/history/<uid>/`.  Survives reconnects.  Per-device so a session on "back porch" doesn't pollute "greenhouse" context.
- [ ] **Tab completion.**  Query device for `dir()` on the current namespace, offer completions on `<Tab>`.  Cache per-session; invalidate on device reset.
- [ ] **Syntax highlighting on input** — Pygments lexer for Python.  Theme-able.
- [ ] **Pretty-printed output.**  Smart truncation for long bytearrays / bytes / nested structures.  Color by type.  Click-to-expand collapsed output when terminal supports hyperlinks.
- [ ] **Help overlay (F1).**  Quick reference for common CP/MP modules and board pins, rendered over the session without scrolling history.

### Editor handoff + snippets

- [ ] **`:edit`** — open `$EDITOR` with a scratch buffer (prefilled with the last N lines of input).  On save-and-exit, ship the buffer to the device.  Matches IPython `%edit` semantics.  Removes the biggest friction in REPL-authored code: writing non-trivial methods inline.
- [ ] **`:save <name>`** — name the last N lines (or a selection) as a named snippet under `~/.chumicro-repl/snippets/<name>.py`.
- [ ] **`:load <name>`** — replay a named snippet.
- [ ] **`:snippets`** — list named snippets.
- [ ] **`:scratch`** — open a single shared scratchpad that lives across sessions.  Ship on save.
- [ ] **`:watch <file>`** — start watching a host file; any save sends the file to the device.  Simpler than the workspace's full deploy, intended for one-file exploration.
- [ ] **`:promote <name> --to things/<thing>/app.py`** — convert a snippet (or the current session) into a real file in a workspace.  Bridge between playground and workspace.  Skipped if no workspace is detected.

### Device introspection commands

- [ ] **`:pins`** — dump every `board.*` attribute (CP) or probe known pin modules (MP), grouped by function.  Color-coded by whether each pin is currently in use.
- [ ] **`:modules`** — parsed + colorized `help('modules')`.
- [ ] **`:mem`** — live `gc.mem_free()` + `gc.mem_alloc()` sampler with a rolling sparkline in the terminal.  Non-blocking: taps the REPL every N ms and overlays a status bar.
- [ ] **`:fs [path]`** — filesystem tree via `os.listdir` / `os.stat` chains.
- [ ] **`:cat <path>`** / **`:hexdump <path>`** — read a file from the device without writing a helper function.
- [ ] **`:upload <host-path> [<device-path>]`** / **`:download <device-path> [<host-path>]`** — file transfer without leaving the REPL.
- [ ] **`:run <host-path>`** — exec a host-side Python file on the device without writing it.  Good for throwaway experiments.
- [ ] **`:reset [--hard] [--bootloader]`** — soft reset (Ctrl-D), hard reset (`microcontroller.reset()` / `machine.reset()`), enter UF2 bootloader (CP only, via `microcontroller.on_next_reset`).
- [ ] **`:pin <name> [high|low|toggle|input|adc]`** — one-liner GPIO control.  Imports `digitalio`/`machine` on demand.
- [ ] **`:scope <pin> [--hz N]`** — poll a pin fast, render a terminal-width sparkline of its value over time.  Poor-man's logic analyzer for a pin.

### Recording + sharing

- [ ] **`:record [filename]`** — start capturing everything typed + output to a `.repl.log` file.  `:stop` ends recording.
- [ ] **`:replay <filename>`** — replay a recorded session against a (possibly different) device.  Ignores outputs, sends inputs with the original timing.
- [ ] **`:share`** — dump the current session to a URL-shareable gist (opt-in, off by default — the user typically has secrets in scrollback).
- [ ] **`--log <file>`** CLI flag to record from the first byte without needing `:record`.

### Multi-device

- [ ] **Split-pane** — `chumicro-repl --devices "back porch,greenhouse"` opens tiled panes, one per device.
- [ ] **Broadcast mode** — `:all` prefix sends the next statement to every device in the split.  `:only <id>` reverts.
- [ ] **Device switcher** — `F2` cycles focus across panes.

### Programmatic API (test-fixture use)

Beyond the minimum `ReplSession` shipped in project-workspace Phase 2:

- [ ] **`ReplSession.tap(pattern, handler)`** — register a callback for a regex on streamed output.  Enables async assertions in tests ("when board says READY, publish X").
- [ ] **`ReplSession.snapshot()`** / **`ReplSession.restore(snapshot)`** — save and restore REPL state (module imports, top-level bindings) via `pickle`-over-wire for fixture setup/teardown.  Only works when `pickle` is available on-device (MP needs `micropython-lib` pickle; CP has it in standard).
- [ ] **`ReplSession.assert_exec(code, expected_output, timeout)`** — testing primitive.
- [ ] **pytest plugin** — `@pytest.fixture` wrapping `ReplSession` for host-side tests that need a live board.

### Fun / discovery

- [ ] **`:demo [name]`** — ship a curated demo (rainbow Neopixel, tone sweep, capacitive-touch reactor) that runs for N seconds then cleans up.  Instant "this is cool" moment for new users.
- [ ] **`:whoami` banner** — on connect, show a friendly banner pulled from `devices.yml` if present, otherwise from the probed board_id.  Small ASCII art per board family (Feather silhouette, Pico silhouette, etc.).
- [ ] **`:board` info dump** — chip, memory, storage, known modules, drawn as a spec sheet card.
- [ ] **Color themes** — `dark`, `light`, `high-contrast`, `retro-crt`.  Selectable in `~/.chumicro-repl/config.yml`.
- [ ] **Playground mode** — `--playground` flag starts with a friendly tutor that offers suggestions ("press :demo for a light show", "press :pins to see available pins").  Turns off with `--no-playground`.
- [ ] **Ephemeral session mode** — `--ephemeral` snapshots the board filesystem at session start, rolls back on exit.  Safe experimentation — nothing the user does can permanently break the device.

## Sequencing

No strict order.  Start with whichever cluster unblocks the most user pain:

1. **Interactive authoring + `:edit`** — solves the single biggest REPL friction (writing multi-line code) and is the most visible win for new users.  Start here.
2. **Persistent history + tab completion** — high-value-per-line-of-code, makes the REPL feel instantly more modern.
3. **Device introspection commands** — `:pins`, `:mem`, `:fs`.  Easy to ship; high utility.
4. **Snippets + scratch + watch** — layers on top of editor handoff.
5. **Multi-device + recording + fun features** — nice-to-haves, ship as capacity allows.
6. **Extended programmatic API** — driven by downstream test-fixture demand.

## Phase 1 — concrete implementation plan (drafted 2026-04-27)

The current TUI (`workbench/repl/src/chumicro_repl/tui.py`) is a tight passthrough loop: keystrokes go straight to the port, output is decoded + highlighted + written to stdout.  No host-side input buffer, no command parser.  Adding rich features means introducing an *input mode* abstraction.

### Architecture

Three input modes, hot-toggleable mid-session:

| Mode | Behaviour | Use |
|---|---|---|
| **Passthrough** | Every byte goes straight to the device.  Today's behaviour. | Raw REPL, paste-mode, anything that wants exact byte forwarding. |
| **Line** | Host buffers input via `prompt_toolkit`; user gets cursor edit, history, history-search (Ctrl-R), bracket matching.  On Enter, the full line ships to the device.  Lines starting with `:` are parsed as REPL commands (intercepted, not forwarded). | The default mode for typing code at the `>>>` prompt.  Where 95 % of interactive use happens. |
| **Edit** | Host opens `$EDITOR` with a scratch buffer.  On save+exit, ships the buffer to the device line-by-line. | Multi-line code authoring.  Triggered by `:edit`. |

**Toggle:** `Ctrl-T` cycles passthrough ↔ line.  Edit is one-shot (auto-returns to the previous mode after the editor closes).

**Auto-detection:** the TUI starts in **line** mode by default.  When the device output indicates raw-REPL entry (`raw REPL; CTRL-B to exit\r\n>` marker), the TUI auto-switches to passthrough.  When the device output shows the friendly REPL prompt (`>>>`), the TUI switches back to line.  Override via `--mode {line,passthrough}` CLI flag.

**Storage:** `~/.chumicro-repl/history/<device-uid>/history.txt` (per-device persistent history).  `<device-uid>` falls back to a stable hash of the address when probe fails.  Command snippets live at `~/.chumicro-repl/snippets/<name>.py`.

**Dep:** `prompt_toolkit` joins `chumicro-repl`'s pyproject as a runtime dep.  CPython-only (Decision 0032 §6 explicitly allows this for workbench packages).  ~500 KB on disk; the value-per-byte ratio is excellent for what it solves (multi-line edit, history search, completion infrastructure all in one library).

### Phase 1a — line mode + persistent history (smallest viable shippable)

* Add `prompt_toolkit` dep to `workbench/repl/pyproject.toml`.
* New module `chumicro_repl.line_mode` — wraps `prompt_toolkit.PromptSession` with a per-device `FileHistory` rooted at `~/.chumicro-repl/history/<uid>/history.txt`.
* New `Mode` enum + mode-state in `run_loop`.  Enter = ship line + record; `:` prefix = command parser stub (initially only handles `:help`).
* `Ctrl-T` cycles line ↔ passthrough.
* CLI: `--mode {line,passthrough}` defaulting to `line`.

**Outcome:** every `chumicro-repl` session immediately has cursor edit, persistent up-arrow history, `Ctrl-R` reverse search, and per-device isolation between sessions.  No new commands yet; the foundation is in place.  ~250 LOC of new code + tests.

### Phase 1b — `:edit` command

* New `chumicro_repl.commands` module: registry of `:command-name → handler` callables.
* `:edit` handler: write current scratch (initial empty + last-N-lines context) to `tempfile.NamedTemporaryFile`, open `$EDITOR` (default `vi`), on save read back and ship to device.  Match IPython's `%edit` semantics.
* `:save <name>` / `:load <name>` / `:snippets` for snippet store.
* `:help` dumps the registered commands + brief.

**Outcome:** writing a 30-line function in the REPL stops being painful.  ~150 LOC.

### Phase 1c — tab completion

* On `<Tab>`, query the device for `dir()` on the current namespace + `dir(x)` for partial attribute access (`object.attr<Tab>`).
* Cache per-session; invalidate on device reset (heuristic: detect `>>>\r\n>>>` two-prompts-in-a-row).
* Pluggable: `Completer` protocol so future device-side completers (e.g. for `board.*` symbols) can layer in.

**Outcome:** REPL feels modern.  ~200 LOC + the cache invalidation finesse.

### Phase 1 success criteria

A user `pip install chumicro-repl && chumicro-repl --device /dev/cu.usbmodem1101` lands in line mode by default, gets up-arrow history that persists across sessions, can hit `:edit` to compose a function in `vim`, and can tab-complete attributes on imported modules.  Beats `mpremote` on every dimension that matters for interactive work.

## Phase 1 — shipped

What landed (commits in chronological order):

- **1a — line mode + persistent history** (`abc81ff4`): `prompt_toolkit.PromptSession` with cursor edit, history navigation, `Ctrl-R` reverse search; per-device history at `~/.chumicro-repl/history/<sanitized-address>/history.txt`; `--mode {line,passthrough}` CLI flag defaulting to line.
- **1b — editor handoff + snippets** (`835eb5c2`): `:edit` opens `$EDITOR` with the last 10 input lines prefilled, ships on save; `:save <name>` / `:load <name>` / `:snippets` for named snippets at `~/.chumicro-repl/snippets/`.
- **1c — tab completion** (`730301f6`): on `<Tab>`, queries device `dir()` on the current namespace, caches per-session; `:rescan` invalidates the cache after `import`.
- **Audit pass** (`2ff929d4`): post-Phase-1 cleanup across the package.

Phase 1 follow-up shipped 2026-05-10 (this session):

- **Line-mode key bindings match `mpremote` / passthrough TUI**: `Ctrl-C` forwards `\x03` to the device (interrupts a running program — the standard REPL convention), `Ctrl-D` at an empty prompt forwards `\x04` (soft-reboot), `Ctrl-X` is the local exit.  Previously, `Ctrl-C` exited line mode entirely, leaving the user with no way to interrupt a runaway loop without dropping the serial connection.

What's deliberately deferred (Phase 2+): every feature in `## Feature buckets` above except the Phase 1 items.  The biggest natural next cluster is **device introspection** (`:pins` / `:fs` / `:mem` / `:reset` / `:pin`) — independently shippable, high utility per line of code, and the user-visible "playground" feel that motivates this workstream's name.

## Success criteria

- A user with no workspace can `pip install chumicro-repl` and `chumicro-repl --device /dev/cu.usbmodem1101` into an interactive session that beats `mpremote` on at least: multi-line editing, history search, tab completion, and traceback rendering.
- Writing a 15-line function in the REPL is as comfortable as writing it in an editor — no awkward paste-mode dance, no lost indentation.
- `:demo` works first try on a freshly flashed CircuitPython board with a Neopixel.
- At least one featured demo video can be recorded from a REPL session using `:record` and replayed on a different board unchanged.

## Notes

- Host-side dependencies (prompt_toolkit, pygments) are fine — REPL runs on the user's laptop, not the board.  Keep the library pure-Python on the host.
- Device-side helpers for introspection commands live in `chumicro-repl`'s `on_device/` submodule, streamed as small code blocks per command.  They do not get installed as a library — they are inlined.
- Secrets risk on `:share` and `:record`: prominent warning, off by default.  `secrets.yml` contents and `settings.toml` reads should be redacted automatically if pattern-detected.

## Open sub-questions

- How much of the "fun" layer (`:demo`, banners, themes) earns its keep vs being cute-but-rarely-used?  Decide after first user feedback on the core features.
- Is `prompt_toolkit` the right choice, or is there a lighter terminal library that avoids the ~500 KB dependency?  Defer until Phase 1 of interactive authoring is scoped.
- Should recording + replay get a stable file format early, so sessions recorded today replay in a year?  Leaning yes — declare a simple JSONL schema in the first implementation.

## Resolved feedback

- **Why split from `archive/project-workspace.md`?**  Project workspace has a defined acceptance (a user onboards and deploys a thing).  REPL playground has no such gate — it's open-ended feature growth that benefits from its own prioritization.  Split on 2026-04-21 when the user flagged that Phase 2's scope was drifting beyond "what deploy tail needs."
