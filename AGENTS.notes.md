# AGENTS.notes — why each rule exists

One line per rule: the concrete thing that forced it, then where the depth
lives. `→ <hash>` = `git show <hash>`; `ADR NNNN` = `plans/decisions/NNNN-*`.
**Not auto-loaded** — open only when a rule's reasoning is non-obvious or
you're about to argue with it. Read the anchor, don't expect the full story here.

## Session start

- **Handoff ≠ resume.** Auto-triggering resume off a `## Now` handoff pointer
  derailed sessions booted for unrelated work. → `54ad81d5`
- **Dead-ADR filename markers.** At 75+ records, dead ADRs were
  indistinguishable from live ones in `ls`; the in-file status field doesn't
  show in a flat listing. `SUPERSEDED-BY-NNNN` names the replacement; `INERT` =
  reversed, no successor. ADR 0076 → `de2d96dd`

## Keeping plans and docs current

- **Drift backstop.** The 2026-05-16 adversarial sweep (16 agents) found
  prose-only contracts shipped wrong (false TLS docstring, README crashing on
  MicroPython, 5 phantom CLI commands) while mechanized lints held at 0 — so a
  lintable drift class *must* be linted. ADR 0074 → `c6c64ee2`
- **Done ledger cap 25→5.** Verbose `## Done` entries put detail in the index
  that belonged in commit messages. → `b474b45d`
- **Read the ADR README first.** Decision 0038's principle→mechanism narrowing
  slipped through because ADR edits never routed past the authoring rules.
  → `59ee9f36`

## Workflow

- **Commit to `main`** — policy while private; retires when the repo opens.
- **No backcompat until 1.0** — nothing on PyPI yet; retires at 1.0.
- **Secrets only in `secrets.toml`.** The `!secret` marker (ADR 0035) was
  imported from Home Assistant's *shared-config* case; pointless here since the
  schema file is itself gitignored. `workspace.yml`'s name misled beginners
  (2026-05-06 usability audit). ADR 0057
- **Heredoc commit messages.** The old `.scratch/commit-msg.txt` path was a
  workaround for Copilot's terminal truncating multi-line input — N/A to Claude
  Code; heredoc preserves backticks/arrows/newlines. → `659039b1`
- **Suppressions** — mechanism, not an incident: `# noqa: CHU0NN` /
  `<!-- noqa: CHU0NN -->` / `# pragma: no cover`, each with a verifiable *why*.

## Testing

- **`run.py test` vs bare `pytest`.** One pytest run across all libraries hit
  `ImportPathMismatchError` from duplicate unqualified test-module names
  (`test_cli.py`, `test_recovery.py`); per-package subprocess kills it. Bare
  pytest gates no coverage. ADR 0009 → `096aac79`
- **94% is scoped.** CPython-reachable, post-`# pragma: no cover` — device
  adapters blanket-pragma because the imports don't exist under CPython (~20 in
  `sockets` alone). Dual gate (85% human / 94% agent) cut contributor friction.
  ADR 0025 → `26d278a8`
- **Loud skips.** A multi-session audit found 13 wifi tests bare-returning on
  missing creds (conftest bug, faked PASS) + 10 zero-assertion tests; a
  fresh-clone contributor saw "all green" with network tests never running.
  ADR 0058 → `d9230519`
- **No `import pytest` in cross-runtime tests.** ~800 tests ran CPython-only
  despite being cross-runtime-capable; a pytest import auto-scopes the file.
  ADR 0003 + ADR 0016 → `f31562be`
- **Pico W per-file is a must-fix.** The Pi Pico W (264 KB SRAM — the
  tier-floor board, ADR 0015) hits two walls: bulk-staging a heavy suite hits
  "No space left" at the ~491 KB CIRCUITPY drive *before any test runs*; a big
  module's resident defs also OOM on a fresh VM. Coarse CP data: ≈32 tests/file
  passes, ≈61 OOMs. No fixed cap — bench-determined, CP≠MP. ADR 0072
  → `5bb0a737`
- **Test dependency boundary** — own `src/`+`testing.py`, stdlib, pytest,
  `support/test_harness/` only. Cross-package data → in-repo fixture. Closest
  ADR is 0010 (library testability); otherwise project policy, no dedicated ADR.

## Code shape — libraries

