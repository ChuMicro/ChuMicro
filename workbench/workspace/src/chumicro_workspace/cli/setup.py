"""``setup`` / ``update`` / ``new`` subcommands.

Workspace lifecycle entry points.  Workspaces are created by cloning
the template repo directly (no scaffolding command).  ``setup`` runs
the editable install plus template materialization on a freshly cloned
workspace.  ``update`` re-flows tool-owned template files from
upstream.  ``new`` scaffolds individual projects (or library /
workbench packages) inside an already-set-up workspace.
"""

from __future__ import annotations

import argparse
import keyword
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

from chumicro_workspace import template_apply
from chumicro_workspace.additive_apply import additive_reapply
from chumicro_workspace.chumicro_dev import (
    discover_chumicro_libraries,
    read_chumicro_dev_path,
    sync_library_sources,
)
from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _resolve_workspace,
)
from chumicro_workspace.scaffold import (
    LibraryAlreadyExistsError,
    scaffold_library,
)
from chumicro_workspace.template_apply import (
    DEFAULT_TEMPLATE_URL,
    ApplyAction,
    materialize_workspace_templates,
)
from chumicro_workspace.workspace import (
    ENTRY_POINT_FILENAMES,
    WorkspaceLayout,
)

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _pyproject_declares_dev_extra(pyproject: Path) -> bool:
    """Return True when *pyproject* declares a ``dev`` optional-dependency extra.

    Read from ``[project.optional-dependencies]``.  A workspace whose
    pyproject carries a ``dev`` extra (pytest / ruff / chumicro-checks)
    wants ``setup`` to install it so ``lint`` / ``test`` have their
    tools.  An unreadable or malformed pyproject falls back to ``False``
    so setup degrades to the bare editable install rather than crashing.
    """
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    optional = data.get("project", {}).get("optional-dependencies", {})
    return isinstance(optional, dict) and "dev" in optional


def _setup_pip_install_editable(
    workspace: WorkspaceLayout,
    subprocess_runner: Callable[..., subprocess.CompletedProcess],
) -> int:
    """Run ``pip install -e <workspace.root>`` when a pyproject.toml is present.

    Installs ``.[dev]`` when the workspace pyproject declares a ``dev``
    extra so ``lint`` / ``test`` have ruff / chumicro-checks / pytest;
    falls back to the bare ``.`` install when no ``dev`` extra is
    declared, so runtime-only workspaces keep working.

    Returns the subprocess return code (``0`` on success, nonzero from pip on
    failure).  Returns ``0`` and prints a skip note when no pyproject.toml is
    present.  A workspace without one is a runtime-only layout that doesn't
    declare its own deps.
    """
    pyproject = workspace.root / "pyproject.toml"
    if not pyproject.is_file():
        print(
            f"setup: no pyproject.toml at {workspace.root}; "
            "skipping editable install.",
        )
        return 0
    if _pyproject_declares_dev_extra(pyproject):
        install_target = f"{workspace.root}[dev]"
        print(f"setup: installing {workspace.root} (editable, [dev] extra)")
    else:
        install_target = str(workspace.root)
        print(f"setup: installing {workspace.root} (editable)")
    completed = subprocess_runner(  # noqa: S603 - args fully controlled
        [sys.executable, "-m", "pip", "install", "-e", install_target],
        check=False,
    )
    return completed.returncode


def _setup_materialize_templates(workspace: WorkspaceLayout) -> None:
    """Land the first-write text for the three workspace-root files.

    ``workspace.yml`` / ``secrets.toml`` / ``devices.yml``: only files
    that don't already exist are touched.  Print one line per materialized
    file so the user sees what landed.
    """
    template_report = materialize_workspace_templates(workspace.root)
    materialized_count = template_report.count(ApplyAction.MATERIALIZED)
    if materialized_count:
        print(f"setup: materialized {materialized_count} workspace template(s)")
        for path, action in template_report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  {path}")


def _setup_sync_chumicro_dev(workspace: WorkspaceLayout) -> None:
    """When ``chumicro-dev.toml`` points at a sibling chumicro checkout,
    refresh ``workspace.yml``'s ``library_sources:`` block to match the
    checkout's ``libraries/<name>/`` set.

    No-op when ``chumicro-dev.toml`` is absent (regular mode), the
    declared path doesn't exist (warn), or the path exists but has no
    libraries (warn).  Otherwise rewrites the managed block in place.
    """
    chumicro_path = read_chumicro_dev_path(workspace.root)
    if chumicro_path is None:
        return
    if not chumicro_path.is_dir():
        print(
            f"setup: warning: chumicro-dev.toml points at "
            f"{chumicro_path} which doesn't exist; "
            "skipping library_sources sync.",
            file=sys.stderr,
        )
        return
    libraries = discover_chumicro_libraries(chumicro_path)
    if not libraries:
        print(
            f"setup: warning: no chumicro libraries found at "
            f"{chumicro_path}/libraries/; "
            "skipping library_sources sync.",
            file=sys.stderr,
        )
        return
    changed = sync_library_sources(workspace.workspace_yaml, libraries)
    if changed:
        print(
            f"setup: synced library_sources for {len(libraries)} "
            f"chumicro libraries from {chumicro_path}",
        )
    else:
        print(
            f"setup: library_sources already in sync with {chumicro_path}",
        )


