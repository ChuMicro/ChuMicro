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
Implementation lives in `chumicro_repl._follow` — the underscore
prefix is just to keep Python's submodule-import machinery from
shadowing the top-level `tail` attribute.

::: chumicro_repl._follow
    options:
      heading_level: 3

## Interactive TUI

::: chumicro_repl.tui
    options:
      heading_level: 3

## Pattern detection

::: chumicro_repl.patterns
    options:
      heading_level: 3

## Highlighting

The `colorize()` function is exposed at the top level
(`from chumicro_repl import colorize, Theme, strip_ansi_sequences`).
It does not share the name of its module so the lazy-attr
indirection is unnecessary here.

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
