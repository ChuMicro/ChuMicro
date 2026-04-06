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
   - Links to hosted docs for both stable and experimental channels (e.g., `https://chumicro.github.io/ChuMicro/<name>/stable/`)
   - Links to GitHub-browsable docs (`docs/guide.md`, `docs/api.md`) under a "Browse on GitHub" subheading
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

**Hardware examples:**

- Hardware examples must include a **Setup** section in the docstring with numbered steps: (1) install the library packages — show the `circup` command for CircuitPython, `mpremote mip install` for MicroPython, with "or copy to `lib/`/board" as a fallback, (2) any wiring required (inline — no separate Wiring section), (3) how to deploy the file (e.g., "Save as `code.py`" or "Save as `main.py`").
- For examples using only the built-in LED, state "No extra wiring" inline in step 2.
- Note which pins may need to be changed for different boards (e.g., "Change `Pin(2)` to match your board").
- Name hardware examples `circuitpython_*.py` or `micropython_*.py`.
- Runner examples that depend on `chumicro_timing` must list it in the install step.
- Hardware examples need not include `time.sleep()` — tight loops are normal on real hardware where the main loop does real work.

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

The scaffolder template (`_GUIDE_TEMPLATE` in `scripts/scaffold.py`) includes generation instructions that point to this prompt. A library must not be released with placeholder comments still in its guide.

### Documentation style

- Write docs in Markdown. This works as standalone GitHub-browsable content now and will be consumed by MkDocs for the built docs site.
- API docs should include the function/class signature, a brief description, parameter descriptions, return value, and any raised exceptions. Mirror the docstring but expand where helpful.
- Keep examples short and self-contained. A reader should be able to copy-paste an example and run it.
- Use fenced code blocks with language hints in Markdown docs.
- Cross-reference other docs pages with relative links.

### Docs build tool: Zensical + mkdocstrings

Chosen tool: **Zensical** with **mkdocstrings** (Python handler via griffe).

Originally MkDocs + Material + mkdocstrings.  Migrated to Zensical (2026-04-05) because MkDocs 1.x is unmaintained (no releases in 18 months) and MkDocs 2.0 breaks all plugins, themes, and overrides with no migration path.  Zensical is from the Material for MkDocs team, reads existing `mkdocs.yml` files natively, and the mkdocstrings author is on the Zensical team.

Why:
- Markdown is the native format — existing `.md` files work as-is for narrative docs.
- `mkdocstrings` uses **static analysis** (griffe) to extract docstrings — it does not import modules, so CircuitPython-only imports (`supervisor`, `board`) don't cause build failures.
- Existing `mkdocs.yml` configs work with zero changes.
- Rust-core differential builds are near-instant.

### Docs hosting: GitHub Pages with mike versioning

