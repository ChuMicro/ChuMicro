"""The :class:`Finding` value type, one rule violation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One rule violation, ready to print or aggregate."""

    path: Path
    line: int
    code: str
    message: str

    def render(self, *, root: Path | None = None) -> str:
        """Return ``<path>:<line>: <code> <message>``.

        When *root* is provided, the path is rendered relative to it
        so output stays compact in repo-rooted invocations.
        """
        display_path = self.path
        if root is not None:
            try:
                display_path = self.path.relative_to(root)
            except ValueError:
                display_path = self.path
        return f"{display_path}:{self.line}: {self.code} {self.message}"
