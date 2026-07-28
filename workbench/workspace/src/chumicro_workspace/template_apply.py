"""Update / materialize-workspace-templates orchestration.

`update` fetches a fresh copy of the template upstream and re-flows
tool-owned files (the zones defined in
:mod:`chumicro_workspace.template_zones`) without touching
user-owned ones.  `materialize_workspace_templates` fills in the
first-write text for ``devices.yml`` / ``workspace.yml`` /
``secrets.toml`` from the readers in
:mod:`chumicro_workspace.templates` on first ``setup``.

``pyproject.toml`` is tool-owned, so `update` re-flows it, but
workspace users legitimately add their own host-side entries to its
``[project].dependencies`` array, and a blind overwrite would drop
them.  As a carve-out, when re-flowing ``pyproject.toml`` `update`
re-applies every requirement present in the on-disk file but absent
from the incoming upstream array, appending each (in on-disk order)
to the incoming document via ``tomlkit`` so upstream comments and
layout survive.  Requirements present in both arrays, or only
upstream, take their incoming form.  A user REMOVAL of an
upstream-shipped requirement is not preserved: upstream wins (the
template ships an empty array today, so that case is theoretical).
Comparison is on the raw requirement strings, not PEP 508 normalized
forms.  If either the on-disk or the incoming ``pyproject.toml`` is
unparseable TOML, or lacks a ``[project].dependencies`` array, the
carve-out is skipped and the plain overwrite stands, so this feature
never blocks an update.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
from tomlkit.exceptions import TOMLKitError

from chumicro_workspace.template_zones import Zone, classify

if TYPE_CHECKING:  # pragma: no cover - type-only
    from collections.abc import Iterable


#: Default upstream for ``update``.  Override when working with a fork.
DEFAULT_TEMPLATE_URL = (
    "https://github.com/ChuMicro/ChuMicro-Workspace-Template"
)

#: The one re-flowed file whose user-added ``[project].dependencies``
#: entries `update` carries across instead of overwriting.
_PYPROJECT_RELATIVE_PATH = "pyproject.toml"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class ApplyAction(StrEnum):
    """What happened to one file during an update / materialize pass."""

    #: Zone-skipped (user-owned on update) or already existed.
    SKIPPED = "skipped"
    #: Tool-owned, rewritten by `update` because bytes changed.
    REFRESHED = "refreshed"
    #: `update` write would have produced identical bytes (no-op).
    UNCHANGED = "unchanged"
    #: User-owned file written for the first time, seeded from the
    #: shipped template.
    MATERIALIZED = "materialized"


@dataclass
class ApplyReport:
    """Per-file actions taken during a single operation."""

    actions: list[tuple[str, ApplyAction]] = field(default_factory=list)
    #: Relative paths whose user-added ``[project].dependencies`` entries
    #: were carried across a re-flow rather than overwritten.  Only
    #: ``pyproject.toml`` qualifies today.
    dependency_preserved_paths: list[str] = field(default_factory=list)

    def add(self, target_relative: str, action: ApplyAction) -> None:
        self.actions.append((target_relative, action))

    def note_dependencies_preserved(self, target_relative: str) -> None:
        """Record that *target_relative* kept user-added dependency entries.

        Args:
            target_relative: The re-flowed file's workspace-relative path.
        """
        self.dependency_preserved_paths.append(target_relative)

    def count(self, action: ApplyAction) -> int:
        return sum(1 for _, taken in self.actions if taken == action)

    def __iter__(self) -> Iterable[tuple[str, ApplyAction]]:
        return iter(self.actions)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def update(
    target: Path,
    *,
    template_url: str = DEFAULT_TEMPLATE_URL,
    git_reference: str | None = None,
) -> ApplyReport:
    """Refresh the tool-owned slice of *target* from upstream.

    Clones the template upstream into a temporary directory, walks
    every file, classifies its destination via
    :func:`chumicro_workspace.template_zones.classify`, and:

    * Tool-owned: writes the upstream bytes (REFRESHED if changed,
      UNCHANGED if identical).  For ``pyproject.toml``, any user-added
      ``[project].dependencies`` requirement is re-applied onto the
      incoming array before the write.
    * User-owned and clone-seeded: skipped (SKIPPED).

    Args:
        target: Existing workspace root.
        template_url: Upstream URL.  Defaults to the ChuMicro repo.
        git_reference: Branch or tag to fetch.

    Returns:
        :class:`ApplyReport`.
    """
    if not target.exists():
        raise FileNotFoundError(f"workspace {target} does not exist")
    if not target.is_dir():
        raise NotADirectoryError(f"workspace {target} is not a directory")
    report = ApplyReport()
    with tempfile.TemporaryDirectory() as tmp:
        upstream = Path(tmp) / "upstream"
        _git_clone(template_url, upstream, git_reference=git_reference, depth=1)
        for source_file in _walk_tracked_files(upstream):
            relative = source_file.relative_to(upstream).as_posix()
            zone = classify(relative)
            if zone is not Zone.TOOL_OWNED:
                report.add(relative, ApplyAction.SKIPPED)
                continue
            incoming_bytes = source_file.read_bytes()
            target_path = target / relative
            incumbent_bytes = (
                target_path.read_bytes() if target_path.exists() else None
            )
            dependencies_preserved = False
            if relative == _PYPROJECT_RELATIVE_PATH and incumbent_bytes is not None:
                incoming_bytes, dependencies_preserved = (
                    _reflow_pyproject_preserving_dependencies(
                        incumbent_bytes, incoming_bytes,
                    )
                )
            if incumbent_bytes is not None and incumbent_bytes == incoming_bytes:
                report.add(relative, ApplyAction.UNCHANGED)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(incoming_bytes)
            report.add(relative, ApplyAction.REFRESHED)
            if dependencies_preserved:
                report.note_dependencies_preserved(relative)
    return report


def materialize_workspace_templates(workspace_root: Path) -> ApplyReport:
    """Materialize the first-write text for ``devices.yml`` /
    ``workspace.yml`` / ``secrets.toml`` into *workspace_root*.

    Existing files are never overwritten.  Re-running on a populated
    workspace produces a report of ``UNCHANGED`` entries.

    Returns a report whose entries are ``MATERIALIZED`` for each
    newly created file and ``UNCHANGED`` for each that already
    existed.
    """
    from chumicro_workspace.templates import (  # noqa: PLC0415
        read_devices_yml_template,
        read_secrets_toml_template,
        read_workspace_yml_template,
    )

    targets = (
        ("devices.yml", read_devices_yml_template),
        ("workspace.yml", read_workspace_yml_template),
        ("secrets.toml", read_secrets_toml_template),
    )
    report = ApplyReport()
    for relative_path, reader in targets:
        target_path = workspace_root / relative_path
        if target_path.exists():
            report.add(relative_path, ApplyAction.UNCHANGED)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(reader(), encoding="utf-8")
        report.add(relative_path, ApplyAction.MATERIALIZED)
    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_clone(
    url: str,
    target: Path,
    *,
    git_reference: str | None,
    depth: int | None,
) -> None:
    """Run ``git clone`` against *url* into *target*."""
    arguments = ["git", "clone"]
    if depth is not None:
        arguments.extend(["--depth", str(depth)])
    if git_reference is not None:
        arguments.extend(["--branch", git_reference])
    arguments.extend([url, str(target)])
    completed = subprocess.run(arguments, capture_output=True, check=False, text=True)  # noqa: S603 - args fully controlled
    if completed.returncode != 0:
        raise RuntimeError(
            f"git clone failed: {completed.stderr.strip() or completed.stdout.strip()}",
        )


def _walk_tracked_files(root: Path) -> list[Path]:
    """Return every regular file under *root* in deterministic order.

    Skips ``.git/`` and ``__pycache__/``.
    """
    files: list[Path] = []
    for entry in sorted(root.rglob("*")):
        if not entry.is_file():
            continue
        parts = entry.parts
        if ".git" in parts or "__pycache__" in parts:
            continue
        files.append(entry)
    return files


def _reflow_pyproject_preserving_dependencies(
    incumbent_bytes: bytes,
    incoming_bytes: bytes,
) -> tuple[bytes, bool]:
    """Merge user-added dependencies from the on-disk file into the upstream bytes.

    Reads ``[project].dependencies`` from both *incumbent_bytes* (the
    on-disk ``pyproject.toml``) and *incoming_bytes* (the fresh upstream
    copy).  Every requirement string present in the incumbent array but
    absent from the incoming array is a user addition; each is appended,
    in incumbent order, to the incoming document's array via ``tomlkit``
    so upstream comments and layout survive.  Requirements present in
    both arrays, or only in the incoming array, keep their incoming
    form; a user removal of an upstream-shipped requirement is not
    preserved.  Comparison is on the raw requirement strings: exact
    match, no PEP 508 normalization.

    Returns *incoming_bytes* unchanged (a plain overwrite) when either
    side is unparseable TOML or lacks a ``[project].dependencies``
    array, or when there are no user additions.

    Args:
        incumbent_bytes: The workspace's current ``pyproject.toml`` bytes.
        incoming_bytes: The fresh upstream ``pyproject.toml`` bytes.

    Returns:
        A ``(final_bytes, dependencies_preserved)`` pair.
        ``dependencies_preserved`` is ``True`` only when at least one
        user-added requirement was carried across.
    """
    incoming_document = _parse_toml_document(incoming_bytes)
    incumbent_document = _parse_toml_document(incumbent_bytes)
    if incoming_document is None or incumbent_document is None:
        return incoming_bytes, False
    incoming_dependencies = _project_dependencies_array(incoming_document)
    incumbent_dependencies = _project_dependencies_array(incumbent_document)
    if incoming_dependencies is None or incumbent_dependencies is None:
        return incoming_bytes, False
    incoming_requirements = [str(entry) for entry in incoming_dependencies]
    user_added = [
        str(entry)
        for entry in incumbent_dependencies
        if str(entry) not in incoming_requirements
    ]
    if not user_added:
        return incoming_bytes, False
    for requirement in user_added:
        incoming_dependencies.append(requirement)
    return tomlkit.dumps(incoming_document).encode("utf-8"), True


def _parse_toml_document(raw_bytes: bytes) -> tomlkit.TOMLDocument | None:
    """Parse *raw_bytes* into a style-preserving ``tomlkit`` document.

    Args:
        raw_bytes: Raw ``pyproject.toml`` bytes.

    Returns:
        The parsed document, or ``None`` when *raw_bytes* is not
        decodable UTF-8 or not parseable TOML.
    """
    try:
        return tomlkit.parse(raw_bytes.decode("utf-8"))
    except (TOMLKitError, UnicodeDecodeError):
        return None


def _project_dependencies_array(document: tomlkit.TOMLDocument) -> list[str] | None:
    """Return the mutable ``[project].dependencies`` array, or ``None``.

    Args:
        document: A parsed ``pyproject.toml`` document.

    Returns:
        The ``[project].dependencies`` array (a live ``tomlkit`` array
        that can be appended to), or ``None`` when the ``[project]``
        table or its ``dependencies`` array is absent.
    """
    project = document.get("project")
    if not isinstance(project, dict):
        return None
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return None
    return dependencies
