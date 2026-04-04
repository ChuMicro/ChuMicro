# Decision 0013: Documentation and Examples Standards

Status: `accepted`

## Context

Every publishable library needs user-facing documentation and runnable examples. Without a defined standard, libraries will ship with inconsistent quality, and contributors won't know what's expected. The timing library is the first candidate and should prove the pattern.

## Decision

### Required per library

Each library under `libraries/<name>/` must include:

1. **`README.md`** at the library root — the primary landing page. Must contain:
   - One-line description
   - Installation instructions (pip, circup, mip when available)
   - Quick example showing the most common use case
   - Link to full docs (once a docs site exists)
   - Platform compatibility notes (which runtimes are supported)

 2. **`docs/`** directory with structured documentation:
    - `guide.md` — user guide with required sections (see below)
    - `api.md` — API reference auto-generated from docstrings via mkdocstrings `:::` directives (see rules below)
    - Additional topic pages as needed (e.g., `testing.md` for libraries that ship test fakes)

 3. **`examples/`** directory with runnable scripts:
    - At least one example per major public feature
    - **Simulated examples** must run on CPython without hardware (use print output to show behavior).  These demonstrate API concepts and are the primary learning path.
    - **Hardware examples** target real boards (CircuitPython and/or MicroPython).  Mark them with `# requires: hardware` as the first line.  Name them `circuitpython_*.py` or `micropython_*.py`.  These show realistic usage with actual LEDs, buttons, sensors, etc.
    - File names should be descriptive: `heartbeat_blink.py`, not `example1.py`
    - Examples must use top-level code (no `def main()` or `if __name__ == "__main__":` guards) — this matches the CircuitPython/MicroPython convention where `code.py` runs at the top level.

### Example quality checklist

Every example must meet the requirements above *and* the quality standards below. These were established during the runner and timing library example rewrites and apply to all libraries going forward.

**Docstring requirements:**

- Module docstring must include an `Example output::` block showing representative output so readers understand behavior without running the code.  Hardware examples may omit this when the behavior is self-evident (e.g., LED blinks).
- Simulated examples must include "Runs on CPython, MicroPython, and CircuitPython."  Hardware examples must state which runtime they target (e.g., "Runs on CircuitPython.").
- Module docstring must open with a one-line title and a 1–3 sentence description of what pattern the example demonstrates.

**Realism:**

- Main-loop examples must use `while True` — that is what real embedded code looks like. Bounded `for` loops are acceptable only for examples demonstrating naturally bounded operations (e.g., timeout checks, calibration sequences).- `time.sleep()` in examples exists only to keep demo output readable.  The comment should say what the user would do here in a real project ("the rest of your main loop goes here — reading sensors, checking buttons, etc.").  Do not frame it as a CPython implementation detail ("avoid busy-spinning") — that is irrelevant to the reader.
- Sleep for yield must be small (0.01–0.1 s). Large sleeps (≥ 0.5 s) negate non-blocking timing patterns and confuse readers about how the library is meant to work.
- Simulation logic must use methods with descriptive names that explain what hardware they replace (e.g., `detect_motion()`, `read_temperature()`, `read_button()`), not bare flags or opaque counters. Include a docstring or comment showing the real-board equivalent (e.g., "On a real board: `return self._pin.value`").

**Inline documentation:**

- Examples are a learning tool for new users.  Every non-obvious line or pattern should have a comment explaining *why* it is there, not just *what* it does.
- Comments should be deliberately redundant across examples.  Each example must be self-contained — a reader should not need to have read other examples first.
- Explain library concepts inline where they first appear: what `tick()` does, what `poll()` returns, why the shared-timestamp pattern matters, what `check()` vs `handle()` means, etc.
- Graduate explanation depth with example complexity: basic examples explain fundamental concepts in detail; advanced examples can be terser about concepts already covered but must still explain new patterns.

**Coverage and progression:**

- Every public method and property of the library should appear in at least one example.
- Graduate complexity: simplest example first, advanced patterns last. Name files to make the progression obvious.
- Separate basic examples (entry-level, one concept) from advanced examples (ecosystem integration, multiple features). They may be different files.

**Code quality:**

- Examples must be self-contained — a reader should be able to copy-paste and run without external setup beyond installing the library.
- Keep examples short. A basic example should be 30–50 lines; an advanced example should be under 100 lines.
- Do not mix loop control logic (mode switches, counter resets) into the main loop body. Extract it into clearly named functions or methods.

### User guide (`guide.md`) required structure

Every library's `guide.md` must contain these sections. The scaffolder generates a template with instructions; contributors (human or AI) must replace all placeholder comments with real content derived from the source code.

| Section | Required? | Content |
|---|---|---|
| **Overview** | Always | 2–4 sentences: what the library does, why, core concept. Name key classes/functions. |
| **Getting started** | Always | The single most common usage as a copy-pasteable snippet. Public imports only. |
| **Feature sections** | When >1 feature | One section per major feature/usage pattern. Descriptive title, 1–2 sentence explanation, code snippet, caveats. |
| **Runner pattern** | When applicable | Show how to wire the library's components into a `Runner`. Omit if no `check()` method. |
| **Memory notes** | When applicable | Allocation strategy, buffer sizing, tuning knobs. Omit for libraries with no interesting allocation behavior. |
| **Platform notes** | Always | Runtime-specific behavior or "works identically on all three runtimes." |

Rules for guide content:

- **Derive from code.** Every claim must trace to source, docstrings, tests, or examples. Do not invent features.
- **Code snippets must be copy-pasteable.** Import from the public package, not internal modules.
- **No API reference.** The guide shows *how to use* things. Signatures and parameter lists belong in `api.md`.
- **No placeholder comments** (`<!-- ... -->`) in the final guide.
- **Keep it short.** 80–150 lines of markdown for a small library. Don't pad.
- **Match tone.** Direct, concrete, minimal prose between code blocks.

