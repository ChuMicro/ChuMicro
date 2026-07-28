"""``LeakRule``: pattern-based file walker for repo-isolation rules.

Two rule families share this shape: a per-repo set of scan roots,
line-by-line matching of (regex, message, scope_predicate) tuples, and
``# noqa: <code>`` suppression. Only the scan roots and forbidden
patterns differ.

Each ``LeakRule`` instance carries:

* ``code``: stable rule identifier (``CHU006``, ``CHU008``).
* ``description``: short prose for ``--list``.
* ``scan_roots_for(repo_root)``: callable that resolves the
  directories to walk under the current repo.  An empty list means
  silent no-op (the rule's targets don't exist in this repo shape).
* ``patterns``: tuple of ``(re.Pattern, message, scope_predicate)``;
  each pattern fires only when ``scope_predicate(relative_path)``
  returns True, where ``relative_path`` is the file's path relative to
  the repo root.  A per-rule package-exemption stays local to that
  rule, and keying it on the repo-relative path means a leading-segment
  exemption can't be tricked by the absolute checkout path.
* ``suffixes``: file extensions walked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses, strip_noqa
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

#: A scope predicate decides whether a pattern applies to a given file.
ScopePredicate = Callable[[Path], bool]

#: A LeakRule pattern triple: regex, message, scope predicate.
LeakPattern = tuple[re.Pattern[str], str, ScopePredicate]


def everywhere(_filepath: Path) -> bool:
    """Default scope predicate: pattern fires for every walked file."""
    return True


class LeakRule(Rule):
    """A pattern-based file-walker rule for repo-isolation enforcement."""

    def __init__(
        self,
        *,
        code: str,
        description: str,
        scan_roots_for: Callable[[Path], list[Path]],
        patterns: tuple[LeakPattern, ...],
        suffixes: tuple[str, ...],
    ) -> None:
        self.code = code
        self.description = description
        self._scan_roots_for = scan_roots_for
        self._patterns = patterns
        self._suffixes = suffixes

    def check(self, repo_root: Path) -> list[Finding]:
        roots = self._scan_roots_for(repo_root)
        findings: list[Finding] = []
        seen_paths: set[Path] = set()
        for root in roots:
            for filepath in iter_text_files(root, suffixes=self._suffixes):
                # The scan-roots resolver may return overlapping
                # subtrees (e.g. ``support/`` plus
                # ``support/test_harness/``); de-dup so a file is only
                # walked once.
                if filepath in seen_paths:
                    continue
                seen_paths.add(filepath)
                findings.extend(self._check_file(filepath, repo_root))
        return findings

    def _check_file(self, filepath: Path, repo_root: Path) -> list[Finding]:
        try:
            text = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        # Scope predicates test the repo-root-relative path, so an
        # exemption keyed on a leading segment (``packages/``,
        # ``workbench/checks/``) matches the tree's own layout rather
        # than a coincidental segment in the absolute checkout path
        # above the repo root.
        try:
            scope_path = filepath.relative_to(repo_root)
        except ValueError:
            scope_path = filepath
        findings: list[Finding] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line_suppresses(line, self.code):
                continue
            scrubbed = strip_noqa(line)
            for pattern, message, scope_predicate in self._patterns:
                if not scope_predicate(scope_path):
                    continue
                if pattern.search(scrubbed):
                    findings.append(
                        Finding(
                            path=filepath,
                            line=line_number,
                            code=self.code,
                            message=message,
                        )
                    )
                    break
        return findings
