# Decision 0046: `libs/` → `shared/`, lazy `libraries/`, packages/ unchanged

Status: `accepted`
Date: `2026-05-02`
Related: Decision 0029 (workspace shape — supersedes §1 default layout
and §7 resolution order)

## Context

A fresh workspace template ships four code-bearing top-level folders:
`projects/`, `libs/`, `libraries/`, `packages/`.  Three of them have
historically been empty placeholders.  The 2026-05-02 multi-persona
audit named the cognitive load of "three folders, three behaviors,
three import paths" as a beginner-comfort smell — a first-week user
has to learn the difference between `libs/`, `libraries/`, and
`packages/` before they can act on shared code.

A first proposal (three-into-one with content classification, ADR
draft on 2026-05-02) collapsed all three into a single `libraries/`
with classification by content + a `libraries/.cache/` convention
for the gitignored mirror.  User push-back: that introduced
ceremony in the flat-helper case (`libs/foo.py` → folder + `__init__.py`)
and the `.cache/` convention was a hack.  The cleaner path: keep
folders separate but pick names that explain themselves, and make
the ones the user might never need lazy.

## Decision

**Three concrete changes.**

### 1. `libs/` → `shared/` (rename)

`libs/` reads as "library helpers" and conflates with `libraries/`.
`shared/` reads as "shared between my projects" — the actual
purpose.

`shared/` continues to ship pre-existing in the template (with
its own `README.md` explaining what goes in it), so beginners
discover it via `ls`-or-IDE-tree.  Imported as
`from shared.foo import bar` (no `__init__.py` required —
implicit namespace packages, Python 3.3+).

### 2. `libraries/` becomes lazy

Most workspaces never hold a chumicro-style library.  Shipping
the folder empty in the default template forced everyone to
learn what it's for, even users who'll never use it.  Lazy
materialization: `libraries/` doesn't ship in the template;
`python run.py new --library <name>` creates it the first time.

The folder's existence is an opt-in signal — if you have a
`libraries/`, you're someone who's chosen to scaffold a full
library.  Otherwise it's noise.

### 3. `packages/` unchanged in name and lifecycle

`packages/` ships pre-existing (already does).  Honest framing
of what it's for: a manual-drop area for third-party Python
source trees the user wants their projects to import on the
device — typically MicroPython-only / CircuitPython-only
libraries that don't ship to PyPI in any installable form, or
vendored copies of upstream forks.  Not a package manager and
not a contrast to pip; just a place to drop source trees the
import-graph walker should know about.

The "sync from manifest" capability that Decision 0029 §1
mentioned is aspirational and hasn't shipped; if/when it does,
this folder is its destination.

`packages/.gitignore` continues to wholesale-ignore everything
except itself + a new `README.md` explaining what the folder
is for.

### Resolution order (replaces Decision 0029 §7)

The import-graph walker keeps its tolerant-missing behavior —
each step skips silently when its path doesn't exist:

1. `workspace.yml`'s `library_sources:` overrides.
2. `workspace/shared/`  (was `libs/`)
3. Each `workspace/libraries/<name>/src/` (auto-discovered
   when `libraries/` exists).
4. `workspace/packages/`
5. Caller-supplied extras.

## Consequences

* **Template repo**: `git mv libs shared`, replace `shared/.gitkeep`
  with `shared/README.md` (explains the folder), add
  `packages/README.md` (same pattern), update
  `packages/.gitignore` to except the README, drop any
  `libraries/` directory (already not shipped).  Prose updates
  in `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `workspace.yml`
  to reference the new names.
* **Mono-repo (`chumicro-workspace`)**: `libs_dir` → `shared_dir`
  in `WorkspaceLayout`; `import_graph.build_search_paths` updated
  reference; `template_zones.py` zone-classifier "libs/" prefix
  → "shared/"; tests + docs flipped; `Decision 0029` §1 + §7
  edited in place to describe the current layout, with cross-links
  to this ADR for the rationale.
* **`workspace.yml`**: schema unchanged — `library_sources:`
  still the override mechanism.
* **chumicro-workspace bumps 0.1.0 → 0.2.0** (CLI behavior
  change: import-graph search path renamed; lazy `libraries/`
  scaffolding).
* **Beginner experience**: a fresh clone has `projects/`,
  `shared/` (with README), `packages/` (with README), plus the
  root files — three code-bearing entries instead of four,
  each one labeled.  No more "what goes in here?" empty
  placeholder.

## Alternatives considered

* **Three-into-one consolidation** (earlier draft of this ADR).
  Rejected for added ceremony in the flat-helper case and the
  `.cache/` hack.
* **Lazy `shared/` too** — only materialize when the user runs
  `new --shared <module>`.  Rejected: the README is the
  discoverability story; an empty folder with a README is a
  lesson, an absent folder isn't.
* **Drop `packages/` from the template** and lazy-create it.
  Rejected: same reason as `shared/` — the README's job is
  teaching, and you can't read a README that doesn't exist.
* **Keep `libs/` as the name**, just lazy-ize the others.
  Rejected: `libs` reads as "library helpers" and the
  conflation with `libraries/` is the actual confusion the
  audit named.  Renaming is the win.
* **Auto-discover any top-level folder with `*.py`** instead
  of an explicit search path list.  Rejected: too magic; harder
  to scope, debug, document.
