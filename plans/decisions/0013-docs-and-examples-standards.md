# Decision 0013: Documentation and Examples Standards

Status: `accepted`
Date: `2026-04-02`
Summary: Each library ships `README.md` + `docs/` + `examples/`; examples import only the owning lib, declared deps, and sibling files; `verify-examples` is AST-only, not execution.
Related: Decision 0011 (platform targeting determines doc-publishing), Decision 0021 (docstring type policy)

## Context

Every publishable library needs user-facing documentation and runnable examples. Without a defined standard, libraries will ship with inconsistent quality, and contributors won't know what's expected. The timing library is the first candidate and should prove the pattern.

## Decision

### Required per library

Each library under `libraries/<name>/` ships:

1. **`README.md`** at the library root — landing page with one-line description, install instructions (pip / circup / mip), quick example, links to hosted docs (`https://chumicro.com/ChuMicro/<name>/{stable,experimental}/`), GitHub-browsable docs links, and platform compatibility notes.
2. **`docs/`** — `index.md` (landing), `guide.md` (user guide), `api.md` (auto-generated from docstrings via mkdocstrings `:::` directives), and topic pages as needed (`testing.md` etc.).
3. **`examples/`** — runnable scripts: simulated examples that run on CPython without hardware, plus optional hardware examples named `circuitpython_*.py` / `micropython_*.py` with `# requires: hardware` first line.  Top-level code only, no `if __name__ == "__main__":` guards (CP/MP run `code.py` at top level).

The full quality checklist — guide structure, docstring requirements, example realism rules, inline-comment policy — lives in [`docs/contributing/new-library.md`](../../docs/contributing/new-library.md).  This ADR fixes the slot shape; that doc fixes the per-slot content.

### Markdown native; Zensical + mkdocstrings build

Docs are written in Markdown.  Build tool: **Zensical** (Material-for-MkDocs successor — original MkDocs is unmaintained; MkDocs 2.0 breaks all plugins) with **mkdocstrings** for API extraction.  mkdocstrings uses static analysis via griffe, so CircuitPython-only imports (`supervisor`, `board`) don't break the build.  Existing `mkdocs.yml` configs work unchanged.

### Docs hosting: GitHub Pages with mike versioning

Docs are published to GitHub Pages via GitHub Actions.  **mike** (Zensical's fork) manages the `gh-pages` branch with one `versions.json` per library prefix.  Each library deploys independently using mike's `--deploy-prefix` flag, with `--alias-type redirect` (the default `symlink` produces 404s on GitHub Pages — symlinks are served as plain text).

URL shape: `/<library>/<channel-or-version>/` — `/timing/stable/`, `/timing/experimental/`, `/timing/0.1.0/`.  CI deploys `experimental` on every push to `main`; `stable` is set by `promote.yml`.

GitHub Pages over ReadTheDocs because: free for private repos (RTD requires paid Business), no external account, mono-repo-friendly subdirectory structure, full control over URL layout.  RTD remains compatible if revisited.

### Example dependency rule: owning library + declared deps + sibling helpers

An example may import only:

1. **Its owning library** (`libraries/<lib>/examples/foo.py` may `import chumicro_<lib>`).
2. **Libraries that owning-lib's `pyproject.toml` `dependencies` declares** (transitive deps the user pip-installs alongside owning-lib are fair game).
3. **Sibling files in its own `examples/` directory** — typically a per-library `helpers.py` containing wifi-up + msgpack decode + ticks math + per-board GPIO whitelists.  The deploy stack stages these alongside the entrypoint.

Examples may NOT import any other chumicro library, even if installed in the workspace's venv.  The point of an example is to teach what its owning library does — every additional import dilutes the lesson and (worse) misleads users into thinking the imported library is required.  An example demonstrating `chumicro-ntp` that also imports `chumicro-wifi` for wifi-up is structurally wrong: ntp doesn't need wifi to function (the socket factory does, separately), so the example is teaching a coupling the library doesn't have.

The `examples/helpers.py` pattern exists to provide what every example needs (wifi creds + connect, runtime config, GPIO abstractions, ticks) without inflating any single library's deps.  Each library's helpers.py is byte-identical to `scripts/templates/examples_helpers.py`, enforced by preflight, and re-implements upstream-library shapes inline (ticks_ms / ticks_add / ticks_diff mirror chumicro_timing; the msgpack decoder mirrors chumicro_msgpack).  When a new library needs something cross-cutting, extend helpers.py rather than reaching into another chumicro library.

A `chumicro-checks` lint that catches example imports outside the allowed set is the right enforcement surface for this rule; not yet shipped.

### Example verification: AST static analysis, not execution

`scripts/run.py verify-examples` compiles each example, walks the AST for imports, and resolves each import via `importlib`.  Hardware examples (files matching `circuitpython_*.py` / `micropython_*.py`) verify only `chumicro_*` imports — platform modules (`board`, `digitalio`, `machine`) are skipped because they don't exist on CPython.  No example code is executed; runs as part of `preflight`.

Static over execution because: examples target embedded devices and depend on wifi / hardware / device config; subprocess+timeout would need skip markers for every example needing external resources, costs ~3s per example, and the actual failure modes (syntax, missing modules, renamed symbols) are all detectable via AST inspection.  On-device testing also revealed that imports from the workspace can be destructive on CP/MP, ruling out import-based verification with `__main__` guards.

## Alternatives considered

- **Sphinx + MyST-Parser** — heavier config; classic `autodoc` imports modules (CP-incompatible); `sphinx-autodoc2` avoids that but is less mature.
- **RST from the start** — rejected; Markdown is GitHub-native and MkDocs/Zensical is Markdown-native.
- **No docs standard** — rejected; inconsistency is the predictable outcome.
- **Auto-generate everything from docstrings** — rejected as sole path; docstrings cover API reference but not guides, examples, or platform notes.
- **Full execution testing for examples** — rejected; slow, needs skip markers, doesn't detect anything AST verification doesn't.
- **No example verification** — rejected; silent breakage after refactors erodes user trust.
