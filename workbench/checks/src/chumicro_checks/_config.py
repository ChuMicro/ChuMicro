"""Per-repo configuration loaded from ``pyproject.toml``.

Each repo can configure ``chumicro-checks`` via a ``[tool.chumicro-checks]``
table::

    [tool.chumicro-checks]
    ignore = ["CHU012"]

Recognized keys:

* ``ignore``: list of CHU codes to skip in this repo.

Unknown keys are tolerated silently. Future versions may add config
keys that older installed packages should ignore rather than fail on.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Resolved chumicro-checks configuration for a single repo."""

    ignore: frozenset[str] = frozenset()


def load_config(repo_root: Path) -> Config:
    """Read ``[tool.chumicro-checks]`` from *repo_root*'s ``pyproject.toml``.

    Returns the default :class:`Config` when the file or section is
    missing. No config is not an error.  A malformed TOML file
    raises ``tomllib.TOMLDecodeError`` so the user sees the parse
    error directly rather than getting an opaque empty config.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return Config()
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("tool", {}).get("chumicro-checks", {})
    raw_ignore = section.get("ignore", [])
    if not isinstance(raw_ignore, list):
        return Config()
    ignore = frozenset(
        str(token).strip().upper() for token in raw_ignore if str(token).strip()
    )
    return Config(ignore=ignore)
