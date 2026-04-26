"""Three-zone classification for template files.

Every file in a ChuMicro workspace template falls into one of three
ownership zones (mirrors Decision 0029 §9's devices.yml model, applied
to the whole template):

* **Tool-owned** — ``run.py``, ``AGENTS.md``, ``things/_template/``,
  ``pyproject.toml`` (the workspace's, where the chumicro-workspace-runtime
  pin lives).  ``init`` writes them; ``update`` rewrites them so newer
  template releases flow in.

* **User-owned** — ``things/<each-real-thing>/``, ``secrets.yml``,
  ``devices.yml``, ``libs/``, ``workspace.yml``.  ``init`` writes the
  starter version (only if absent); ``update`` never touches them.

* **Init-only** — ``.gitignore``, ``secrets.yml.example``, ``README.md``.
  ``init`` writes if absent; ``update`` skips so user edits survive.

The classification is computed against the *target* path (the path
relative to the workspace root after the dotfile rename), not the
template-payload path, because dot-prefix-renamed files (``dot_gitignore``
-> ``.gitignore``) need the post-rename name to match cleanly.
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
    "pyproject.toml",
})

#: Directory prefixes whose contents are tool-owned.  Anything below
#: a listed prefix is rewritten on ``update``.
TOOL_OWNED_PREFIXES: tuple[str, ...] = (
    "things/_template/",
)

#: Files / paths that are user-owned.  ``update`` never touches them.
USER_OWNED_PATHS: frozenset[str] = frozenset({
    "workspace.yml",
    "devices.yml",
    "secrets.yml",
})

#: Directory prefixes whose contents are user-owned.  Anything below
#: is left alone on ``update``.
USER_OWNED_PREFIXES: tuple[str, ...] = (
    "libs/",
    "packages/",
)

#: Files / paths that are init-only.  ``init`` writes if absent;
#: ``update`` skips so user edits survive.  The starter ``README.md``
#: lives here (template provides one; users freely edit it).
INIT_ONLY_PATHS: frozenset[str] = frozenset({
    ".gitignore",
    "secrets.yml.example",
    "README.md",
})


def classify(target_path: str) -> Zone:
    """Return the zone *target_path* falls into.

    *target_path* is the path relative to the workspace root, after
    any ``dot_`` -> ``.`` rename has been applied (so ``.gitignore``,
    not ``dot_gitignore``).  Forward slashes only.

    The lookup is: exact-match user-owned paths first (so the
    starter ``workspace.yml`` is never clobbered by ``update``), then
    user-owned prefixes (``libs/`` / ``packages/``), then exact-match
    init-only paths, then exact-match tool-owned paths, then
    tool-owned prefixes (``things/_template/``).  Anything that
    falls through — typically ``things/<a-real-thing>/...`` files
    the user created post-init — counts as user-owned.
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
    # Default for unrecognized paths is user-owned — `things/<my-thing>/...`
    # post-init falls through here, and any custom files the user
    # adds at the workspace root.  We err on the side of "don't
    # touch" for `update`.
    return Zone.USER_OWNED


def rename_dot_prefix(template_relative_path: str) -> str:
    """Convert a payload path's ``dot_`` prefix into a leading dot.

    Hatchling + pip's wheel build don't reliably ship dotfiles in
    package data, so the payload uses ``dot_gitignore`` /
    ``dot_gitkeep`` and apply renames on copy.

    Only the *file basename* is renamed; intermediate directories
    pass through unchanged.  ``things/_template/dot_gitignore`` ->
    ``things/_template/.gitignore``.
    """
    posix = PurePosixPath(template_relative_path)
    if posix.name.startswith("dot_"):
        renamed = "." + posix.name[len("dot_") :]
        return posix.with_name(renamed).as_posix()
    return posix.as_posix()