### AI generation of guides

Guides should be generated by an AI agent using the prompt at `plans/prompts/guide-generation.prompt.md`. This prompt tells the agent which source files to read and which sections to produce. Human contributors may also write guides by following the same structure.

The scaffolder template (`_GUIDE_TEMPLATE` in `scripts/run.py`) includes generation instructions that point to this prompt. A library must not be released with placeholder comments still in its guide.

### Documentation style

- Write docs in Markdown. This works as standalone GitHub-browsable content now and will be consumed by MkDocs for the built docs site.
- API docs should include the function/class signature, a brief description, parameter descriptions, return value, and any raised exceptions. Mirror the docstring but expand where helpful.
- Keep examples short and self-contained. A reader should be able to copy-paste an example and run it.
- Use fenced code blocks with language hints in Markdown docs.
- Cross-reference other docs pages with relative links.

### Docs build tool: MkDocs + Material + mkdocstrings

Chosen tool: **MkDocs** with the **Material** theme and **mkdocstrings** (Python handler via griffe).

Why:
- Markdown is the native format — existing `.md` files work as-is for narrative docs.
- `mkdocstrings` uses **static analysis** (griffe) to extract docstrings — it does not import modules, so CircuitPython-only imports (`supervisor`, `board`) don't cause build failures.
- ReadTheDocs has first-class MkDocs support via `.readthedocs.yaml`.
- Lowest setup complexity: one `mkdocs.yml` + three pip packages.

The trade-off: `:::` autodoc directives in `api.md` appear as raw text when browsing on GitHub. Narrative pages (`guide.md`, `testing.md`, `README.md`) look perfect on GitHub. The README already contains an API summary table for GitHub readers; the full auto-generated reference lives on the built site.

Not yet wired: the actual `mkdocs.yml` config, ReadTheDocs hosting setup, or the `docs` task in `scripts/run.py`. These are follow-up implementation items.

### Example verification

Examples are verified via static analysis in `scripts/run.py verify-examples`:

1. Each example is compiled to catch syntax errors.
2. The AST is walked to extract all `import` and `from … import …` statements.
3. Each imported module is resolved via `importlib`.  For `from X import Y`, the verifier also checks `hasattr(module, 'Y')` to catch renamed or removed symbols.
4. No example code is executed — verification is purely static.
5. **Hardware examples** (containing `# requires: hardware`) import platform-specific modules (`board`, `digitalio`, `machine`, etc.) that don't exist on CPython.  For these, only `chumicro_*` imports are verified — platform-specific imports are skipped.  This still catches API drift in our libraries while accepting that hardware modules can't be resolved on the host.
6. `verify-examples` runs as part of `preflight` and should run in CI.

**Why static verification instead of execution:**  Examples are intended for embedded devices and may depend on wifi, hardware, or device-specific configuration.  Running them as subprocesses would require timeouts (slow — 3s × N examples), skip markers for anything needing external resources, and process management.  The actual failure modes we need to catch — syntax errors, missing modules after refactors, renamed/removed symbols — are all detectable through AST inspection and import resolution.  Static verification is instant, deterministic, and works for any example regardless of its runtime dependencies.

**Why top-level style:**  CircuitPython and MicroPython run `code.py` at the top level — there is no `__name__ == "__main__"` mechanism.  Adafruit's own examples use top-level `while True` loops without guards.  Matching this convention means examples can be deployed to boards unchanged.

### Contributor expectations

- New libraries must include docs and examples before their first release. The `new-library` scaffolder already creates empty `docs/` and `examples/` directories.
- PRs that add or change public API must update `docs/api.md` for the affected library.
- PRs that add new features should include or update at least one example.
- Examples must use top-level code (no `def main()` / `__main__` guard) and pass `verify-examples`.
- Docs and examples are reviewed as part of normal code review.

### Release pipeline integration (future)

When the release pipeline is built (Milestone 2), it should:
- Verify that `docs/` is non-empty for any library being released.
- Build and publish docs to the hosting platform on version bumps.
- Include docs build as a preflight check (once `mkdocs.yml` is in place).

## Alternatives considered

- **Sphinx + MyST-Parser**: Powerful and the original RTD tool, but configuration is heavier and Markdown is an adapter rather than the native format. Sphinx's classic `autodoc` imports modules, which is problematic for CircuitPython-only code. `sphinx-autodoc2` avoids this but is less mature.
- **Require RST from the start**: rejected — adds tooling complexity. Markdown is readable on GitHub and MkDocs is Markdown-native.
- **No docs standard, let each library decide**: rejected — inconsistency is the predictable outcome.
- **Auto-generate everything from docstrings**: rejected as the sole path — docstrings are good for API reference but not for guides, examples, or platform notes.
- **Full execution testing for examples**: rejected — slow (3s timeout per example), requires skip markers for examples needing wifi/config/hardware, and the actual failure modes (syntax errors, missing imports, renamed symbols) are all detectable statically.  AST-based import verification is instant and deterministic.
- **Import-based verification with `__main__` guards**: rejected — required examples to diverge from the embedded `code.py` convention.  On-device testing revealed that imports from the workspace can be destructive on CircuitPython/MicroPython.
- **Subprocess + timeout**: superseded by AST-based verification — achieved the same detection of broken imports and syntax errors, but at 3s per example and with the looming problem of examples needing wifi or device configuration.
- **No example verification**: rejected — examples that silently break after refactors erode user trust.
