"""Two-zone classification for workspace files.

Workspaces are created by cloning the template repo directly (there
is no scaffolding CLI command); these zones govern only what
`update` re-syncs into an existing workspace:

* **Tool-owned** — `run.py`, `AGENTS.md`, `CONTRIBUTING.md`,  <!-- noqa: CHU006 -->
  `pyproject.toml`, `projects/_template/`, `examples/`
  (reading-material demos shipped from the template), and
  the agent-skill documents under `.github/skills/`.  `update`
  rewrites these so newer template releases flow in.

* **User-owned** — everything else, and it's the default: anything
  not explicitly tool-owned is left alone by `update`.  Covers
  `projects/<each-real-project>/`, `devices.yml`, `shared/`,
  `packages/`, `workspace.yml`, `secrets.toml`, and tracked-but-
  user-editable files like `README.md` / `.gitignore` (the README
  title is meant to be renamed; users add their own ignore lines).

The classification is computed against the *target* path (the path
relative to the workspace root after the dotfile rename, when one
applies — the new template repo carries `.gitignore` directly so the
rename is mostly historical), not the template-payload path.
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath


class Zone(Enum):
    """Two ownership zones; see module docstring."""

    TOOL_OWNED = "tool-owned"
    USER_OWNED = "user-owned"


#: Files / paths that are tool-owned.  ``update`` rewrites them.
TOOL_OWNED_PATHS: frozenset[str] = frozenset({
    "run.py",
    "AGENTS.md",  # noqa: CHU006  tool-owned template filename data
    "CONTRIBUTING.md",  # noqa: CHU006  tool-owned template filename data
    "pyproject.toml",
})

#: Directory prefixes whose contents are tool-owned.  Anything below
#: a listed prefix is rewritten on ``update``.
TOOL_OWNED_PREFIXES: tuple[str, ...] = (
    "projects/_template/",
    ".github/skills/",
    "examples/",
)

#: Files / paths that are user-owned.  ``update`` never touches them.
USER_OWNED_PATHS: frozenset[str] = frozenset({
    "workspace.yml",
    "secrets.toml",
    "devices.yml",
})

#: Directory prefixes whose contents are user-owned.  Anything below
#: is left alone on ``update``.
USER_OWNED_PREFIXES: tuple[str, ...] = (
    "shared/",
    "packages/",
)


def classify(target_path: str) -> Zone:
    """Return the zone *target_path* falls into.

    *target_path* is the path relative to the workspace root.
    Forward slashes only.

    Lookup order: exact-match user-owned (so a materialized
    ``workspace.yml`` is never clobbered by ``update``), user-owned
    prefixes (``shared/`` / ``packages/``), exact-match tool-owned,
    tool-owned prefixes (``projects/_template/``).  Anything that
    falls through — `README.md`, `.gitignore`, and
    ``projects/<a-real-project>/...`` files the user created
    post-clone — counts as user-owned.
    """
    posix = PurePosixPath(target_path).as_posix()
    if posix in USER_OWNED_PATHS:
        return Zone.USER_OWNED
    if any(posix.startswith(prefix) for prefix in USER_OWNED_PREFIXES):
        return Zone.USER_OWNED
    if posix in TOOL_OWNED_PATHS:
        return Zone.TOOL_OWNED
    if any(posix.startswith(prefix) for prefix in TOOL_OWNED_PREFIXES):
        return Zone.TOOL_OWNED
    # Default for unrecognized paths is user-owned — `projects/<my-project>/...`
    # post-clone falls through here, and any custom files the user
    # adds at the workspace root.  We err on the side of "don't
    # touch" for `update`.
    return Zone.USER_OWNED
