---
name: guide-generation
description: How to generate or update docs/guide.md for a ChuMicro library. Use this skill when a library needs its user guide written or refreshed.
---

# Guide generation

Use this procedure to generate or update `docs/guide.md` for a ChuMicro library.

## When to use

- After implementing a new library (the scaffold generates placeholder comments — see `workbench/workspace/src/chumicro_workspace/_payloads/library_template/guide.md.template`)
- After adding significant new features to an existing library
- When `guide.md` still contains placeholder comments from scaffolding

Keep this document and the scaffold template (`workbench/workspace/src/chumicro_workspace/_payloads/library_template/guide.md.template`, loaded by `workbench/workspace/src/chumicro_workspace/scaffold.py`) synchronized — they define the same section order and requirements.

## Inputs to read before generating

For library `libraries/<name>/`:

1. `src/chumicro_<name>/__init__.py` — public exports
2. `src/chumicro_<name>/*.py` — all source modules (read docstrings)
3. `src/chumicro_<name>/testing.py` — test fakes (if present)
4. `tests/` — test files show usage patterns and edge cases
5. `examples/` — runnable examples to reference and list in the Examples table
6. `README.md` — quick example to stay consistent with

## Required structure

Sections marked *conditional* should be included when they apply and omitted otherwise.

```markdown
# User Guide

## Overview

<!-- 2–4 sentences: what the library does, why it exists, and the core concept.
     Name the key classes/functions. State the problem it solves. -->

## Getting started

<!-- The single most common usage pattern. Show a minimal working snippet
     that a user can copy-paste. Import from the public package, not
     internal modules. -->

## [Feature sections]

<!-- One section per major public feature or usage pattern. Section titles
     should be descriptive (e.g., "Multiple timers", "Using ticks directly",
     "Stream-based API"). Each section needs:
     - A 1–2 sentence explanation of what the feature does
     - A code snippet showing usage
     - Any important caveats or gotchas -->

## Runner pattern (conditional)

<!-- Include if the library's classes implement check(now_ms) -> bool.
     Show how to wire them into a Runner from chumicro-runner.
     Omit for libraries with no runner-compatible tasks. -->

## Memory notes (conditional)

<!-- Include if the library manages buffers, queues, or pre-allocated
     structures. Explain the allocation strategy and any tuning knobs
     (e.g., max_size). Omit for libraries with no interesting allocation
     behavior. -->

## Testing (conditional)

<!-- Include if the library ships test fakes in a testing submodule
     (e.g., chumicro_runner.testing.CallRecorder). Show a minimal
     test snippet using the fake with FakeTicks. Link to testing.md
     if the library has a dedicated testing docs page.
     Omit for libraries with no testing submodule. -->

## Platform notes

<!-- Runtime-specific behavior, limitations, or fallback chains. If the
     library works identically on all three runtimes, say so in one line.
     If there are differences (e.g., native C delegation, tick source
     resolution order), list them in a table. -->

## Examples

<!-- List all examples from the examples/ directory in a table:
     | Example | What it shows |
     Note which examples are simulated (CPython) vs hardware
     (circuitpython_* / micropython_*). -->

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](...) · [PyPI](...) · [Bundle](...) · [Experimental Bundle](...)

</div>
```

## Rules

1. **Derive everything from code.** Do not invent features or parameters that don't exist in the source. Check the `__init__.py` exports for the public API surface.
2. **Code snippets must be copy-pasteable.** Import from the public package (`from chumicro_timing import Heartbeat`), not internal modules. Use realistic variable names.
3. **Keep it proportional.** A guide for a small library (compat) should be ~100 lines. A larger library (runner) may need 200–270 lines. Don't pad, but don't force-compress either.
4. **No API reference in the guide.** The guide shows *how to use* things. Parameter lists, return types, and exceptions belong in `api.md` (auto-generated from docstrings).
5. **Match existing tone.** Look at the timing library's `guide.md` for the established voice — direct, concrete, minimal prose between code blocks.
6. **Cross-reference.** Link to the examples directory and to `api.md` where appropriate. Use relative paths for in-repo links.
7. **Include the footer.** Every guide ends with the `chumicro-footer` div containing Source, PyPI, Bundle, and Experimental Bundle links. The scaffold template generates this — preserve it.
8. **Delete scaffold placeholders.** If the guide was scaffolded, remove all `<!-- ... -->` comment blocks. The final guide should have no HTML comments.

## Verification

After generating, check:

- [ ] Every required section is present; conditional sections included or omitted with reason
- [ ] Every public symbol from `__init__.py` is mentioned somewhere in the guide
- [ ] All code snippets use public imports only
- [ ] No placeholder comments remain (`<!-- ... -->`)
- [ ] Examples table lists all files from `examples/`
- [ ] Footer div with Source/PyPI/Bundle links is present
