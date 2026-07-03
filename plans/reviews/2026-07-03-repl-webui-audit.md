# Hunt-tail — un-audited-areas final sweep: workbench/repl + webui/

Scope A = `workbench/repl` (interactive REPL/session tooling). Scope B = `webui/` (local dev web UI).
Method: read all source in both areas; confirmed candidates with fake-backed probes in
`.scratch/hunt-tail/` (no live serial — repl is code-reading + unit-fake probes only). Baseline
`workbench/repl/tests` = 262 passed. Excludes items already in `plans/next-up.md` and the
repl-playground Phase-1 shipped set.

Headline: webui binds 127.0.0.1 everywhere (no 0.0.0.0) and `SimpleHTTPRequestHandler` confines
every path-traversal probe (all 404) — both named risks are clean. The real findings are in the repl.

---

## Scope A — repl (R-ids)

### R1 · high · workbench/repl/src/chumicro_repl/tui.py:227-253 — passthrough-TUI Ctrl-X never exits while the board is streaming

What happens: `run_loop`'s on-exit serial drain is an unbounded `while True` whose ONLY exit is
`if not available: break` (line 230-231). When the user presses Ctrl-X, `exit_requested` is set and
the drain then loops until `in_waiting` reports 0 (the `if not exit_requested: break` at 247-251 is
skipped once exiting). A board stuck in a tight `while True: print(...)` saturates USB-CDC so
`in_waiting` never settles to 0 — the drain reads/writes forever and the `if exit_requested: return 0`
at 252 is never reached. Ctrl-X is documented as "exit without interrupting the board", i.e. exactly
the case where the board keeps streaming.

Confirmed: `.scratch/hunt-tail/probe_repl.py` (probe A) — a fake port with `in_waiting` always 1 plus a
lone Ctrl-X keystroke; `run_loop` performed 3000+ post-exit reads without returning (capped by the
probe to avoid a real infinite loop). "HANG CONFIRMED — Ctrl-X did NOT exit."

Blast radius: interactive passthrough TUI (`chumicro-repl` non-line mode, and line-mode's
byte-passthrough sibling). Runaway-print loops are extremely common during board bringup; the user's
only escape is killing the terminal. Line-mode's `_drain_serial` bounds the same wait with
`window_seconds`; the TUI exit path has no such bound.