- **Runner pattern.** Independent `ticks_ms()` calls drift on slow boards;
  capture time once per loop. The payoff is "LED keeps blinking through the TLS
  handshake" — nothing blocks the main loop. Was de-facto until named policy.
  ADR 0014 → `bcc6f6df`; ADR 0051 → `7f486f97`
- **Constructor injection.** Direct `time.monotonic()` etc. was untestable
  without monkeypatching or live hardware. ADR 0010 → `80def624`
- **Absolute imports on-device.** CircuitPython RAM-mode `exec()`s modules with
  no `__package__`, so relative imports break. ruff TID252.
- **No `typing` / `__future__`.** Annotations cost zero heap/flash (verified on
  MicroPython 1.26.0 + CircuitPython 10.1.4); `typing`/`__future__` don't exist
  there. ADR 0021 → `8d0adb09`
- **Runtime markers.** Pi Pico W uses 4 KB FAT clusters — ~51 files ≈ 204 KB of
  per-file overhead; ~10 wrong-runtime adapter files ≈ 40 KB dead weight per
  device. Every host-side deploy path filters, not just bundles (ADR 0044
  → `dfc99301`). `testing.py` mis-marked `cpython`-only broke 21/37 on-device
  unit files with `ImportError`. ADR 0037 → `662a5d7f`; ADR 0069 → `7804f31a`
- **No `__slots__` / passthrough `@property`.** 2026-05-11 audit: 17 `__slots__`
  (a no-op on MP/CP, pure dead source) + 89 `@property` (mostly passthrough,
  ~100 B/class on device, getter-call cost). ADR 0065 → `62032710`
- **Descriptive names.** Single-letter vars / abbreviations are C/Unix tribal
  knowledge — not universal for newcomers or non-native speakers. ADR 0022
  → `e6cc0d3b`

## Code shape — workbench

- **No library imports.** Workbench is CPython-native — use battle-tested PyPI
  packages, not the cross-runtime re-implementations; Decision 0036's "workbench
  helpers" idea was the lure. ADR 0052 → `7f486f97`
- **Classify failures.** Beginners get coached through hardware failures
  instead of a stack trace; generic `raise` is a UX defect. ADR 0053
  → `7f486f97`
- **Non-interactive mode.** An agent hitting `bootstrap`'s interactive
  port-pick wizard has no recovery but `kill`; `repl` follow-mode tail never
  ends in CI. ADR 0066 → `46716d29`

## Code comments / isolation / brevity

- **Comments = why-of-current-code only.** History/incidents/workstream
  pointers belong in the commit, ADR, or workstream file. → `e13df11b`
- **No mono-repo refs in publishable trees.** CHU rules centralized in
  `chumicro-checks` so the template repo + downstream workspaces can run them
  (`scripts/check_*.py` couldn't reach other repos). ADR 0060 → `ea4d3c20`;
  CHU006 activated → `14fde950`
- **Plans-doc brevity (CHU011).** → `c420cbbf`
- **`Phase N` needs a 3-word topic** — the bare number is opaque weeks later.

## Common pitfalls — the incidents

- **`python` not on PATH.** The Claude desktop-app shell (unlike the CLI)
  lacks a `python`→`python3` alias even with the venv installed. → `e969605d`
- **Web-search over recall.** An MP-copy-defect resume made training-knowledge
  assertions later disproved by reading the source. → `93b11799`
- **Don't touch CIRCUITPY mount state.** A macOS FSKit wedge →
  `diskarbitrationd` uninterruptible wait leaves the volume unmountable;
  manual `diskutil`/`eject` defeats the deploy code's mount probing + EACCES
  classifier. (Related: `os.sync()` after flash writes fixes stale "NO TESTS
  FOUND" reads — FatFs writes USB-MSC async.) ADR 0033 → `6fdc132b`,
  `96197f29`
- **No persisted `reset()` in `code.py`/`main.py`.** The runtime re-runs the
  file every boot → infinite loop until safe mode (physical replug). Hard reset
  is one-shot via raw REPL: `circuitpython_transport.py::_reset_into_bootloader`.
  → `2aedd665`
- **Staged paths ride into the next commit.** A pre-staged `mqtt/test_client.py`
  deletion rode into an unrelated `http_server` split — `main` had a
  deleted-but-not-replaced suite for one commit; cost a fixup + a broken-main
  window. → `1c420e11`
- **`init` is retired** — workspace creation is clone-only; the "thin wrapper"
  was unreachable as a real entry point. ADR 0075 → `ed23721c`
