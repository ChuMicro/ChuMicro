"""Update / materialize-workspace-templates orchestration.

`update` fetches a fresh copy of the template upstream and re-flows
tool-owned files (the zones defined in
:mod:`chumicro_workspace.template_zones`) without touching
user-owned ones.  `materialize_workspace_templates` fills in the
first-write text for ``devices.yml`` / ``workspace.yml`` /
``secrets.toml`` from the readers in
:mod:`chumicro_workspace.templates` on first ``setup``.

`update` records a fingerprint of every tool-owned file it applies
in ``.chumicro-template-state.json`` at the workspace root
(machine state; keep it gitignored).  On the next run that record
is the guard baseline: a tool-owned file whose on-disk content no
longer matches its last-applied fingerprint carries local edits, so
`update` refuses to overwrite it (and refuses to delete it when
upstream dropped the file) unless ``force=True``.  A file with no
recorded fingerprint (a workspace that has never run a
state-recording update, or a deleted state file) is unguarded and
overwritten as before; the fingerprints recorded by that run arm
the guard for every run after it.

`update` also reconciles deletions: a file it applied on an earlier
run that upstream no longer ships is deleted from the workspace,
with the same local-edit guard.  Only files the tool itself applied
are candidates, so user-created files inside tool-owned directories
(a custom workflow next to the shipped ones) are never touched.

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
carve-out is skipped and the incoming bytes are written as-is.

The guard treats ``pyproject.toml``'s ``[project].dependencies``
array as user territory to match that carve-out: its fingerprint
hashes the parsed document with the array removed, so a
dependencies-only edit stays clean and flows through the carve-out
silently, while an edit to any other knob (``requires-python``, a
``[tool.*]`` table) refuses without ``force=True``.  An on-disk
``pyproject.toml`` that no longer parses as TOML falls back to a
raw-bytes fingerprint, which cannot match the recorded one, so a
mangled file is refused rather than silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
from tomlkit.exceptions import TOMLKitError

from chumicro_workspace.atomic_write import atomic_write_text
from chumicro_workspace.template_zones import Zone, classify

if TYPE_CHECKING:  # pragma: no cover - type-only
    from collections.abc import Iterable


#: Default upstream for ``update``.  Override when working with a fork.
DEFAULT_TEMPLATE_URL = (
    "https://github.com/ChuMicro/ChuMicro-Workspace-Template"
)

#: Workspace-root JSON file recording the fingerprint of every
#: tool-owned file the last ``update`` applied.  Machine state, not
#: workspace content: the template's ``.gitignore`` keeps it out of git.
TEMPLATE_STATE_FILENAME = ".chumicro-template-state.json"

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
    #: Tool-owned file deleted by `update` because upstream no longer
    #: ships it.
    REMOVED = "removed"
    #: Overwrite or deletion refused: the on-disk content differs from
    #: the last-applied template version and ``force`` was not passed.
    REFUSED = "refused"


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
    force: bool = False,
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

    A tool-owned file whose on-disk fingerprint no longer matches the
    one recorded by the last update carries local edits: the write is
    refused (REFUSED) unless *force* is true.  Files recorded by an
    earlier update that upstream no longer ships are deleted
    (REMOVED), under the same guard.  Fingerprints live in
    ``.chumicro-template-state.json`` at the workspace root; a file
    with no recorded fingerprint is overwritten unguarded.

    Args:
        target: Existing workspace root.
        template_url: Upstream URL.  Defaults to the ChuMicro repo.
        git_reference: Branch or tag to fetch.
        force: Overwrite and delete tool-owned files even when their
            on-disk content differs from the last-applied version.

    Returns:
        :class:`ApplyReport`.
    """
    if not target.exists():
        raise FileNotFoundError(f"workspace {target} does not exist")
    if not target.is_dir():
        raise NotADirectoryError(f"workspace {target} is not a directory")
    report = ApplyReport()
    previous_state = _read_template_state(target)
    applied_state: dict[str, str] = {}
    upstream_relatives: set[str] = set()
    with tempfile.TemporaryDirectory() as tmp:
        upstream = Path(tmp) / "upstream"
        _git_clone(template_url, upstream, git_reference=git_reference, depth=1)
        for source_file in _walk_regular_files(upstream):
            relative = source_file.relative_to(upstream).as_posix()
            upstream_relatives.add(relative)
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
                applied_state[relative] = _fingerprint(relative, incoming_bytes)
                continue
            baseline = previous_state.get(relative)
            locally_edited = (
                incumbent_bytes is not None
                and baseline is not None
                and _fingerprint(relative, incumbent_bytes) != baseline
            )
            if locally_edited and not force:
                report.add(relative, ApplyAction.REFUSED)
                applied_state[relative] = baseline
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(incoming_bytes)
            report.add(relative, ApplyAction.REFRESHED)
            applied_state[relative] = _fingerprint(relative, incoming_bytes)
            if dependencies_preserved:
                report.note_dependencies_preserved(relative)
    _reconcile_deletions(
        target,
        previous_state=previous_state,
        applied_state=applied_state,
        upstream_relatives=upstream_relatives,
        force=force,
        report=report,
    )
    _write_template_state(target, applied_state)
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