Fix: bound the exit drain — either a wall-clock ceiling (like `_drain_serial`'s `window_seconds`) or a
max-iteration/byte cap on the `exit_requested` branch, so Ctrl-X always returns 0 within a bounded time.

### R2 · medium · workbench/repl/src/chumicro_repl/line_mode.py:660 (+ 301, 338, 261) — a `:command` handler exception crashes the whole line-mode session

What happens: `run_line_mode` calls `handler(context, rest)` at line 660 with no try/except. `:edit`
(`_cmd_edit`) shells out via `_open_editor` → `subprocess.run(shlex.split(editor)+[path])` (line 301);
a missing/misconfigured `$EDITOR` binary raises `FileNotFoundError` (an OSError subclass) which is NOT
caught anywhere and propagates out of `run_line_mode` → `interactive_line` → `cli.main`, ending the
whole REPL with a bare traceback. Same gap for `context.send_line` inside `_cmd_edit` (338) and
`_cmd_load` (261): a port drop mid-replay raises OSError uncaught — whereas the main loop's plain-line
branch (664-669) DOES catch OSError and prints "write failed". So the handler path is the odd one out.

Confirmed: `.scratch/hunt-tail/probe_repl.py` (probe B) — `_cmd_edit` with `editor="this-binary-does-
not-exist-zzz"` raised `FileNotFoundError` uncaught. "CRASH CONFIRMED."

Blast radius: `:edit` on any host where `$EDITOR` points at a missing command, or `$EDITOR` unset and
`vi` absent (minimal containers / trimmed dev images) — the entire interactive session dies, losing
in-progress history. `:load`/`:edit` also die on a mid-replay unplug instead of degrading gracefully.

Fix: wrap the `handler(context, rest)` call in run_line_mode in a try/except (OSError at minimum) that
prints a one-line "command failed: …" and continues the loop; or catch FileNotFoundError/OSError inside
`_cmd_edit`/`_open_editor` and report "editor not found: <editor>".

### R3 · medium · workbench/repl/src/chumicro_repl/cli.py:99-121 — `chumicro-repl` console script gives a bare traceback on connect failure (no coaching loop)

What happens: `main()` calls `interactive_line(args.address)` / `interactive(args.address)` / `tail(...)`
directly with no wrapper. On the most common first-run failures (port not found, port busy,
permission denied) `default_port_factory`'s `serial.Serial(...)` raises `SerialException`, which
propagates unclassified straight out of `main` as a raw traceback. The package already ships
`recovery.coached_session_start` + `classify_session_failure` + per-kind `RecoveryPlan`s for exactly
these cases, and AGENTS.md's workbench rule says "Workbench CLIs … CLIs always wrap entry points in
coaching loops. A generic raise Exception is a UX defect." The `chumicro-repl` entry point
(`pyproject.toml [project.scripts] chumicro-repl = "chumicro_repl.cli:main"`) never uses them.

Confirmed by reading: entry point maps to `cli:main`; `main` (99-121) has no try/except and no
`coached_session_start`; `recovery.py`'s own docstring (313-320) says only "the workspace repl CLI"
wraps these calls — the standalone published console script does not.

Blast radius: every `chumicro-repl --address …` run against an unplugged / wrong / busy port — the #1
first-run failure — surfaces a pyserial traceback instead of the actionable recovery plan. Note the
ambiguity: this may be intentional ("thin wrapper; coaching lives in `chumicro-workspace repl`"), but
the workbench rule and the success-criterion of `pip install chumicro-repl && chumicro-repl --device …`
argue the standalone CLI should coach.

Fix: wrap the interactive/line-mode connect in `coached_session_start` in `cli.main` (tail mode already
returns a classified ExitCode; leave it as is).

### R4 · low · workbench/repl/src/chumicro_repl/session.py:357-374 — `read_until` drops the lead bytes of a multibyte codepoint split at a marker boundary

What happens: `ReplSession.read_until` builds a fresh `Utf8StreamDecoder` local to the call. When the
regex matches, it saves only the decoded tail (`tail_text.encode()` → `_read_remainder`, 371-373) and
returns — any bytes still buffered inside the decoder (an incomplete trailing codepoint) are discarded
with the local decoder. If a multibyte char begins immediately after the matched marker in the same
chunk, its lead bytes are lost; the continuation bytes arriving on the next call decode to U+FFFD.
(`exec`'s `_read_until_bytes` is byte-only and unaffected — this is `read_until`-specific.)

Confirmed: `.scratch/hunt-tail/probe_readuntil.py` — chunk `b"READY\xf0\x9f"` then `b"\x99\x82DONE"`;
first `read_until("READY")` → `'READY'`, second `read_until("DONE")` → `'��DONE'` instead of
`'🙂DONE'`. "R4 CONFIRMED."

Blast radius: narrow — only the public `read_until` primitive (tailing the friendly REPL / non-raw
output), and only when a non-ASCII codepoint straddles the exact match boundary. Cosmetic corruption
(replacement chars) in streamed non-ASCII output.

Fix: when returning, also carry the decoder's buffered bytes forward — e.g. `_read_remainder =
tail_text.encode() + decoder._buffer` (or re-decode with `decoder.flush()` semantics preserved), so a
partial codepoint survives into the next call the way `_read_until_bytes` preserves its byte remainder.

### R5 · low · workbench/repl/src/chumicro_repl/_follow.py:259 / 277-282 — `_attempt_reconnect` docstring claims KeyboardInterrupt handling the code doesn't have

What happens: the docstring (259-261) states "Catches `KeyboardInterrupt` from the user's signal
handler and treats it as 'stop reconnecting' — the caller's return path turns that into
`ExitCode.INTERRUPTED`." The function body has only `except OSError` (281); there is no
`except KeyboardInterrupt`. A Ctrl-C during the reconnect window (e.g. inside
`time.sleep(reconnect_interval)`) propagates through `tail`'s try/finally (closing the port) and out to
the caller as a raw `KeyboardInterrupt`, NOT `ExitCode.INTERRUPTED`. The main read loop DOES catch it
(line 164) and return INTERRUPTED, so the two windows behave inconsistently.

Confirmed by reading: `grep KeyboardInterrupt _follow.py` → only line 164 (main loop) + line 259
(docstring prose); none in `_attempt_reconnect` (240-289).

Blast radius: `chumicro-repl --tail` (and any `tail()` caller) — Ctrl-C while waiting for a replug
yields a traceback / uncaught KeyboardInterrupt rather than the documented clean INTERRUPTED exit.
Drift between doc and behavior.

Fix: either add `except KeyboardInterrupt: return None` around the retry body (matching the doc and the
main-loop behavior), or correct the docstring to say Ctrl-C propagates. The TUI sibling
`_tui_reconnect` uses an explicit `exit_key` poll instead and doesn't make this claim — align on one.

---

## Scope B — webui (U-ids)

Localhost binding: every server binds `("127.0.0.1", …)` (server.py:89, session.py:156, checked by
grep — no `0.0.0.0` anywhere). Path traversal: `.scratch/hunt-tail/probe_traversal.py` hit
`SimpleHTTPRequestHandler` with `/../`, `/%2e%2e/`, `/..%2f`, `/....//` — all 404, no leak. Picker
attribution: picks/notes/edits are keyed per-card by DOM traversal (`c.querySelector`) under a
per-card `name="pick:<id>"` radio group — structurally sound. `body_html`/`intro_html`/section html are
unescaped by explicit documented design (spec author = the orchestrating agent, trust boundary stated
in render_picker.py:178-179); every other spec field routes through `html.escape`. Only one nit:

### U1 · low · webui/kit.py:132-134 — `chuProgress` writes an unescaped `text` into innerHTML

What happens: `sse_client_js`'s `chuProgress(v, text)` sets
`p.innerHTML = '<div class="bar" style="width:'+Math.round(...)+'%"></div><span>'+(text||'')+'</span>'`.
`v` is numeric-safe (`Math.round`), but `text` is interpolated into innerHTML unescaped. `text` comes
from a `progress` SSE event (`webui.session` `_cmd_progress` / any localhost `/push`). The sibling
`chuToast` correctly uses `textContent`. A progress message containing `<`/markup (e.g. a filename like
`deploying app<x>.py`) is parsed as HTML — malformed render or trivial injection.

Confirmed by reading (kit.py:130-134): `chuToast` uses `.textContent`; `chuProgress` uses `.innerHTML`
with `+(text||'')+`. Same code reaches the live picker when `spec.live` is set (render_picker.py:1087).

Blast radius: low — source is the trusted localhost agent, page is the agent's own tab, not a
cross-origin/untrusted boundary. It's the one place a webui surface puts caller text into markup
without escaping; a stray `<` in a status string breaks the progress bar rendering.

Fix: build the progress bar with DOM nodes / set the label via `textContent` (mirror `chuToast`), or
escape `text` before interpolation.

---

## Cleared (checked, not findings)
- webui trusted-HTML unescaped fields (body_html/intro_html/section html/diff): documented trust
  boundary (render_picker.py:178), spec author is the agent — not a finding.
- webui `serve_oneshot`/`SessionServer` serve the whole working directory: localhost-only + scratch
  dir; low but expected. Concurrent `/submit` writes are last-wins, single-human tool.
- repl `close_quietly`/`__enter__`/`__exit__`/`_close_port`: FD teardown on every handshake/exit path is
  correct — no leaked handles. `sanitize_address` neutralizes path-traversal in `:save`/`:load` names.
- completion.py Tab round-trip drives the board into raw REPL and back (Ctrl-C Ctrl-C Ctrl-A … Ctrl-B)
  and always restores friendly REPL on every return path; 2 s bounded; soft-fails to None. Sound, though
  Tab sends Ctrl-C to the board (interrupts a still-running program) — by-design per the module doc.
