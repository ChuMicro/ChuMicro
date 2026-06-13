# Decision 0090: Device deploys strip docstrings and comments

Status: `accepted`
Date: `2026-06-13`
Summary: Device deploys strip docstrings and `#` comments from every staged `.py`, blanking lines in place so deployed size tracks code not prose while statement line numbers stay stable.
Related: 0087 (generator substrate, RAM-mode inline strip), 0047 (flash deploy-mode default), 0015 (minimum board tier)

## Context

Flash-mode deploy shipped raw `.py` verbatim while RAM mode already stripped docstrings through `ast.unparse`.  Docstrings and comments are roughly three quarters of a staged library file's bytes, so a one-request demo plus the on-device test harness could not be staged on the 256 KB / ~800 KB-flash minimum board ([Decision 0015](0015-board-architecture-support.md)): a Pico W CircuitPython deploy ran out of flash at 2 KB free.  Deployed bytes also moved every time a comment was reworded, so any test that gates on staged size drifted.

## Decision

Both deploy paths strip docstrings and `#` comments from every staged `.py` before transfer, for CircuitPython and MicroPython.  RAM mode already did this inline through `ast.unparse`; flash and copy staging now do it too, through `chumicro_deploy.source_minify`.

The strip blanks the removed lines in place instead of deleting them, so every kept statement keeps its original line number.  That is load-bearing: the on-device test runner splits a staged file into chunks at top-level statement line numbers computed host-side from the unstripped source, and a device traceback points at the line of the staged file.  Deleting lines would desync both.

`strip_source` parses the input, parses its stripped output, and compares the two with docstrings removed; if they differ it returns the input verbatim.  That guard makes the cheap line-and-string comment scanner safe: a file it would corrupt — a `#` inside a multi-line string — deploys unstripped rather than broken.

`source_minify` owns the shared docstring-stripping AST transformer.  Flash and copy staging call `minify_python_tree` over the staging directory; RAM mode keeps its `ast.unparse` path, which minifies hardest for the raw-REPL chunk budget, and reuses only the transformer.

## Consequences

A library's verbose maintainer-facing docstrings no longer cost device flash: `chumicro_sockets` drops from ~57 KB of `.py` to ~12 KB on a board, and the minimum tier stages a basic demo and the on-device unit sweep again.  Deployed bytes track code, so rewording a comment no longer changes what lands, which stabilizes size-gated behavior.

Deployed files carry no docstrings, so on-device `__doc__` is empty; embedded code rarely reads it, and RAM mode already had this property.  A line-based comment scanner can mis-handle a multi-line string, but the equivalence guard contains that by shipping the file verbatim.
