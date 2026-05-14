"""Init / update / materialize-workspace-templates orchestration.

`chumicro-workspace` `init` clones a workspace template repo into a
target directory.  `update` fetches a fresh copy of the template
upstream and re-flows tool-owned files (the zones defined in
:mod:`chumicro_workspace.template_zones`) without touching
user-owned ones.  `materialize_workspace_templates` fills in the
canonical first-write text for ``devices.yml`` / ``workspace.yml`` /
``secrets.toml`` from the readers in
:mod:`chumicro_workspace.templates` on first ``setup``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace.template_zones import Zone, classify

if TYPE_CHECKING:  # pragma: no cover — type-only
    from collections.abc import Iterable


#: Canonical workspace template repo.  Used as the default ``--from``
#: for ``init`` and ``update``.  Override via flag for forks.
DEFAULT_TEMPLATE_URL = (
    "https://github.com/ChuMicro/ChuMicro-Workspace-Template"
)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class ApplyAction(StrEnum):
    """What happened to one file during an init / update / materialize pass."""

    #: File landed in the target on a fresh `init`.
    WRITTEN = "written"
    #: Zone-skipped (user-owned on update) or already existed.
    SKIPPED = "skipped"
    #: Tool-owned, rewritten by `update` because bytes changed.
    REFRESHED = "refreshed"
    #: `update` write would have produced identical bytes — no-op.
    UNCHANGED = "unchanged"
    #: Workbench-owned starter freshly created (`materialize_workspace_templates`).
    MATERIALIZED = "materialized"


@dataclass
class ApplyReport:
    """Per-file actions taken during a single operation."""

    actions: list[tuple[str, ApplyAction]] = field(default_factory=list)

    def add(self, target_relative: str, action: ApplyAction) -> None:
        self.actions.append((target_relative, action))

    def count(self, action: ApplyAction) -> int:
        return sum(1 for _, taken in self.actions if taken == action)

    def __iter__(self) -> Iterable[tuple[str, ApplyAction]]:
        return iter(self.actions)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def init(
    target: Path,
    *,
    template_url: str = DEFAULT_TEMPLATE_URL,
    git_reference: str | None = None,
    force: bool = False,
) -> ApplyReport:
    """Clone the workspace template into *target*.

    Runs ``git clone --depth 1`` (with ``--branch <git_reference>`` when
    *git_reference* is given), removes the cloned ``.git``, and runs
    ``git init`` so the user's workspace starts as a fresh
    repository decoupled from the template upstream.

    Args:
        target: Workspace directory.  Must not exist or must be
            empty unless ``force=True`` is passed.
        template_url: Git URL to clone from.  Defaults to the
            canonical ChuMicro template.
        git_reference: Branch or tag to clone.  ``None`` (default) lets
            git pick the remote's HEAD.
        force: Allow cloning into a non-empty target by clearing
            it first.  Caller's responsibility to confirm intent.

    Returns:
        :class:`ApplyReport` listing the files copied (one
        ``WRITTEN`` per tracked file in the cloned tree).
    """
    if target.exists() and any(target.iterdir()):
        if not force:
            raise FileExistsError(
                f"target {target} is not empty (pass force=True to override)",
            )
        for entry in target.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    target.mkdir(parents=True, exist_ok=True)
    _git_clone(template_url, target, git_reference=git_reference, depth=1)
    _strip_dot_git(target)
    _git_init(target)
    return _report_init_files(target)


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
      UNCHANGED if identical).
    * User-owned and init-only: skipped (SKIPPED).

    Args:
        target: Existing workspace root.
        template_url: Upstream URL.  Defaults to the canonical repo.
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
            new_bytes = source_file.read_bytes()
            target_path = target / relative
            if target_path.exists() and target_path.read_bytes() == new_bytes:
                report.add(relative, ApplyAction.UNCHANGED)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(new_bytes)
            report.add(relative, ApplyAction.REFRESHED)
    return report


def materialize_workspace_templates(workspace_root: Path) -> ApplyReport:
    """Materialize the canonical first-write text for ``devices.yml`` /
    ``workspace.yml`` / ``secrets.toml`` into *workspace_root*.

    Existing files are never overwritten.  Idempotent — re-running on
    a populated workspace produces a report of ``UNCHANGED`` entries.

    Returns a report whose entries are ``MATERIALIZED`` for each
    newly created file and ``UNCHANGED`` for each that already
    existed.
    """
    # Local import: ``templates`` pulls in ``chumicro_deploy`` for the
    # devices.yml reader; deferring keeps module import cheap.
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
    completed = subprocess.run(arguments, capture_output=True, check=False, text=True)  # noqa: S603 — args fully controlled
    if completed.returncode != 0:
        raise RuntimeError(
            f"git clone failed: {completed.stderr.strip() or completed.stdout.strip()}",
        )


def _git_init(target: Path) -> None:
    """Run ``git init`` inside *target*."""
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        ["git", "init"],
        cwd=str(target),
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git init failed: {completed.stderr.strip() or completed.stdout.strip()}",
        )


def _strip_dot_git(target: Path) -> None:
    """Remove ``<target>/.git`` so the cloned workspace decouples from upstream."""
    dot_git = target / ".git"
    if dot_git.exists():
        shutil.rmtree(dot_git)


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


def _report_init_files(target: Path) -> ApplyReport:
    """Build a :class:`ApplyReport` listing every file under *target*."""
    report = ApplyReport()
    for entry in _walk_tracked_files(target):
        relative = entry.relative_to(target).as_posix()
        report.add(relative, ApplyAction.WRITTEN)
    return report