def _setup_additive_reapply(workspace: WorkspaceLayout) -> None:
    """Append upstream-template keys missing from the user's ``workspace.yml``
    / ``secrets.toml``, in place, comments preserved.

    Existing values are NEVER touched; only the missing keys land.  The
    helper prints one line per file that gained keys.
    """
    appended = additive_reapply(workspace.root)
    for filename, paths in appended.items():
        plural = "key" if len(paths) == 1 else "keys"
        joined = ", ".join(paths)
        print(
            f"setup: appended {len(paths)} {plural} to {filename} "
            f"from the upstream template: {joined}",
        )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> int:
    """Install workspace dependencies and materialize workspace templates.

    Runs ``pip install -e .`` (or ``.[dev]`` when the workspace
    pyproject declares a ``dev`` extra) in the workspace root when a
    ``pyproject.toml`` is present, then materializes any missing
    workspace templates (``devices.yml``, ``workspace.yml``,
    ``secrets.toml``) from the content shipped in
    :mod:`chumicro_workspace.templates` (``devices.yml`` ships from
    ``chumicro_deploy`` since it owns the schema).  Re-running is
    safe: only missing template files are materialized, existing
    ones are left alone.

    ``setup`` materializes ``workspace.yml`` on a fresh clone, so it
    cannot rely on :func:`_resolve_workspace`'s walk-up-and-find-marker
    discovery, because the marker isn't there yet.  Resolve the workspace
    root directly from ``--workspace-dir`` or ``cwd``.  Every other
    command keeps using marker-based discovery and works from any
    subdirectory inside an already-set-up workspace.
    """
    starting_dir = (
        args.workspace_dir if args.workspace_dir is not None else Path.cwd()
    ).resolve()
    workspace = WorkspaceLayout(root=starting_dir)

    pip_exit_code = _setup_pip_install_editable(
        workspace, args._env.subprocess_runner,
    )
    if pip_exit_code != 0:
        return pip_exit_code

    _setup_materialize_templates(workspace)
    # chumicro-dev.toml mode: sync workspace.yml's library_sources:
    # block so deploy --import-graph resolves `import chumicro_<name>`
    # against the sibling checkout rather than the empty packages/
    # dir.
    _setup_sync_chumicro_dev(workspace)
    _setup_additive_reapply(workspace)
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Re-flow tool-owned template files from upstream.

    Exit codes: ``0`` on success, ``2`` when the template clone
    fails, ``3`` when any tool-owned file was refused because its
    on-disk content differs from the last-applied template version
    (re-run with ``--force`` to overwrite or delete those files).
    """
    workspace = _resolve_workspace(args)
    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = template_apply.update(
            workspace.root,
            template_url=template_url,
            git_reference=args.git_reference,
            force=args.force,
        )
    except RuntimeError as error:
        print(f"update: {error}", file=sys.stderr)
        return 2
    refreshed = report.count(ApplyAction.REFRESHED)
    unchanged = report.count(ApplyAction.UNCHANGED)
    skipped = report.count(ApplyAction.SKIPPED)
    removed = report.count(ApplyAction.REMOVED)
    refused = report.count(ApplyAction.REFUSED)
    print(
        f"update: refreshed={refreshed} unchanged={unchanged} "
        f"skipped={skipped} removed={removed} refused={refused}",
    )
    for path, action in report:
        print(f"  {action:>11}  {path}")
    for path in report.dependency_preserved_paths:
        print(f"update: preserved your added dependencies in {path}")
    if refused:
        plural = "file" if refused == 1 else "files"
        print(
            f"update: refused {refused} tool-owned {plural} with local "
            "edits (content differs from the last-applied template "
            "version); review the list above, then re-run with --force "
            "to overwrite or delete them.",
            file=sys.stderr,
        )
        return 3
    return 0


def _validate_project_name(name: str) -> None:
    """Reject project names that won't survive ``import projects.<name>.app``.

    Accepts three shapes: bare (``"bedroom_sensor"``), slash-form
    (``"upstairs/bedroom_sensor"``), and dotted
    (``"upstairs.bedroom_sensor"``).  Each path segment is validated
    independently.  The on-device import path is
    ``projects.<seg1>.<seg2>.app`` so every segment must be a valid
    Python identifier (no hyphens, leading digits, leading underscore,
    or Python keywords).

    Leading underscore is reserved at every level for
    workspace-internal directories such as ``_template`` /
    ``_generated``.  The recursive project classifier filters those out,
    so a user-created ``_foo/bar`` segment would be invisible to
    ``projects``/``deploy``.
    """
    if not name:
        raise SystemExit("error: project name must not be empty")
    segments = re.split(r"[/.]", name)
    for segment in segments:
        if not segment:
            raise SystemExit(
                f"error: project name {name!r} has an empty path segment "
                "(check for stray '/' or '.' separators).",
            )
        if not segment.isidentifier():
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "is not a valid Python identifier: project directories "
                "are imported as modules, so each segment must use "
                "snake_case (letters, digits, underscores; no hyphens "
                "or spaces; no leading digit).",
            )
        if segment.startswith("_"):
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "starts with '_'; leading underscore is reserved for "
                "workspace-internal directories (e.g. _template).",
            )
        if keyword.iskeyword(segment):
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "is a Python keyword.",
            )


def _ensure_namespace_parents(
    workspace: WorkspaceLayout, target: Path,
) -> list[Path]:
    """Create empty ``__init__.py``-marked namespace dirs above *target*.

    Returns the list of namespace dirs newly created so the caller can
    print a per-command trace line.  Pre-existing namespace dirs are
    reused silently.  A project moved into ``garage/sensors/`` lands
    with the same host-side namespace marker layout that ``new`` would
    produce.
    """
    workspace.projects_dir.mkdir(parents=True, exist_ok=True)
    parent = target.parent
    if parent == workspace.projects_dir:
        return []
    created: list[Path] = []
    relative_parent = parent.relative_to(workspace.projects_dir)
    for segment_count in range(1, len(relative_parent.parts) + 1):
        namespace_dir = workspace.projects_dir.joinpath(
            *relative_parent.parts[:segment_count],
        )
        init_path = namespace_dir / "__init__.py"
        if not namespace_dir.exists():
            namespace_dir.mkdir(parents=True)
            created.append(namespace_dir)
        if not init_path.exists():
            init_path.write_text("")
    return created


def _resolve_new_source(
    workspace: WorkspaceLayout, from_path: str | None,
) -> Path:
    """Pick the directory ``new`` will copy into the target.

    Without ``--from``, returns ``projects/_template/``.  With
    ``--from <path>``, resolves *path* relative to the workspace
    root and validates that the resulting directory exists and looks
    like a project, i.e. has at least one of
    :data:`~chumicro_workspace.workspace.ENTRY_POINT_FILENAMES`.
    An entry-point is the only way to confirm the source is a project
    (vs. a namespace dir or a docs folder).
    """
    if from_path is None:
        template = workspace.projects_dir / "_template"
        if not template.is_dir():
            raise SystemExit(
                f"error: template {template} not found; run "
                "`python3 run.py update` to re-flow it from the "
                "shipped template, or create `projects/_template/` "
                "by hand.",
            )
        return template
    candidate = (workspace.root / from_path).resolve()
    # Defense against `--from ../../etc/passwd` shenanigans: keep the
    # source under the workspace root.
    try:
        candidate.relative_to(workspace.root.resolve())
    except ValueError as exception:
        raise SystemExit(
            f"error: --from path {from_path!r} resolves outside the "
            f"workspace root {workspace.root}.",
        ) from exception
    if not candidate.is_dir():
        raise SystemExit(
            f"error: --from source {candidate} is not a directory.",
        )
    has_entry_point = any(
        (candidate / filename).is_file()
        for filename in ENTRY_POINT_FILENAMES
    )
    if not has_entry_point:
        raise SystemExit(
            f"error: --from source {candidate} has no entry-point "
            "file (app.py / code.py / main.py); pick a project "
            "directory, not a namespace.",
        )
    return candidate


def _cmd_new(args: argparse.Namespace) -> int:
    """Create a project or library scaffold under the workspace.

    Default mode (no ``--library``): creates ``projects/<path>/`` by
    copying a template or example tree.  *path* may be bare
    (``"bedroom_sensor"``), slash-form (``"upstairs/bedroom_sensor"``),
    or dotted (``"upstairs.bedroom_sensor"``).  Intermediate namespace
    directories are auto-created with empty ``__init__.py`` markers
    so host-side tooling can
    ``import projects.upstairs.bedroom_sensor.app`` without surprises.
    With ``--from <path>`` the source tree is *path* (resolved
    relative to the workspace root and validated as a project) instead
    of ``projects/_template/``.

    Library mode (``--library``): creates a chumicro-style library
    tree under ``libraries/<name>/``, using the same scaffolder
    chumicro libraries themselves use.  ``--into <path>`` overrides the
    parent directory.

    Each path segment is validated against the Python identifier
    grammar (``_validate_project_name``).
    """
    _validate_project_name(args.name)
    workspace = _resolve_workspace(args)

    if args.library or args.workbench:
        if args.from_path is not None:
            print(
                "new: --from / --library / --workbench are mutually "
                "exclusive: package scaffolding uses the built-in "
                "template.",
                file=sys.stderr,
            )
            return 2
        if args.library and args.workbench:
            print(
                "new: --library and --workbench are mutually exclusive: "
                "pick one (libraries/ for cross-runtime device libs; "
                "workbench/ for host-only CPython tools).",
                file=sys.stderr,
            )
            return 2
        package_kind = "workbench" if args.workbench else "library"
        default_parent = (
            workspace.root / "workbench"
            if args.workbench
            else workspace.root / "libraries"
        )
        target_dir = (
            Path(args.into).resolve()
            if args.into is not None
            else default_parent
        )
        try:
            created = scaffold_library(
                target_dir, args.name, package_kind=package_kind,
            )
        except LibraryAlreadyExistsError as exception:
            raise SystemExit(f"error: {exception} already exists") from exception
        print(f"new: created {package_kind} {created}")
        return 0

    source = _resolve_new_source(workspace, args.from_path)
    target = workspace.project_dir(args.name)
    if target.exists():
        raise SystemExit(f"error: {target} already exists")
    created_namespaces = _ensure_namespace_parents(workspace, target)
    for namespace_dir in created_namespaces:
        print(
            f"new: creating namespace "
            f"{namespace_dir.relative_to(workspace.root)}/",
        )
    shutil.copytree(source, target)
    print(f"new: created {target}")
    return 0


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_setup_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``setup`` / ``update`` / ``new`` subparsers.

    Workspace *creation* is intentionally not a CLI command.  Users
    clone the template repo directly (``git clone`` or GitHub "Use
    this template").  ``update`` is the supported way to re-sync an
    existing workspace's tool-owned files with the template.
    """
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install dependencies and materialize template files.",
    )
    _add_workspace_arg(setup_parser)
    setup_parser.set_defaults(func=_cmd_setup)

    update_parser = subparsers.add_parser(
        "update",
        help=(
            "Re-flow tool-owned template files from upstream. "
            "User-owned files are skipped; tool-owned files upstream "
            "no longer ships are deleted."
        ),
    )
    _add_workspace_arg(update_parser)
    update_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the ChuMicro template).",
    )
    update_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to fetch (defaults to the remote's HEAD).",
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite or delete tool-owned files even when their "
            "content differs from the last-applied template version "
            "(without this flag such files are refused and left "
            "untouched)."
        ),
    )
    update_parser.set_defaults(func=_cmd_update)

    new_parser = subparsers.add_parser(
        "new",
        help=(
            "Create projects/<path>/ by copying a template or example tree.  "
            "Path may be nested (slash- or dotted-form)."
        ),
    )
    _add_workspace_arg(new_parser)
    new_parser.add_argument(
        "name",
        help=(
            "Name of the new project (becomes projects/<path>/).  Accepts "
            "bare ('bedroom_sensor'), slash ('upstairs/bedroom_sensor'), "
            "or dotted ('upstairs.bedroom_sensor') forms.  Intermediate "
            "namespace directories are auto-created."
        ),
    )
    new_parser.add_argument(
        "--from",
        dest="from_path",
        default=None,
        help=(
            "Copy from this directory (relative to the workspace root) "
            "instead of projects/_template/.  Source must contain an "
            "app.py / code.py / main.py entry-point.  Useful for "
            "`new garage/heater --from examples/two_board_handshake/server`."
        ),
    )
    new_parser.add_argument(
        "--library",
        action="store_true",
        help=(
            "Scaffold a chumicro-style library under "
            "<workspace>/libraries/<name>/.  Mutually exclusive with "
            "--from / --workbench; uses the built-in scaffolder."
        ),
    )
    new_parser.add_argument(
        "--workbench",
        action="store_true",
        help=(
            "Scaffold a host-only workbench tool under "
            "<workspace>/workbench/<name>/.  Same scaffolder as "
            "--library, but uses a workbench-flavored pyproject "
            "template (CLI entry point, no cross-runtime concerns; "
            "free to depend on CPython-only third-party libs).  "
            "Mutually exclusive with --library / --from."
        ),
    )
    new_parser.add_argument(
        "--into",
        type=Path,
        default=None,
        help=(
            "Library scaffolder only: override the parent directory "
            "for the new library tree (default <workspace>/libraries/)."
        ),
    )
    new_parser.set_defaults(func=_cmd_new)
