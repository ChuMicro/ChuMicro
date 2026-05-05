"""Three-zone classification for workspace files.

Generalizes Decision 0029 §9's `devices.yml` ownership model to the
whole workspace tree.  Every file falls into one of three zones:

* **Tool-owned** — `run.py`, `AGENTS.md`, `CONTRIBUTING.md`,
  `pyproject.toml`, `projects/_template/`, `_workspace_template/`
  (template-source files used to materialize user-edited config
  like `workspace.yml` per Decision 0038 §5 and Decision 0057),
  `examples/` (Slice 5 reading-material demos shipped from the
  canonical template), and the agent-skill documents under
  `.github/skills/`.  `init` writes them; `update` rewrites them so
  newer template releases flow in.

* **User-owned** — `projects/<each-real-project>/`, `devices.yml`,
  `shared/`, `packages/`, `workspace.yml` (gitignored under
  Decision 0057).  `init` writes the starter version (only if
  absent); `update` never touches them.

* **Init-only** — `.gitignore`, `README.md`.  `init` writes if
  absent; `update` skips so user edits survive.

The classification is computed against the *target* path (the path
relative to the workspace root after the dotfile rename, when one
applies — the new template repo carries `.gitignore` directly so the
rename is mostly historical), not the template-payload path.
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath


class Zone(Enum):
    """Three ownership zones; see module docstring."""

    TOOL_OWNED = "tool-owned"
    USER_OWNED = "user-owned"
    INIT_ONLY = "init-only"


#: Files / paths that are tool-owned.  ``update`` rewrites them.
TOOL_OWNED_PATHS: frozenset[str] = frozenset({
    "run.py",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
})

#: Directory prefixes whose contents are tool-owned.  Anything below
#: a listed prefix is rewritten on ``update``.
TOOL_OWNED_PREFIXES: tuple[str, ...] = (
    "projects/_template/",
    "_workspace_template/",
    ".github/skills/",
    "examples/",
)

#: Files / paths that are user-owned.  ``update`` never touches them.
USER_OWNED_PATHS: frozenset[str] = frozenset({
    "workspace.yml",
    "devices.yml",
})

#: Directory prefixes whose contents are user-owned.  Anything below
#: is left alone on ``update``.
USER_OWNED_PREFIXES: tuple[str, ...] = (
    "shared/",
    "packages/",
)

#: Files / paths that are init-only.  ``init`` writes if absent;
#: ``update`` skips so user edits survive.
INIT_ONLY_PATHS: frozenset[str] = frozenset({
    ".gitignore",
    "README.md",
})


def classify(target_path: str) -> Zone:
    """Return the zone *target_path* falls into.

    *target_path* is the path relative to the workspace root.
    Forward slashes only.

    Lookup order: exact-match user-owned (so the starter
    ``workspace.yml`` is never clobbered by ``update``), user-owned
    prefixes (``shared/`` / ``packages/``), exact-match init-only,
    exact-match tool-owned, tool-owned prefixes (``projects/_template/``
    / ``_workspace_template/``).  Anything that falls through —
    typically ``projects/<a-real-project>/...`` files the user
    created post-init — counts as user-owned.
    """
    posix = PurePosixPath(target_path).as_posix()
    if posix in USER_OWNED_PATHS:
        return Zone.USER_OWNED
    if any(posix.startswith(prefix) for prefix in USER_OWNED_PREFIXES):
        return Zone.USER_OWNED
    if posix in INIT_ONLY_PATHS:
        return Zone.INIT_ONLY
    if posix in TOOL_OWNED_PATHS:
        return Zone.TOOL_OWNED
    if any(posix.startswith(prefix) for prefix in TOOL_OWNED_PREFIXES):
        return Zone.TOOL_OWNED
    # Default for unrecognized paths is user-owned — `projects/<my-project>/...`
    # post-init falls through here, and any custom files the user
    # adds at the workspace root.  We err on the side of "don't
    # touch" for `update`.
    return Zone.USER_OWNED
