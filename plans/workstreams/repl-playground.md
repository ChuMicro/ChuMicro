# Workstream: REPL Playground

Status: `proposed`

## Purpose

Grow `chumicro-repl` from "serial TUI with traceback highlighting" into a side-portal experience for people who want to play with a CircuitPython or MicroPython board interactively — no project, no workspace, no saved scripts.  Also make it less tedious to author multi-line code in the REPL, which today is the single biggest friction in both `mpremote` and CP's default serial console.

This workstream is **deliberately separate from `project-workspace.md`**.  The minimum-viable `chumicro-repl` core (in project-workspace Phase 2) is enough for deploy-tail and basic interactive use.  The playground features are valuable on their own terms but do not block the workspace template.  Sequencing, priority, and even whether to pursue some features at all can be decided independently.

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

- **Why split from `project-workspace.md`?**  Project workspace has a defined acceptance (a user onboards and deploys a thing).  REPL playground has no such gate — it's open-ended feature growth that benefits from its own prioritization.  Split on 2026-04-21 when the user flagged that Phase 2's scope was drifting beyond "what deploy tail needs."
