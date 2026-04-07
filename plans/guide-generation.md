# Guide generation template

Use this template to generate or update `docs/guide.md` for a Chumicro library.

## When to use

- After implementing a new library
- After adding significant new features to an existing library
- When `guide.md` still contains placeholder comments from scaffolding

## Instructions for the AI agent

Read the library's source code, docstrings, tests, and examples first. Then generate `docs/guide.md` following the required structure below. Every section is mandatory. Do not use placeholder comments — write real content derived from the actual code.

### Required structure

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
     "Using the sink directly"). Each section needs:
     - A 1–2 sentence explanation of what the feature does
     - A code snippet showing usage
     - Any important caveats or gotchas -->

## Runner pattern

<!-- If the library's classes implement check(now_ms) -> bool, show how to
     wire them into a Runner from chumicro-runner. If the
     library has no tasks, omit this section. -->

## Memory notes

<!-- For libraries that manage buffers, queues, or pre-allocated structures:
     explain the allocation strategy and any tuning knobs (e.g., max_size).
     Omit for libraries with no interesting allocation behavior. -->

## Platform notes

<!-- Runtime-specific behavior, limitations, or fallback chains. If the
     library works identically on all three runtimes, say so in one line.
     If there are differences (e.g., tick source resolution order), list
     them. -->
```

### Rules

1. **Derive everything from code.** Do not invent features or parameters that don't exist in the source. Check the `__init__.py` exports for the public API surface.
2. **Code snippets must be copy-pasteable.** Import from the public package (`from chumicro_timing import Heartbeat`), not internal modules. Use realistic variable names.
3. **Keep it short.** A guide for a small library should be 80–150 lines of markdown. Don't pad.
4. **No API reference in the guide.** The guide shows *how to use* things. Parameter lists, return types, and exceptions belong in `api.md` (auto-generated from docstrings).
5. **Match existing tone.** Look at the timing library's `guide.md` for the established voice — direct, concrete, minimal prose between code blocks.
6. **Cross-reference.** Link to the examples directory and to `api.md` where appropriate. Use relative paths.

### Inputs to read before generating

For library `libraries/<name>/`:

1. `src/chumicro_<name>/__init__.py` — public exports
2. `src/chumicro_<name>/*.py` — all source modules (read docstrings)
3. `tests/` — test files show usage patterns and edge cases
4. `examples/` — runnable examples to reference or incorporate
5. `README.md` — quick example to stay consistent with

### Verification

After generating, check:

- [ ] Every section from the required structure is present (or explicitly omitted with rationale)
- [ ] Every public symbol from `__init__.py` is mentioned somewhere in the guide
- [ ] All code snippets use public imports only
- [ ] No placeholder comments remain (`<!-- ... -->`)
- [ ] The guide is ≤200 lines for a small library

