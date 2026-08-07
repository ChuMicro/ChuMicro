# Decision 0100: The surfaces browser toolkit lives in-repo

Status: `accepted`
Date: `2026-07-04`
Summary: `.claude/surfaces/` is a pure-stdlib toolkit for the browser surfaces an agent renders for a human: a shared kit, a submit transport, an SSE live-canvas server, a picker, and the hub fronting them.
Related: Decision [0032](0032-workbench-host-tools.md) (the workbench folder is PyPI-publishable, surfaces deliberately is not), Decision [0052](0052-workbench-no-library-imports.md) (no-library-imports, a rule surfaces has no reason to satisfy), Decision [0066](0066-agent-runnable-clis.md) (TTY-aware agent-runnable front doors), Decision [0116](0116-surface-hub.md) (the surface hub: one server, one tab, surface lifecycle).

## Context

Agents present decisions, audit reports, and A/B compares to a human in a browser and read structured choices back. Left alone, each surface rolls its own HTML, CSS, JS, submit path, and theme, and they drift apart. About 2,500 lines accreted under `.claude/surfaces/` with no decision record — the drift audit's largest un-ADR'd subsystem. This records the shape.

## Decision

- **One shared construction layer.** `.claude/surfaces/kit.py` owns the single semantic palette (light plus a fully-overridden dark, asserted by `theme.py`'s dark-lint before any page ships), the page shell, the affordance helper, the content-key (a localStorage namespace hashed from page content, so a regenerated page opens clean instead of restoring a stale verdict), and the SSE client. Every surface — picker, report, compare — sits on it, so a palette, affordance, or theme fix lands once.
- **Self-contained pages, localhost transport.** Every page inlines its CSS and JS and works from `file://`; nothing loads from an external asset. The server is stdlib `http.server` bound to `127.0.0.1` on a free port, and is transport only — it never parses or applies a submission.
- **Two server shapes, one per interaction.** `server.py`'s `serve_oneshot` is submit-once: the first POST is written verbatim to a sink file and the process shuts down, so the process *completing* is itself the submit signal. `session.py`'s `SessionServer` is the persistent canvas: one stable URL opened once plus a server→browser SSE push channel, so each turn the agent overwrites the page and pushes `reload` / `toast` / `progress` into the same tab. SSE-down plus POST-up covers everything turn-based.
- **Skills drive it through a spec.** A skill writes a JSON spec; `render_picker.py` renders it to a self-contained `picker.html`; `serve_picker.py` loops the Submit POST back to the session as `selection.txt`. Copy-paste of the line-oriented blob is the always-available no-server fallback; the Submit button appears only over http. The agent is the trusted spec author, so `intro_html` / `body_html` ride unescaped.
- **In-repo, not a library.** surfaces is host-side agent/human tooling: never written to a board, never imported by a device library or a publishable workbench package. It lives under `.claude/` with the rest of the agent tooling, not under `libraries/` or `workbench/`. Pure stdlib, so any interpreter, skill, or live session drives it identically.
- **A generated copy, not a local original.** The package and its `surfaces` skill are one
  synced unit shared with the other repos that carry them; the canonical is
  `upstream-workspace/.claude/surfaces/`, emitted by its `bin/sync-surfaces`. Per-repo variance
  is limited to the palette, the hub name, the theme key, and the JS prefix. Fix the
  canonical: a local edit is overwritten by the next emit, and an improvement that starts
  here is harvested upstream before it is emitted back.
- **Agent-edited, gated.** A PostToolUse hook (`picker_edit_gate.py`) re-runs `validate_picker.py` on any agent edit to the renderer or validator, so a structure or JS-syntax regression surfaces in the same turn as the edit.

## Rejected

- **A bespoke standalone picker.** The picker began as its own page; it was folded into surfaces to consume the shared kit (git `c6ff25bf`), killing the three-different-accents drift and one-off theme bugs. A surface no longer owns its own palette.
- **A published surfaces library.** Shipping it as a PyPI or workbench package drags it into the release contract and the no-library-imports rules (Decisions 0032/0052) it has no reason to satisfy. It is tooling, not a deliverable.
- **Websockets for re-serve.** Re-serve is push-only; SSE is exactly that over the stdlib server, auto-reconnects, and adds no dependency. Websockets are reserved for the day a surface must stream up mid-page.

## Consequences

- One palette, affordance, or theme fix reaches every surface. A new surface writes a body and inherits the shell, the submit path, the theme toggle, and the live canvas.
- A new pick strategy is a branch in `pick_area_html` plus its CSS; the page JS stays strategy-agnostic (every strategy emits radios named `pick:<id>`).
- surfaces carries no device-flash and no import-time cost — it never leaves the host, and no library depends on it.
- The edit-gate makes the renderer safe to evolve by agent: a regression blocks the turn, not review.