Docs are published to **GitHub Pages** via GitHub Actions, with version management handled by **mike** (Zensical's fork: `git+https://github.com/squidfunk/mike.git`).  Mike manages the `gh-pages` branch, deploying each version to a subdirectory and maintaining a `versions.json` that powers the Material theme's version selector dropdown.

Each library is deployed independently using mike's `--deploy-prefix` flag.  **`--alias-type redirect` is required** — the default `symlink` creates git symlinks that GitHub Pages serves as plain text files (producing 404s).  The `redirect` type creates proper HTML redirect pages for each alias path:

```
mike deploy --deploy-prefix timing -F libraries/timing/mkdocs.yml --alias-type redirect 0.1.0 stable --push
mike deploy --deploy-prefix runner -F libraries/runner/mkdocs.yml --alias-type redirect 0.1.0 stable --push
```

This produces a URL structure of `/<library>/<version>/`:

- `chumicro.github.io/ChuMicro/timing/stable/` — alias to latest released version
- `chumicro.github.io/ChuMicro/timing/0.1.0/` — pinned version
- `chumicro.github.io/ChuMicro/timing/experimental/` — pre-release from `main`

Each library has its own `versions.json` under its prefix, so version selectors are independent per library.

Each library's `docs/` directory must include an `index.md` that serves as the landing page (linked from the `Home` nav entry in `mkdocs.yml`).  Without it, the version root URL (e.g., `/timing/0.1.8/`) has no `index.html` and GitHub Pages returns a 404.

Channel mapping in CI:
- Push to `main`: `mike deploy --deploy-prefix <lib> --alias-type redirect dev experimental`
- Promote (stable): `mike deploy --deploy-prefix <lib> --alias-type redirect <version> stable`

Each library's `mkdocs.yml` includes `extra.version.provider: mike` and `extra.version.default: [stable, experimental]` so that both current channels suppress the "outdated version" warning.  Pinned old versions show the warning.

Why GitHub Pages over ReadTheDocs:
- **Free for both private and public repos.**  ReadTheDocs Community is free for public repos (ad-supported) but requires a paid Business plan for private repos.
- **No external account.**  Deploys directly from GitHub Actions — no additional service to configure or maintain.
- **Mono-repo friendly.**  Each library's docs build into a subdirectory of one combined site, served at the org domain.  RTD's model is one project = one docs build, requiring either a combined build (losing per-library version independence) or subprojects (admin overhead per library).
- **Full control over site structure.**  Channel separation, version switching, and URL layout are all under our control.

ReadTheDocs remains a viable option if the project goes public and wants built-in versioned docs dropdown, server-side search, or analytics without additional tooling.  The Zensical build is compatible with both hosts.  If RTD is revisited, create a new decision that updates this one.

The trade-off: `:::` autodoc directives in `api.md` appear as raw text when browsing on GitHub. Narrative pages (`guide.md`, `testing.md`, `README.md`) look perfect on GitHub. The README already contains an API summary table for GitHub readers; the full auto-generated reference lives on the built site.


### Example verification

Examples are verified via static analysis in `scripts/run.py verify-examples`:

1. Each example is compiled to catch syntax errors.
2. The AST is walked to extract all `import` and `from … import …` statements.
3. Each imported module is resolved via `importlib`.  For `from X import Y`, the verifier also checks `hasattr(module, 'Y')` to catch renamed or removed symbols.
4. No example code is executed — verification is purely static.
5. **Hardware examples** (files named `circuitpython_*.py` or `micropython_*.py`) import platform-specific modules (`board`, `digitalio`, `machine`, etc.) that don't exist on CPython.  For these, only `chumicro_*` imports are verified — platform-specific imports are skipped.  This still catches API drift in our libraries while accepting that hardware modules can't be resolved on the host.
6. `verify-examples` runs as part of `preflight` and should run in CI.

**Why static verification instead of execution:**  Examples are intended for embedded devices and may depend on wifi, hardware, or device-specific configuration.  Running them as subprocesses would require timeouts (slow — 3s × N examples), skip markers for anything needing external resources, and process management.  The actual failure modes we need to catch — syntax errors, missing modules after refactors, renamed/removed symbols — are all detectable through AST inspection and import resolution.  Static verification is instant, deterministic, and works for any example regardless of its runtime dependencies.

**Why top-level style:**  CircuitPython and MicroPython run `code.py` at the top level — there is no `__name__ == "__main__"` mechanism.  Adafruit's own examples use top-level `while True` loops without guards.  Matching this convention means examples can be deployed to boards unchanged.

### Contributor expectations

- New libraries must include docs and examples before their first release. The `new-library` scaffolder already creates empty `docs/` and `examples/` directories.
- PRs that add or change public API must update `docs/api.md` for the affected library.
- PRs that add new features should include or update at least one example.
- Examples must use top-level code (no `def main()` / `__main__` guard) and pass `verify-examples`.
- Docs and examples are reviewed as part of normal code review.

### Release pipeline integration

- `docs-build` CI job verifies all library docs build on every PR (Zensical).
- `docs-deploy.yml` workflow deploys docs on push to `main` (experimental) and via `workflow_dispatch` with `channel=stable` (stable, called by `promote.yml`):
  - **push to main**: deploys each library at version `dev` with alias `experimental`.
  - **promote (stable)**: deploys each library at its VERSION (e.g., `0.1.0`) with alias `stable`, sets `stable` as the default redirect for `/<lib>/`.
  - Uses mike with `--deploy-prefix <lib>` per library, pushing to the `gh-pages` branch.
  - Concurrency group prevents conflicting deploys.
- The `mkdocs.yml` configs, `docs` task in `scripts/run.py`, and the `new-library` scaffolder are all wired.
- GitHub Pages must be configured to serve from the `gh-pages` branch (repository setting).

## Alternatives considered

- **Sphinx + MyST-Parser**: Powerful and the original RTD tool, but configuration is heavier and Markdown is an adapter rather than the native format. Sphinx's classic `autodoc` imports modules, which is problematic for CircuitPython-only code. `sphinx-autodoc2` avoids this but is less mature.
- **Require RST from the start**: rejected — adds tooling complexity. Markdown is readable on GitHub and MkDocs is Markdown-native.
- **No docs standard, let each library decide**: rejected — inconsistency is the predictable outcome.
- **Auto-generate everything from docstrings**: rejected as the sole path — docstrings are good for API reference but not for guides, examples, or platform notes.
- **Full execution testing for examples**: rejected — slow (3s timeout per example), requires skip markers for examples needing wifi/config/hardware, and the actual failure modes (syntax errors, missing imports, renamed symbols) are all detectable statically.  AST-based import verification is instant and deterministic.
- **Import-based verification with `__main__` guards**: rejected — required examples to diverge from the embedded `code.py` convention.  On-device testing revealed that imports from the workspace can be destructive on CircuitPython/MicroPython.
- **Subprocess + timeout**: superseded by AST-based verification — achieved the same detection of broken imports and syntax errors, but at 3s per example and with the looming problem of examples needing wifi or device configuration.
- **No example verification**: rejected — examples that silently break after refactors erode user trust.
