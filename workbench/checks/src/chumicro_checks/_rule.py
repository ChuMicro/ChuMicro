"""The :class:`Rule` abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from chumicro_checks._finding import Finding


class Rule(ABC):
    """A workspace lint rule.

    Subclasses set :attr:`code` (the ``CHU0NN`` identifier) and
    :attr:`description` (short prose for ``--help``), and implement
    :meth:`check` to walk the relevant paths under *repo_root* and
    return a list of findings.

    A rule that finds none of its target paths under *repo_root*
    returns an empty list — silent no-op rather than error.  This is
    how repo-specific rules (CHU006, CHU008) coexist in one package.
    """

    code: str
    description: str

    @abstractmethod
    def check(self, repo_root: Path) -> list[Finding]:
        """Return every finding under *repo_root*."""
