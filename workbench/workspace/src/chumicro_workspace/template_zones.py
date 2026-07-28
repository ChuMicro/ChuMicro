"""Two-zone classification for workspace files.

Workspaces are created by cloning the template repo directly (there
is no scaffolding CLI command).  These zones govern only what
`update` re-syncs into an existing workspace:

* **Tool-owned**: `run.py`, `AGENTS.md`, `CONTRIBUTING.md`,  <!-- noqa: CHU006 -->
  `pyproject.toml`, `projects/_template/`, `examples/`
  (reading-material demos shipped from the template), the
  agent-skill documents under `.github/skills/`, and the CI
  workflows under `.github/workflows/` (their headers declare
  themselves tool-owned, so `update` re-flows CI fixes; sibling
  custom workflows the user adds live outside this set and stay
  untouched).  `update` rewrites these so newer template releases
  flow in.

* **User-owned**: everything else, and it's the default.  Anything
  not explicitly tool-owned is left alone by `update`.  Covers
  `projects/<each-real-project>/`, `devices.yml`, `shared/`,
  `packages/`, `workspace.yml`, `secrets.toml`, and tracked-but-
  user-editable files like `README.md` / `.gitignore`.

The classification is computed against the *target* path (the path
relative to the workspace root), not the template-payload path.
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath


class Zone(Enum):
    """Two ownership zones."""

    TOOL_OWNED = "tool-owned"
    USER_OWNED = "user-owned"


#: Tool-owned exact-match paths.
TOOL_OWNED_PATHS: frozenset[str] = frozenset({
    "run.py",
    "AGENTS.md",  # noqa: CHU006  tool-owned template filename data
    "CONTRIBUTING.md",  # noqa: CHU006  tool-owned template filename data
    "pyproject.toml",
    # The chumicro tooling manifest `run.py setup` installs in regular mode.
    # Tool-owned so `update` keeps it in step with the CLI it pins.
    "requirements.txt",
})

#: Tool-owned directory prefixes.
TOOL_OWNED_PREFIXES: tuple[str, ...] = (
    "projects/_template/",
    ".github/skills/",
    ".github/workflows/",
    "examples/",
)

#: User-owned exact-match paths.
USER_OWNED_PATHS: frozenset[str] = frozenset({
    "workspace.yml",
    "secrets.toml",
    "devices.yml",
})

#: User-owned directory prefixes.
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
    falls through (`README.md`, `.gitignore`, and
    ``projects/<a-real-project>/...`` files the user created
    post-clone) counts as user-owned.
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
    return Zone.USER_OWNED
