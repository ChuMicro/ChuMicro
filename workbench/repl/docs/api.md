# API Reference

Auto-generated from docstrings via mkdocstrings.  All public names are
re-exported at the package top level via the lazy-attr table in
`chumicro_repl/__init__.py`; the per-module sections below mirror the
internal layout for readers who want to navigate by source file.

## Programmatic raw-REPL session

::: chumicro_repl.session
    options:
      heading_level: 3

## tail() and ExitCode

The `tail()` function and its `ExitCode` enum are exposed at the
package top level (`from chumicro_repl import tail, ExitCode`).
Implementation lives in `chumicro_repl._follow`; the underscore
prefix is just to keep Python's submodule-import machinery from
shadowing the top-level `tail` attribute.

::: chumicro_repl._follow
    options:
      heading_level: 3

## Interactive entry points

`interactive_line()` opens line mode (the default on a terminal) and
`interactive()` opens byte-passthrough mode.  Both are exposed at the
package top level; the passthrough run-loop and its reconnect
handling live here too.

::: chumicro_repl.tui
    options:
      heading_level: 3

## Line mode

The line-mode loop, its `:command` table (`BUILTIN_COMMANDS`), the
`LineModeContext` a command handler receives, and the
`CommandHandler` signature.  Pass an extended table to
`run_line_mode(commands=...)` to register your own commands.

::: chumicro_repl.line_mode
    options:
      heading_level: 3

## Tab completion

`fetch_device_names()` drives the friendly-REPL to raw-REPL to
`dir()` round-trip in one call; `build_default_completer()`
assembles the static keyword catalog and the device-backed source
into the completer line mode uses; `CompletionCache` holds the
fetched namespace and is what `:rescan` clears.

::: chumicro_repl.completion
    options:
      heading_level: 3

## Recovery layer

`InteractiveReplSession` is the wrapper around `ReplSession` that
classifies session-start failures (port not found, port busy,
permission denied, raw-REPL unresponsive) and walks the user
through a recovery plan.  Mid-session disconnects are *not*
routed through this module; those use the auto-reconnect loop
in `tail()` and `run_loop()`.

::: chumicro_repl.recovery
    options:
      heading_level: 3

## Pattern detection

::: chumicro_repl.patterns
    options:
      heading_level: 3

## Highlighting

`colorize()` and `Theme` are exposed at the top level
(`from chumicro_repl import colorize, Theme`).  `strip_ansi_sequences`
lives at the submodule path (`from chumicro_repl.highlight import
strip_ansi_sequences`) since it's mostly used by tests + log-capture
plumbing.

::: chumicro_repl.highlight
    options:
      heading_level: 3

## UTF-8 streaming decoder

::: chumicro_repl.framing
    options:
      heading_level: 3

## Test fakes

::: chumicro_repl.testing
    options:
      heading_level: 3

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · [PyPI](https://pypi.org/project/chumicro-repl/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