def _walk_regular_files(root: Path) -> list[Path]:
    """Return every regular file under *root* in deterministic order.

    A plain filesystem walk (``rglob``), not a git listing.  Skips
    ``.git/`` and ``__pycache__/``.
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


def _reconcile_deletions(
    target: Path,
    *,
    previous_state: dict[str, str],
    applied_state: dict[str, str],
    upstream_relatives: set[str],
    force: bool,
    report: ApplyReport,
) -> None:
    """Delete tool-owned files applied earlier but absent upstream.

    Walks *previous_state* (last update's ``{relative: fingerprint}``
    record), so only files the tool itself applied are candidates:
    user-created files inside tool-owned directories never appear in
    the record and are never touched.  For each candidate absent from
    *upstream_relatives* and still classified tool-owned:

    * On-disk fingerprint matches the record: delete the file
      (REMOVED) and prune newly empty parent directories.
    * Fingerprint differs (local edits) and *force* is false: refuse
      (REFUSED) and carry the record forward in *applied_state* so
      a later run can still act on the file.
    * File already gone, or the path now classifies user-owned: drop
      the record silently.

    Args:
        target: Workspace root.
        previous_state: Fingerprints recorded by the last update.
        applied_state: Fingerprints for the record this update writes.
            Mutated: refused deletions keep their entry.
        upstream_relatives: Every file path the fresh clone ships.
        force: Delete even when the on-disk content differs from the
            recorded fingerprint.
        report: Report collecting the REMOVED / REFUSED actions.
    """
    for relative, baseline in sorted(previous_state.items()):
        if relative in upstream_relatives:
            continue
        if classify(relative) is not Zone.TOOL_OWNED:
            continue
        target_path = target / relative
        if not target_path.exists():
            continue
        on_disk_bytes = target_path.read_bytes()
        if _fingerprint(relative, on_disk_bytes) != baseline and not force:
            report.add(relative, ApplyAction.REFUSED)
            applied_state[relative] = baseline
            continue
        target_path.unlink()
        _prune_empty_directories(target_path.parent, stop=target)
        report.add(relative, ApplyAction.REMOVED)


def _prune_empty_directories(start: Path, *, stop: Path) -> None:
    """Remove *start* and its parents while empty, never touching *stop*.

    Ascends from *start* toward *stop*, deleting each directory that
    is empty.  Stops at the first non-empty directory or at *stop*
    itself, so deleting the last file of a nested tool-owned tree
    leaves no husk of empty directories behind.
    """
    current = start
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _read_template_state(workspace_root: Path) -> dict[str, str]:
    """Read the last update's ``{relative: fingerprint}`` record.

    Reads ``.chumicro-template-state.json`` at *workspace_root*.
    Fail-soft: a missing, unreadable, or malformed file reads as
    ``{}``, which leaves the local-edit guard unarmed for one run
    (the same behavior as a workspace that has never recorded state)
    rather than blocking the update.

    Args:
        workspace_root: Workspace root holding the state file.

    Returns:
        Mapping of workspace-relative path to fingerprint hex digest.
    """
    state_path = workspace_root / TEMPLATE_STATE_FILENAME
    try:
        raw_text = state_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    applied = document.get("applied") if isinstance(document, dict) else None
    if not isinstance(applied, dict):
        return {}
    return {
        relative: fingerprint
        for relative, fingerprint in applied.items()
        if isinstance(relative, str) and isinstance(fingerprint, str)
    }


def _write_template_state(
    workspace_root: Path, applied: dict[str, str],
) -> None:
    """Atomically write the ``{relative: fingerprint}`` record.

    Args:
        workspace_root: Workspace root holding the state file.
        applied: Fingerprint per tool-owned file this update applied
            (or carried forward for a refused file).
    """
    payload = {"applied": dict(sorted(applied.items()))}
    atomic_write_text(
        workspace_root / TEMPLATE_STATE_FILENAME,
        json.dumps(payload, indent=2) + "\n",
    )


def _fingerprint(relative: str, content: bytes) -> str:
    """Return the local-edit-guard fingerprint for one file's bytes.

    Plain SHA-256 of *content* for every file except
    ``pyproject.toml``, whose fingerprint hashes the parsed document
    with ``[project].dependencies`` removed: that array is user
    territory under the dependency-preserving carve-out, so an edit
    there must not read as a local edit.  A ``pyproject.toml`` that
    does not parse as TOML falls back to the raw-bytes hash, which
    cannot match a recorded structural fingerprint, so a mangled file
    reads as locally edited.

    Args:
        relative: Workspace-relative path, used to pick the scheme.
        content: The file bytes to fingerprint.

    Returns:
        Hex digest string.
    """
    if relative == _PYPROJECT_RELATIVE_PATH:
        normalized = _normalized_pyproject_structure(content)
        if normalized is not None:
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return hashlib.sha256(content).hexdigest()


def _normalized_pyproject_structure(content: bytes) -> str | None:
    """Serialize pyproject bytes to a comparison form without dependencies.

    Parses *content* as TOML, drops ``[project].dependencies``, and
    dumps the rest as sorted-key JSON, so two files that differ only
    in that array (or in comments and formatting) serialize
    identically.

    Args:
        content: Raw ``pyproject.toml`` bytes.

    Returns:
        The serialized structure, or ``None`` when *content* is not
        decodable UTF-8 or not parseable TOML.
    """
    try:
        document = tomllib.loads(content.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    project = document.get("project")
    if isinstance(project, dict):
        project.pop("dependencies", None)
    return json.dumps(document, sort_keys=True, default=str)


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
