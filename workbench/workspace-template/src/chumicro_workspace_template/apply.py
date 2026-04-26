"""Walk a template directory and lay it down at a target path.

Two operations:

* :func:`init` — initial scaffold.  Walks every file under *source*,
  applies the ``dot_<name>`` -> ``.<name>`` rename, and writes each
  file at the corresponding location under *target*.  Refuses to
  overwrite existing files unless ``force=True``.
* :func:`update` — refresh the tool-owned slice of an existing
  workspace.  Walks every file under *source*, classifies the
  corresponding *target* path via :mod:`manifest`, and writes only
  the files in the :data:`Zone.TOOL_OWNED` zone (replacing whatever
  was there).  User-owned and init-only files are skipped.

Both operations report the per-file action via the ``ApplyReport``
dataclass so the CLI can summarize what landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace_template.manifest import (
    Zone,
    classify,
    rename_dot_prefix,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from collections.abc import Iterable


#: Directory at the top of the template payload tree shipped with this
#: package.  Resolved at import time so package data lookups stay simple
#: — the wheel ships the files under the same path.
DEFAULT_TEMPLATE_ROOT: Path = (
    Path(__file__).resolve().parent / "_payloads" / "default_template"
)


def default_template_root() -> Path:
    """Return the path to the package's built-in template payload.

    Useful for inspection or vendoring (a downstream package can copy
    the tree as a starting point for its own template).  Returns the
    wheel-installed location; resolve to absolute path and treat as
    read-only.
    """
    return DEFAULT_TEMPLATE_ROOT


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class ApplyAction(str):
    """One of: ``"written"`` (file landed), ``"skipped"`` (existed and
    we wouldn't overwrite), ``"refreshed"`` (tool-owned, rewritten on
    update), ``"unchanged"`` (write would have produced identical bytes).
    """

    WRITTEN = "written"
    SKIPPED = "skipped"
    REFRESHED = "refreshed"
    UNCHANGED = "unchanged"


@dataclass
class ApplyReport:
    """Per-file actions taken during a single :func:`init` /
    :func:`update` invocation.

    Each entry is ``(target_relative_path, ApplyAction)``.  Order
    follows the source-tree walk (alphabetical by sorted ``rglob``).
    """

    actions: list[tuple[str, str]] = field(default_factory=list)

    def add(self, target_relative: str, action: str) -> None:
        self.actions.append((target_relative, action))

    def count(self, action: str) -> int:
        return sum(1 for _, taken in self.actions if taken == action)

    def __iter__(self) -> Iterable[tuple[str, str]]:
        return iter(self.actions)


# ---------------------------------------------------------------------------
# init / update
# ---------------------------------------------------------------------------


def init(
    target: Path,
    *,
    source: Path | None = None,
    force: bool = False,
) -> ApplyReport:
    """Lay down a fresh workspace at *target* from *source*.

    Walks every file under *source* (defaults to the built-in
    template payload), applies the ``dot_`` rename, and writes each
    file under *target*.  Existing target files are skipped unless
    ``force=True``.  Empty directories under *source* are created
    under *target* so the layout is preserved (e.g. ``libs/`` shows
    up even if it has only a single ``dot_gitkeep`` file inside).

    Args:
        target: Workspace directory to create / populate.  Created
            (with parents) if it doesn't exist.
        source: Template payload root.  Defaults to the package's
            built-in template (:func:`default_template_root`).
        force: When ``True``, overwrite existing files at *target*.

    Returns:
        :class:`ApplyReport` describing every file's outcome.

    Raises:
        FileNotFoundError: *source* doesn't exist.
        NotADirectoryError: *source* exists but isn't a directory.
    """
    resolved_source = _resolve_source(source)
    target.mkdir(parents=True, exist_ok=True)
    report = ApplyReport()
    for source_file in _walk_source_files(resolved_source):
        relative = source_file.relative_to(resolved_source).as_posix()
        target_relative = rename_dot_prefix(relative)
        target_path = target / target_relative
        if target_path.exists() and not force:
            report.add(target_relative, ApplyAction.SKIPPED)
            continue
        _write_file(target_path, source_file.read_bytes())
        report.add(target_relative, ApplyAction.WRITTEN)
    return report


def update(
    target: Path,
    *,
    source: Path | None = None,
) -> ApplyReport:
    """Refresh the tool-owned slice of an existing workspace.

    Walks the template, classifies each target-relative path, and:

    * Writes ``Zone.TOOL_OWNED`` files (replaces whatever's there) —
      reports ``REFRESHED`` for changed bytes, ``UNCHANGED`` when
      identical.
    * Skips ``Zone.USER_OWNED`` and ``Zone.INIT_ONLY`` files — reports
      ``SKIPPED``.

    Args:
        target: Existing workspace directory.  Must exist.
        source: Template payload root.  Defaults to the package's
            built-in template.

    Returns:
        :class:`ApplyReport`.

    Raises:
        FileNotFoundError: *target* (or *source*) doesn't exist.
        NotADirectoryError: *target* (or *source*) isn't a directory.
    """
    if not target.exists():
        raise FileNotFoundError(f"target workspace {target} does not exist")
    if not target.is_dir():
        raise NotADirectoryError(f"target workspace {target} is not a directory")
    resolved_source = _resolve_source(source)
    report = ApplyReport()
    for source_file in _walk_source_files(resolved_source):
        relative = source_file.relative_to(resolved_source).as_posix()
        target_relative = rename_dot_prefix(relative)
        target_path = target / target_relative
        zone = classify(target_relative)
        if zone is not Zone.TOOL_OWNED:
            report.add(target_relative, ApplyAction.SKIPPED)
            continue
        new_bytes = source_file.read_bytes()
        if target_path.exists() and target_path.read_bytes() == new_bytes:
            report.add(target_relative, ApplyAction.UNCHANGED)
            continue
        _write_file(target_path, new_bytes)
        report.add(target_relative, ApplyAction.REFRESHED)
    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_source(source: Path | None) -> Path:
    """Validate / resolve *source* to a concrete directory path."""
    resolved = source if source is not None else DEFAULT_TEMPLATE_ROOT
    if not resolved.exists():
        raise FileNotFoundError(f"template source {resolved} does not exist")
    if not resolved.is_dir():
        raise NotADirectoryError(f"template source {resolved} is not a directory")
    return resolved


def _walk_source_files(source: Path) -> list[Path]:
    """Return every regular file under *source* in deterministic order.

    Skips ``__pycache__`` directories so package-build artifacts
    don't leak into the scaffolded workspace.
    """
    files: list[Path] = []
    for entry in sorted(source.rglob("*")):
        if not entry.is_file():
            continue
        if "__pycache__" in entry.parts:
            continue
        files.append(entry)
    return files


def _write_file(target_path: Path, content: bytes) -> None:
    """Create parents and write *content* atomically(-ish)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
