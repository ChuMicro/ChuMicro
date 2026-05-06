"""``chumicro-workspace`` command dispatch.

Thin wrapper over the public ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` APIs.  Workspace template
repos vendor a tiny ``run.py`` shim that simply calls
:func:`main`; every command the workspace user invokes
(``python run.py deploy back-porch``, ``python run.py repl``, etc.)
routes through this dispatcher.

Commands are shipped at three depths:

* **Implemented** — full behaviour wired to the underlying library
  (``deploy``, ``probe``, ``devices``, ``repl``, ``new``,
  ``install-firmware`` / ``upgrade-firmware``, ``discover``,
  ``test``, ``setup``).
* **Stubbed for a planned slice** — registered with help text and a
  clear "implemented in Slice X" error so the dispatcher contract is
  stable before the implementation lands (``add-device``, ``rename``,
  ``sim``, ``env``, ``use``, ``sync``, ``upgrade``).

Stubs raise :exc:`NotImplementedError` carrying a one-line pointer to
the slice or workstream phase that will land them.  CLI invocation
catches the exception and exits 2 with a descriptive message — the
test suite asserts on that exit code so the rollout sequence stays
visible.
"""

from __future__ import annotations

import argparse
import keyword
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chumicro_deploy.config.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    list_device_ids,
    load_devices,
    rename_device,
    update_device_address,
    update_device_firmware_version,
    update_device_hardware,
)
from chumicro_deploy.firmware_url import (
    UnresolvedFirmwareError,
    derive_firmware_url,
)

from chumicro_workspace.boot_shim import (
    project_app_exports_run,
    project_boot_source,
    project_boot_with_import_graph_source,
)
from chumicro_workspace.deploy_source import project_directory_source
from chumicro_workspace.deploy_targets import read_deploy_targets
from chumicro_workspace.firmware_support import (
    FirmwareSupportStatus,
    check_firmware_supported,
)
from chumicro_workspace.firmware_support import (
    explain as explain_firmware_support,
)
from chumicro_workspace.health import (
    HealthFinding,
    HealthLevel,
    collect_doctor_findings,
    collect_health_findings,
)
from chumicro_workspace.import_graph import project_import_graph_source
from chumicro_workspace.onboarding import (
    BoardState,
    detect_board_state,
    probe_with_runtime_inference,
)
from chumicro_workspace.quality import load_quality_config
from chumicro_workspace.recovery import detect_hints, format_hints
from chumicro_workspace.workspace import (
    ENTRY_POINT_FILENAMES,
    ProjectClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import Device, DeviceImplementation


# ---------------------------------------------------------------------------
# Common argparse helpers
# ---------------------------------------------------------------------------


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--workspace-dir`` flag.

    Defaults to walking up from the current working directory until a
    ``workspace.yml`` is found (mirrors ``git`` discovery).  Override
    when running multiple workspaces in parallel or when the user
    invokes the CLI from outside the tree (CI runners, IDE tasks).
    """
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help=(
            "Workspace root.  Defaults to walking up from the current "
            "directory until a workspace.yml is found."
        ),
    )


def _add_device_selector(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--device`` / ``--runtime`` selectors.

    Resolved against ``<workspace>/devices.yml`` via
    :mod:`chumicro_deploy.config.default`.  Mutually-exclusive at
    runtime (the loader raises if both are passed alongside two
    runtime defaults).
    """
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help="Pick a specific entry from devices.yml by id.",
    )
    parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help="Pick the default device for the named runtime.",
    )


def _resolve_workspace(args: argparse.Namespace) -> WorkspaceLayout:
    """Locate the workspace root for *args*.

    Wraps :class:`WorkspaceLayout.from_dir` so missing workspaces
    surface as a uniform ``SystemExit`` with a helpful message
    instead of a stack trace.
    """
    try:
        return WorkspaceLayout.from_dir(args.workspace_dir)
    except WorkspaceNotFoundError as exception:
        raise SystemExit(f"error: {exception}") from exception


def _find_devices_yml_entry_for_args(
    workspace: WorkspaceLayout,
    args: argparse.Namespace,
) -> Mapping[str, Any] | None:
    """Locate the raw ``devices.yml`` entry matching *args*' selectors.

    Mirrors :func:`chumicro_deploy.config.default.load_devices_yml`'s
    resolution order — explicit ``--device id`` wins outright, then
    ``--runtime`` picks ``defaults.<runtime>``, finally a single
    runtime default in the file picks itself.  Returns the matching
    raw dict (with comments + key order intact since it comes from
    :func:`load_devices`) or ``None`` when nothing matches.

    Distinct from :func:`_resolve_device` because the
    ``firmware_source`` / ``hardware`` fields aren't on the
    :class:`Device` dataclass — they live in the raw entry.
    """
    if not workspace.devices_yaml.is_file():
        return None
    data = load_devices(workspace.devices_yaml)
    if args.device_id is not None:
        return find_device(data, args.device_id)
    defaults = data.get("defaults") or {}
    runtime = getattr(args, "runtime", None)
    if runtime is not None:
        default_id = defaults.get(runtime)
        if default_id is not None:
            return find_device(data, default_id)
    candidates = [
        defaults.get("micropython"),
        defaults.get("circuitpython"),
    ]
    picks = [candidate for candidate in candidates if candidate]
    if len(picks) == 1:
        return find_device(data, picks[0])
    return None


def _resolve_device(workspace: WorkspaceLayout, args: argparse.Namespace) -> Device:
    """Construct a :class:`Device` for the selected entry in devices.yml."""
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found — run "
            "'add-device' to register a board first.",
        )
    from chumicro_deploy.config.default import load_devices_yml  # noqa: PLC0415

    return load_devices_yml(
        workspace.devices_yaml,
        device_id=args.device_id,
        runtime=args.runtime,
    )


def _resolve_all_devices(workspace: WorkspaceLayout) -> list[Device]:
    """Return a :class:`Device` for every entry in devices.yml.

    Used by ``deploy --all-devices`` (Phase 2f).  Loads each entry
    via :func:`load_devices_yml` so the per-entry validation +
    runtime-default resolution stays consistent with single-device
    deploys.  Order matches the YAML file order so deploys reach
    boards in a predictable sequence.
    """
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found — run "
            "'add-device' to register a board first.",
        )
    from chumicro_deploy.config.default import load_devices_yml  # noqa: PLC0415

    raw = load_devices(workspace.devices_yaml)
    entries = raw.get("devices", []) or []
    if not entries:
        raise SystemExit(
            f"error: {workspace.devices_yaml} has no devices to deploy to.",
        )
    return [
        load_devices_yml(workspace.devices_yaml, device_id=entry["id"])
        for entry in entries
    ]


# ---------------------------------------------------------------------------
# Implemented commands
# ---------------------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> int:
    """Install workspace dependencies and materialize template files.

    Runs ``pip install -e .`` in the workspace root when a
    ``pyproject.toml`` is present, then walks ``_workspace_template/``
    and creates any missing files at the workspace root.  Idempotent —
    re-running is safe.

    Setup is the one command that *materialises* ``workspace.yml`` —
    it cannot use :func:`_resolve_workspace`'s walk-up-and-find-marker
    discovery, because on a fresh clone the marker doesn't exist yet.
    Resolve the workspace root directly from ``--workspace-dir`` or
    ``cwd``; every other command continues to use the marker-based
    discovery so they keep working from any subdirectory inside an
    already-set-up workspace.
    """
    starting_dir = (
        args.workspace_dir if args.workspace_dir is not None else Path.cwd()
    ).resolve()
    workspace = WorkspaceLayout(root=starting_dir)
    pyproject = workspace.root / "pyproject.toml"
    if pyproject.is_file():
        print(f"setup: installing {workspace.root} (editable)")
        completed = subprocess.run(  # noqa: S603 — args fully controlled
            [sys.executable, "-m", "pip", "install", "-e", str(workspace.root)],
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    else:
        print(
            f"setup: no pyproject.toml at {workspace.root} — "
            "skipping editable install.",
        )
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        ApplyAction,
        materialize_templates,
        materialize_workbench_starters,
    )

    # `_workspace_template/` first — repo-specific starter files
    # (project templates, examples, README placeholders, custom
    # devices.yml or workspace.yml shapes for forks of the
    # canonical template).  When a fork ships its own
    # `_workspace_template/devices.yml`, the customised version wins.
    report = materialize_templates(workspace.root)
    new_files = report.count(ApplyAction.MATERIALIZED)
    if new_files:
        print(f"setup: materialized {new_files} file(s) from _workspace_template/")
        for path, action in report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  {path}")

    # Workbench-owned starters as the fallback — fills in
    # `devices.yml` / `workspace.yml` only when the
    # `_workspace_template/` walker didn't.  Canonical content lives
    # in the workbench package's `_payloads/` so the same bytes ship
    # to every workspace-template-derived workspace.
    workbench_report = materialize_workbench_starters(workspace.root)
    workbench_new = workbench_report.count(ApplyAction.MATERIALIZED)
    if workbench_new:
        print(f"setup: materialized {workbench_new} workbench-owned starter(s)")
        for path, action in workbench_report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  {path}")

    # Gap 3(a): when chumicro-dev.toml points at a sibling chumicro
    # checkout, sync workspace.yml's ``library_sources:`` block so
    # ``deploy --import-graph`` (and the ``--boot-shim --import-graph``
    # composition, gap 5) resolve ``import chumicro_<name>`` against
    # the local checkout instead of the empty ``packages/`` dir.
    from chumicro_workspace.chumicro_dev import (  # noqa: PLC0415
        discover_chumicro_libraries,
        read_chumicro_dev_path,
        sync_library_sources,
    )

    chumicro_path = read_chumicro_dev_path(workspace.root)
    if chumicro_path is not None:
        if not chumicro_path.is_dir():
            print(
                f"setup: warning — chumicro-dev.toml points at "
                f"{chumicro_path} which doesn't exist; "
                "skipping library_sources sync.",
                file=sys.stderr,
            )
        else:
            libraries = discover_chumicro_libraries(chumicro_path)
            if not libraries:
                print(
                    f"setup: warning — no chumicro libraries found at "
                    f"{chumicro_path}/libraries/; "
                    "skipping library_sources sync.",
                    file=sys.stderr,
                )
            else:
                changed = sync_library_sources(
                    workspace.workspace_yaml, libraries,
                )
                if changed:
                    print(
                        f"setup: synced library_sources for "
                        f"{len(libraries)} chumicro libraries from "
                        f"{chumicro_path}",
                    )
                else:
                    print(
                        "setup: library_sources already in sync with "
                        f"{chumicro_path}",
                    )

    # Schema-drift surface: print fields the upstream starter has
    # gained since the user materialised their workspace.yml.  No
    # auto-application — the user decides whether to copy the new
    # fields in.  Empty (no-op) when the user's file already covers
    # the starter's schema.
    from chumicro_workspace.starter_drift import (  # noqa: PLC0415
        print_starter_drift_report,
    )

    print_starter_drift_report(workspace.root)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Clone the workspace template into a target directory."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
        init,
    )

    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = init(
            args.target,
            template_url=template_url,
            git_reference=args.git_reference,
            force=args.force,
        )
    except FileExistsError as error:
        print(f"init: {error}", file=sys.stderr)
        print(
            "Pass --force to clear the target directory and reclone.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as error:
        print(f"init: {error}", file=sys.stderr)
        return 2
    written = report.count(ApplyAction.WRITTEN)
    print(f"init: cloned {template_url} into {args.target} ({written} files)")
    print(f"next: cd {args.target} && python3 run.py setup")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Re-flow tool-owned template files from the canonical upstream."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
    )
    from chumicro_workspace.template_apply import (
        update as apply_update,
    )

    workspace = _resolve_workspace(args)
    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = apply_update(
            workspace.root,
            template_url=template_url,
            git_reference=args.git_reference,
        )
    except RuntimeError as error:
        print(f"update: {error}", file=sys.stderr)
        return 2
    refreshed = report.count(ApplyAction.REFRESHED)
    unchanged = report.count(ApplyAction.UNCHANGED)
    skipped = report.count(ApplyAction.SKIPPED)
    print(
        f"update: refreshed={refreshed} unchanged={unchanged} skipped={skipped}",
    )
    for path, action in report:
        print(f"  {action:>11}  {path}")
    return 0


def _validate_project_name(name: str) -> None:
    """Reject project names that won't survive ``import projects.<name>.app``.

    Accepts three shapes: bare (``"bedroom_sensor"``), slash-form
    (``"upstairs/bedroom_sensor"``), and dotted
    (``"upstairs.bedroom_sensor"``).  Each path segment is validated
    independently — the on-device import path is
    ``projects.<seg1>.<seg2>.app`` so every segment must be a valid
    Python identifier (no hyphens, leading digits, leading underscore,
    or Python keywords).

    Leading underscore is reserved at every level for
    workspace-internal directories such as ``_template`` /
    ``_generated``; the recursive project classifier filters those out,
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
                "— check for stray '/' or '.' separators.",
            )
        if not segment.isidentifier():
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "is not a valid Python identifier — project directories "
                "are imported as modules, so each segment must use "
                "snake_case (letters, digits, underscores; no hyphens "
                "or spaces; no leading digit).",
            )
        if segment.startswith("_"):
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "starts with '_' — leading underscore is reserved for "
                "workspace-internal directories (e.g. _template).",
            )
        if keyword.iskeyword(segment):
            raise SystemExit(
                f"error: project name segment {segment!r} (in {name!r}) "
                "is a Python keyword.",
            )


# Project-entrypoint filenames are defined once in
# :data:`chumicro_workspace.workspace.ENTRY_POINT_FILENAMES` — single
# source of truth for "what files mark a project dir."  Imported above
# alongside the other workspace.py exports.


def _ensure_namespace_parents(
    workspace: WorkspaceLayout, target: Path,
) -> list[Path]:
    """Create empty ``__init__.py``-marked namespace dirs above *target*.

    Returns the list of namespace dirs newly created so the caller can
    print a per-command trace line.  Pre-existing namespace dirs are
    reused silently.  Used by both ``new`` and ``rename`` so a project
    moved into ``garage/sensors/`` lands with the same host-side
    namespace marker layout ``new`` would produce.
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

    Without ``--from``, returns ``projects/_template/`` (same default as
    before Slice 3 added the flag).  With ``--from <path>``, resolves
    *path* relative to the workspace root and validates that the
    resulting directory exists and looks like a project — i.e. has at
    least one of :data:`~chumicro_workspace.workspace.ENTRY_POINT_FILENAMES`.
    An entry-point is the only way to confirm the source is a project
    (vs. a namespace dir or a docs folder).
    """
    if from_path is None:
        template = workspace.projects_dir / "_template"
        if not template.is_dir():
            raise SystemExit(
                f"error: template {template} not found — run "
                "`chumicro-workspace init` to clone the canonical "
                "template, or create `projects/_template/` by hand.",
            )
        return template
    candidate = (workspace.root / from_path).resolve()
    # Defence against `--from ../../etc/passwd` shenanigans — keep the
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
            "file (app.py / code.py / main.py) — pick a project "
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
    tree under ``libraries/<name>/`` — same scaffolder chumicro
    libraries themselves use.  ``--into <path>`` overrides the
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
                "exclusive — package scaffolding uses the built-in "
                "template.",
                file=sys.stderr,
            )
            return 2
        if args.library and args.workbench:
            print(
                "new: --library and --workbench are mutually exclusive — "
                "pick one (libraries/ for cross-runtime device libs; "
                "workbench/ for host-only CPython tools).",
                file=sys.stderr,
            )
            return 2
        from chumicro_workspace.scaffold import (  # noqa: PLC0415
            LibraryAlreadyExistsError,
            scaffold_library,
        )
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


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a board's runtime identity (delegates to chumicro-deploy)."""
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import probe_device  # noqa: PLC0415

    info = probe_device(device)
    if info.implementation is None:
        print("probe: no implementation marker", file=sys.stderr)
        return 1
    print(f"runtime: {info.implementation.name}")
    print(f"version: {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
    if info.uid:
        print(f"uid: {info.uid}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    """List serial ports the host can see (pyserial-backed)."""
    # pyserial ships as a chumicro-deploy dep so it's always present.
    from serial.tools import list_ports  # noqa: PLC0415

    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print("discover: no serial ports detected")
        return 0
    for port in ports:
        description = port.description or "(no description)"
        print(f"{port.device}\t{description}")
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    """Print the entries in ``devices.yml`` (one per line)."""
    workspace = _resolve_workspace(args)
    if not workspace.devices_yaml.is_file():
        print(f"devices: {workspace.devices_yaml} does not exist yet")
        return 0
    from ruamel.yaml import YAML  # noqa: PLC0415

    raw = YAML(typ="safe").load(workspace.devices_yaml.read_text()) or {}
    devices = raw.get("devices", [])
    if not devices:
        print("devices: no entries")
        return 0
    for entry in devices:
        identifier = entry.get("id", "?")
        runtime = entry.get("runtime", "?")
        address = entry.get("address", "?")
        print(f"{identifier}\t{runtime}\t{address}")
    return 0


def _make_deploy_runner(device: Any, *, non_interactive: bool) -> Any:
    """Construct the deploy runner for a CLI command.

    Wraps a fresh :class:`chumicro_deploy.Deployer` in
    :class:`chumicro_deploy.InteractiveDeployer` by default so transport
    failures (port busy, drive missing, FSKit wedge) get classified and
    coached.  ``--non-interactive`` opts out for CI / scripted flows
    where the retry prompt has no stdin to answer.

    Returns the runner; caller invokes ``.deploy()`` or
    ``.deploy_diff()`` as needed (both signatures are mirrored on the
    interactive wrapper).
    """
    from chumicro_deploy import Deployer, InteractiveDeployer  # noqa: PLC0415

    deployer = Deployer(device)
    if non_interactive:
        return deployer
    return InteractiveDeployer(deployer)


def _emit_failure_hints(deploy_result: Any) -> None:
    """Print the traceback + matching app-level recovery hints to stderr.

    The deploy result's ``traceback`` and ``execute_output`` are
    both scanned for known patterns (Phase 2d's hint table); any
    matching hints append below the traceback under a "--- hints ---"
    section so users who hit a common failure (missing config key,
    library not installed) get the workspace-shaped pointer instead
    of just the raw stdlib error.

    Skip the hints section silently when no pattern matches —
    showing an empty block reads worse than showing nothing.
    """
    traceback_text = getattr(deploy_result, "traceback", "") or ""
    execute_output = getattr(deploy_result, "execute_output", "") or ""
    if traceback_text:
        print(
            f"\n--- traceback ---\n{traceback_text}",
            file=sys.stderr,
        )
    haystack = traceback_text + "\n" + execute_output
    hints = detect_hints(haystack)
    block = format_hints(hints)
    if block:
        print(f"\n{block}", file=sys.stderr)


def _format_size(num_bytes: int) -> str:
    """Render *num_bytes* as a short human-readable string.

    ``B`` for under 1 KiB, ``KiB`` (one decimal) for under 1 MiB,
    ``MiB`` past that.  Used in ``deploy --dry-run`` columns where
    fixed-width "look at a glance" output beats raw byte counts.
    """
    kib = 1024
    mib = 1024 * 1024
    if num_bytes < kib:
        return f"{num_bytes} B"
    if num_bytes < mib:
        return f"{num_bytes / kib:.1f} KiB"
    return f"{num_bytes / mib:.1f} MiB"


def _classify_dry_run_path(path: str, content: bytes) -> str:  # noqa: ARG001
    """Return a one-word category for *path* in the deploy file map.

    Drives the right-column annotation of ``deploy --dry-run`` so
    the reader can scan "what's shim infrastructure vs my code"
    without parsing paths by eye.

    The classifier still returns ``shim`` for ``/code.py`` and
    ``/main.py`` even when those are user-owned in plain mode —
    they're always the firmware entrypoint, regardless of who
    authored them.
    """
    if path in ("/code.py", "/main.py"):
        return "shim"
    if path == "/runtime_config.msgpack":
        return "config"
    if path.startswith("/lib/"):
        return "library"
    return "file"


def _render_dry_run_summary(
    *,
    project_name: str,
    device: Device,
    layout: str,
    files: dict[str, bytes],
    entrypoint: str,
    wipe: bool = False,
) -> str:
    """Format the ``deploy --dry-run`` output.

    Two sections: a one-line header naming the project / device /
    layout, and a sorted file list with size + classification.
    The output doubles as user-facing documentation for
    "what does deploy actually do" — link from docs/guide.md +
    workspace template README.

    When *wipe* is ``True``, an additional ``would wipe filesystem``
    line surfaces between the header and the file table so dry-run
    output matches the destructive variant of the real deploy.
    """
    total_bytes = sum(len(content) for content in files.values())
    lines = [
        f"would deploy {project_name} to {device.transport}@{device.address} "
        f"using {layout} layout",
        f"entrypoint: {entrypoint}",
    ]
    if wipe:
        lines.append("would wipe filesystem before deploy")
    lines.append(
        f"device files ({len(files)} total, {_format_size(total_bytes)}):",
    )
    if not files:
        lines.append("  (file map is empty)")
        return "\n".join(lines)
    sorted_paths = sorted(files)
    path_width = max(len(path) for path in sorted_paths)
    size_width = max(
        len(_format_size(len(files[path]))) for path in sorted_paths
    )
    for path in sorted_paths:
        content = files[path]
        size = _format_size(len(content)).rjust(size_width)
        category = _classify_dry_run_path(path, content)
        lines.append(f"  {path.ljust(path_width)}  {size}  {category}")
    return "\n".join(lines)


def _resolve_project_name(workspace: WorkspaceLayout, name: str) -> str:
    """Resolve a user-typed project name to a canonical slash-form path.

    Accepts three shapes:

    * **Bare** (``"door_open"``) — looked up across the whole
      ``projects/`` tree.  Unique match → that project.  Multiple matches →
      ``SystemExit`` listing the candidates.  No match → caller's
      existence check surfaces the ``FileNotFoundError``-shaped
      message.
    * **Slash** (``"garage/sensors/door_open"``) — direct path.
    * **Dotted** (``"garage.sensors.door_open"``) — same as slash;
      normalised before return because ``/`` is the canonical form
      used by :meth:`WorkspaceLayout.list_projects`.

    Slice 2 of the nested-projects-and-examples plan; replaces the
    flat-only ``names = list(args.names)`` lookup that preceded it.
    """
    normalised = name.replace(".", "/")
    if "/" in normalised:
        return normalised
    candidates = [
        path for path in workspace.list_projects()
        if path == name or path.endswith("/" + name)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        candidate_list = "\n".join(f"  {path}" for path in candidates)
        raise SystemExit(
            f"deploy: {name!r} is ambiguous — multiple projects match:\n"
            f"{candidate_list}\n"
            f"specify the path: `python run.py deploy {candidates[0]}`",
        )
    # No match — let the caller's existence check produce the standard
    # "project not found" message after constructing the dir path.
    return name


def _suggest_add_device_id(
    *,
    implementation: "DeviceImplementation",
    existing_ids: set[str],
) -> str:
    """Default ``add-device`` id when the user omits the positional.

    Composes :func:`_suggest_device_id` (the machine-string slug used
    by the bootstrap wizard) with a runtime suffix and collision
    resolution against the workspace's existing ``devices.yml``:

    * ``"Raspberry Pi Pico W with rp2040"`` + circuitpython
      → ``"raspberry-pi-pico-w-cp"``
    * ``"S2Mini with ESP32S2-S2FN4R2"`` + circuitpython
      → ``"s2mini-cp"``
    * ``"LOLIN_S2_MINI with ESP32-S2FN4R2"`` + micropython
      → ``"lolin-s2-mini-mp"``
    * Empty machine string + circuitpython → ``"circuitpython-cp"``
      (fallback shape from the underlying slug helper; rare —
      indicates a probe that returned no machine identifier).

    When the resulting id collides with *existing_ids*, append a
    numeric suffix: ``"-2"``, ``"-3"``, etc.  The user can rename the
    entry afterwards with ``rename --device <old> <new>``.

    F4 of the 2026-05-06 verification pass — beginners running
    ``add-device`` without a positional id had to invent one cold,
    even though the probe already knows what board this is.

    Args:
        implementation: Probe's :class:`DeviceImplementation` (carries
            the ``machine`` string + runtime ``name``).
        existing_ids: All ids already in ``devices.yml`` — for
            collision resolution.
    """
    base_slug = _suggest_device_id(implementation)
    runtime_suffix_map = {"circuitpython": "cp", "micropython": "mp"}
    suffix = runtime_suffix_map.get(
        implementation.name, implementation.name.lower(),
    )
    base_id = f"{base_slug}-{suffix}"

    if base_id not in existing_ids:
        return base_id
    counter = 2
    while f"{base_id}-{counter}" in existing_ids:
        counter += 1
    return f"{base_id}-{counter}"


def _auto_detect_deploy_mode(
    *,
    project_dir: Path,
    target_entrypoint: str,
    user_passed_boot_shim: bool,
    user_passed_import_graph: bool,
) -> str:
    """Pick the right deploy layout when the user passes no layout flags.

    Returns one of:

    * ``"shim"`` — project ships ``app.py`` with ``run()`` and no
      runtime-specific entrypoint; deploy synthesises ``/code.py``
      or ``/main.py`` and routes through boot-shim + import-graph.
    * ``"plain"`` — project ships the runtime-matching entrypoint
      (``code.py`` for CP, ``main.py`` for MP); ship as-is, no shim.
    * ``"_user_error"`` — project shape doesn't match the target
      runtime (e.g., ``code.py`` only but target is MP, or no
      entrypoint at all).  An actionable message has already been
      printed; the caller treats this as exit code 2.
    * ``"flag_set"`` — the user explicitly passed ``--boot-shim``
      or ``--import-graph``; auto-detect is a no-op.

    Decision matrix (verification finding #5, 2026-05-06):

        code.py     main.py     app.py:run()   target   →  result
        ----------  ----------  -------------  -------     ----------
        Yes         *           *              CP          plain
        *           Yes         *              MP          plain
        Yes         No          *              MP          USER ERROR
        No          Yes         *              CP          USER ERROR
        No          No          Yes            any         shim
        No          No          No             any         USER ERROR
    """
    if user_passed_boot_shim or user_passed_import_graph:
        return "flag_set"

    has_code_py = (project_dir / "code.py").is_file()
    has_main_py = (project_dir / "main.py").is_file()
    has_app_run = project_app_exports_run(project_dir)

    target_is_cp = target_entrypoint == "code.py"
    target_is_mp = target_entrypoint == "main.py"

    # Plain deploy when the runtime-matching entrypoint is present.
    if target_is_cp and has_code_py:
        return "plain"
    if target_is_mp and has_main_py:
        return "plain"

    # Wrong-runtime entrypoint present: user intended this project for
    # the *other* runtime and targeted the wrong board.  Surface as a
    # clear error rather than silently shimming around it.
    if target_is_mp and has_code_py and not has_main_py:
        print(
            f"deploy: project {project_dir.name!r} has code.py "
            "(CircuitPython entrypoint) but you targeted a MicroPython "
            "board.\n"
            "  Fix: rename code.py → main.py for MicroPython, or "
            "deploy --runtime circuitpython.",
            file=sys.stderr,
        )
        return "_user_error"
    if target_is_cp and has_main_py and not has_code_py:
        print(
            f"deploy: project {project_dir.name!r} has main.py "
            "(MicroPython entrypoint) but you targeted a CircuitPython "
            "board.\n"
            "  Fix: rename main.py → code.py for CircuitPython, or "
            "deploy --runtime micropython.",
            file=sys.stderr,
        )
        return "_user_error"

    # No runtime-specific entrypoint — try shim mode.
    if has_app_run:
        return "shim"

    # Nothing to dispatch on.
    app_py_present = (project_dir / "app.py").is_file()
    app_clause = (
        "app.py present but has no top-level run() callable"
        if app_py_present
        else "no app.py with run() callable"
    )
    print(
        f"deploy: project {project_dir.name!r} has no entrypoint "
        "chumicro-deploy can use:\n"
        "  - no code.py at the project root (CircuitPython entrypoint)\n"
        "  - no main.py at the project root (MicroPython entrypoint)\n"
        f"  - {app_clause} (boot-shim mode requires app.py to "
        "export run())\n"
        "\n"
        "  Fix: name your script code.py (CP) or main.py (MP), OR\n"
        "       wrap your top-level code in `def run(): ...` in app.py.",
        file=sys.stderr,
    )
    return "_user_error"


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Deploy a project to a device.

    Single-project default uses :func:`project_directory_source` — the
    flat layout where the project's files land at the device root.
    ``--import-graph`` ships only transitively-imported modules.
    ``--boot-shim`` ships project files at the device root plus a
    synthesised ``/code.py`` (CP) or ``/main.py`` (MP) that imports
    the project's ``app.run``.  Auto-detected when the project ships
    ``app.py`` + ``run()`` and no runtime-specific entrypoint.

    Positional name accepts bare (``"door_open"``), slash
    (``"garage/sensors/door_open"``), or dotted forms; bare names that
    match more than one project in the tree exit 2 with a list of
    candidates.

    When invoked with no positional name and the workspace contains
    exactly one project, that project is deployed by default — covers
    the "I only have one app" beginner case.  Zero projects or
    multiple projects both require an explicit positional.

    Multi-project deploys (``deploy <a> <b> <c>``) are not supported —
    Slice 7 of the nested-projects-and-examples workstream retired the
    multi-project-staging path; pass one positional per ``deploy`` call.
    """
    workspace = _resolve_workspace(args)

    # Pre-deploy fast health gate.  Catches the user-visible failure
    # modes that *would* deploy but ship junk to the device — missing
    # workspace.yml, malformed devices.yml, etc.  Skips the slower
    # per-project AST checks that ``doctor`` runs (those add latency
    # to every deploy).
    # ``--skip-health-check`` opts out for power-users + CI.
    if not args.skip_health_check:
        gate_findings = collect_health_findings(workspace)
        gate_blockers = [
            finding for finding in gate_findings
            if finding.level is HealthLevel.ERROR
        ]
        gate_warnings = [
            finding for finding in gate_findings
            if finding.level is HealthLevel.WARN
        ]
        for finding in gate_warnings:
            print(
                f"deploy: WARN {finding.label}: {finding.message}",
                file=sys.stderr,
            )
            if finding.hint:
                print(f"  hint: {finding.hint}", file=sys.stderr)
        if gate_blockers:
            for finding in gate_blockers:
                print(
                    f"deploy: ERROR {finding.label}: {finding.message}",
                    file=sys.stderr,
                )
                if finding.hint:
                    print(f"  hint: {finding.hint}", file=sys.stderr)
            print(
                "deploy: aborting before sending bytes to the device "
                "(pass --skip-health-check to override).",
                file=sys.stderr,
            )
            return 2

    plan_or_exit = _build_deploy_plan(workspace, args)
    if isinstance(plan_or_exit, int):
        return plan_or_exit
    deploy_plan = plan_or_exit

    exit_code = 0
    for project_name, project_dir, devices in deploy_plan:
        if len(deploy_plan) > 1:
            print(f"\ndeploy: === {project_name} ===")
        for device in devices:
            if len(devices) > 1 or len(deploy_plan) > 1:
                print(
                    f"deploy: --- {device.transport}@{device.address} ---",
                )
            # Every staging path filters out files marked
            # ``__chumicro_runtimes__`` for a different runtime.
            # ``--target-runtime`` overrides; otherwise the device's
            # configured runtime drives the filter.
            target_runtime = args.target_runtime or str(device.transport)
            # Auto-detect deploy layout when the user passed no
            # layout flags.  Project shape determines the mode:
            #
            # * ``code.py`` at root    → plain (CP entrypoint, user-owned).
            # * ``main.py`` at root    → plain (MP entrypoint, user-owned).
            # * ``app.py`` with run()  → boot-shim + import-graph (deploy
            #   synthesises ``/code.py`` or ``/main.py`` and ships imported
            #   libraries from ``library_sources`` and ``shared/``).
            # * Runtime mismatch (e.g. ``code.py`` only, but target is MP)
            #   surfaces as a user error before any bytes leave the host.
            #
            # See finding #5 of the 2026-05-06 verification pass.
            auto_detected_mode = _auto_detect_deploy_mode(
                project_dir=project_dir,
                target_entrypoint=device.effective_entrypoint,
                user_passed_boot_shim=args.boot_shim,
                user_passed_import_graph=args.import_graph,
            )
            if auto_detected_mode == "_user_error":
                # Detector already printed the actionable message.
                exit_code = 2
                continue
            if auto_detected_mode == "shim":
                args.boot_shim = True
                args.import_graph = True

            if args.boot_shim and args.import_graph:
                layout = "boot-shim+import-graph"
                source = project_boot_with_import_graph_source(
                    project_dir,
                    workspace=workspace,
                    entrypoint_filename=device.effective_entrypoint,
                    target_runtime=target_runtime,
                )
            elif args.boot_shim:
                layout = "boot-shim"
                source = project_boot_source(
                    project_dir,
                    workspace=workspace,
                    entrypoint_filename=device.effective_entrypoint,
                    target_runtime=target_runtime,
                )
            elif args.import_graph:
                layout = "import-graph"
                device_entrypoint = (
                    args.entrypoint or f"/{device.effective_entrypoint}"
                )
                source = project_import_graph_source(
                    project_dir,
                    workspace=workspace,
                    entrypoint_filename=device.effective_entrypoint,
                    device_entrypoint=device_entrypoint,
                    target_runtime=target_runtime,
                )
            else:
                layout = "flat"
                source = project_directory_source(
                    project_dir,
                    workspace_yaml=workspace.workspace_yaml,
                    entrypoint=(
                        args.entrypoint or f"/{device.effective_entrypoint}"
                    ),
                    target_runtime=target_runtime,
                )
            if args.dry_run:
                print(_render_dry_run_summary(
                    project_name=project_name,
                    device=device,
                    layout=layout,
                    files=source.files(),
                    entrypoint=source.entrypoint(),
                    wipe=args.wipe,
                ))
                continue
            if args.wipe:
                print(
                    f"deploy: wiping filesystem on "
                    f"{device.transport}@{device.address} before deploy",
                )
            deleted: list[str] = []
            result = _make_deploy_runner(
                device, non_interactive=args.non_interactive,
            ).deploy_diff(
                source,
                wipe=args.wipe,
                on_file_deleted=deleted.append,
            )
            for stale_path in deleted:
                print(f"deploy: removed stale {stale_path}")
            if result.execute_output:
                print(result.execute_output, end="")
            if not result.success:
                _emit_failure_hints(result)
                exit_code = 1
    return exit_code


def _build_deploy_plan(
    workspace: WorkspaceLayout, args: argparse.Namespace,
) -> list[tuple[str, Path, list[Device]]] | int:
    """Resolve the (project, devices) pairs ``deploy`` will iterate.

    Returns a list of ``(project_slash_path, project_dir, [Device, ...])``
    tuples or an integer exit code when input validation fails.

    Three input shapes:

    * ``--all-projects`` — walk ``workspace.yml``'s ``deploy_targets``
      mapping; one tuple per (project, devices-it-targets) pair.
    * Positional name + ``--all-devices`` — one tuple targeting every
      device in ``devices.yml``.
    * Positional name (or default-when-only-one-project) — one tuple
      whose device list is either the user's ``--device`` /
      ``--runtime`` choice, or — when no per-deploy override is
      passed — the project's ``deploy_targets`` entry, falling through
      to the workspace's ``devices.yml`` default.
    """
    if args.all_projects:
        if (
            args.names
            or args.device_id is not None
            or args.runtime is not None
            or args.all_devices
        ):
            print(
                "deploy: --all-projects is mutually exclusive with positional "
                "names / --device / --runtime / --all-devices.",
                file=sys.stderr,
            )
            return 2
        targets = read_deploy_targets(workspace.workspace_yaml)
        if not targets:
            print(
                "deploy: --all-projects requires a `deploy_targets:` block "
                f"in {workspace.workspace_yaml.name}.  Map each project to "
                "one or more device ids and re-run.",
                file=sys.stderr,
            )
            return 2
        from chumicro_deploy.config.default import (  # noqa: PLC0415
            load_devices_yml,
        )

        plan: list[tuple[str, Path, list[Device]]] = []
        for project_path, device_ids in targets.items():
            project_dir = workspace.project_dir(project_path)
            if not project_dir.is_dir():
                print(
                    f"deploy: deploy_targets references unknown project "
                    f"{project_path!r} (no projects/{project_path}/ directory).",
                    file=sys.stderr,
                )
                return 2
            try:
                project_devices = [
                    load_devices_yml(workspace.devices_yaml, device_id=did)
                    for did in device_ids
                ]
            except (FileNotFoundError, ValueError) as error:
                print(
                    f"deploy: deploy_targets[{project_path!r}]: {error}",
                    file=sys.stderr,
                )
                return 2
            plan.append((project_path, project_dir, project_devices))
        return plan

    # Positional / default project resolution.
    if not args.names:
        candidates = workspace.list_projects()
        if not candidates:
            print(
                "deploy: no projects to deploy.  Create one with "
                "`new <name>` first.",
                file=sys.stderr,
            )
            return 2
        if len(candidates) > 1:
            print(
                "deploy: multiple projects in workspace; specify which "
                f"to deploy ({', '.join(candidates)}).",
                file=sys.stderr,
            )
            return 2
        project_name = candidates[0]
        print(f"deploy: defaulting to {project_name} (only project in workspace).")
    else:
        if len(args.names) > 1:
            print(
                "deploy: multi-project deploys are no longer supported — "
                "pass one positional name per `deploy` call.",
                file=sys.stderr,
            )
            return 2
        project_name = _resolve_project_name(workspace, args.names[0])
    project_dir = workspace.project_dir(project_name)
    if not project_dir.is_dir():
        raise SystemExit(f"error: project {project_dir} not found")

    if args.all_devices:
        if args.device_id is not None or args.runtime is not None:
            print(
                "deploy: --all-devices is mutually exclusive with "
                "--device / --runtime.",
                file=sys.stderr,
            )
            return 2
        return [(project_name, project_dir, _resolve_all_devices(workspace))]

    # Default-from-mapping: when the user passed neither --device nor
    # --runtime, consult workspace.yml's deploy_targets[project] before
    # falling back to devices.yml's defaults block.  Lets a workspace
    # owner with multiple boards stop typing --device for every deploy.
    if args.device_id is None and args.runtime is None:
        targets = read_deploy_targets(workspace.workspace_yaml)
        mapped = targets.get(project_name)
        if mapped:
            from chumicro_deploy.config.default import (  # noqa: PLC0415
                load_devices_yml,
            )

            try:
                mapped_devices = [
                    load_devices_yml(workspace.devices_yaml, device_id=did)
                    for did in mapped
                ]
            except (FileNotFoundError, ValueError) as error:
                print(
                    f"deploy: deploy_targets[{project_name!r}]: {error}",
                    file=sys.stderr,
                )
                return 2
            return [(project_name, project_dir, mapped_devices)]
    return [(project_name, project_dir, [_resolve_device(workspace, args)])]


def _render_projects_tree(
    workspace: WorkspaceLayout,
) -> str:
    """Format the workspace's projects as an indented Unicode tree.

    Empty workspace prints a friendly marker.  Otherwise:

    .. code-block:: text

        projects/
        ├── thermostat
        ├── upstairs/
        │   ├── bedroom_sensor
        │   └── nightstand_lamp
        └── garage/
            ├── controls/
            │   └── heater
            └── sensors/
                └── door_open

    Driven by :meth:`WorkspaceLayout.iter_projects_with_classification`
    so namespace dirs (``upstairs/``) always sit above their project
    leaves, matching depth-first display order.
    """
    items = workspace.iter_projects_with_classification()
    if not items:
        return "(no projects in this workspace)"
    classification_by_path: dict[str, ProjectClassification] = dict(items)
    # children["parent/path"] = sorted list of leaf segments.  Empty
    # string is the top level (children of `projects/`).
    children: dict[str, list[str]] = {"": []}
    for path in classification_by_path:
        segments = path.split("/")
        for depth in range(len(segments)):
            parent_key = "/".join(segments[:depth])
            children.setdefault(parent_key, [])
            leaf = segments[depth]
            if depth == len(segments) - 1 and leaf not in children[parent_key]:
                children[parent_key].append(leaf)
    for kids in children.values():
        kids.sort()

    lines = ["projects/"]

    def _walk(parent_path: str, prefix: str) -> None:
        kids = children.get(parent_path, [])
        for index, leaf in enumerate(kids):
            full_path = f"{parent_path}/{leaf}" if parent_path else leaf
            is_last = index == len(kids) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            classification = classification_by_path[full_path]
            if classification is ProjectClassification.NAMESPACE:
                lines.append(f"{prefix}{connector}{leaf}/")
                _walk(full_path, prefix + extension)
            else:
                lines.append(f"{prefix}{connector}{leaf}")

    _walk("", "")
    return "\n".join(lines)


def _cmd_projects(args: argparse.Namespace) -> int:
    """List the projects defined in the workspace under ``projects/``.

    Two views: the default :func:`_render_projects_tree` (Slice 4)
    draws an indented Unicode tree so namespaced workspaces are
    legible at a glance; ``--flat`` falls back to the legacy
    one-project-per-line slash-form output (handy for shell pipelines
    and ``grep``-style filtering).

    Local-only: walks ``projects/`` via
    :meth:`WorkspaceLayout.list_projects` and
    :meth:`WorkspaceLayout.iter_projects_with_classification`, both of
    which skip ``_template`` and leading ``.`` / ``_`` names.  An
    on-device variant that probes ``/lib/projects/`` for installed
    payloads is a follow-on once the REPL one-shot pattern lands as
    a public helper.
    """
    workspace = _resolve_workspace(args)
    if args.flat:
        names = workspace.list_projects()
        if not names:
            print("(no projects in this workspace)")
            return 0
        for name in names:
            print(name)
        return 0
    print(_render_projects_tree(workspace))
    return 0


#: Glyphs for ``status`` line prefixes.  Plain Unicode dingbats so
#: every reasonable terminal renders them; downstream consumers
#: that want strict ASCII can pipe through ``sed`` to remap.
_HEALTH_LEVEL_PREFIX: dict[HealthLevel, str] = {
    HealthLevel.OK: "✓",
    HealthLevel.WARN: "⚠",
    HealthLevel.ERROR: "✗",
}

#: Width of the label column in ``status`` output.  Picked so the
#: longest current label (``WORKSPACE.YML``) plus a 2-space gutter
#: lines up the prefix glyph at the same column for every row.
_STATUS_LABEL_WIDTH: int = 16


def _format_health_finding(finding: HealthFinding) -> str:
    """Return the one-line representation of *finding* for ``status``."""
    prefix = _HEALTH_LEVEL_PREFIX[finding.level]
    label = finding.label.ljust(_STATUS_LABEL_WIDTH)
    return f"{label}{prefix} {finding.message}"


def _print_health_findings(
    workspace: WorkspaceLayout,
    findings: list[HealthFinding],
) -> int:
    """Print *findings* with the status/doctor renderer; return exit code.

    Header line carries the workspace root.  Each finding renders as
    ``LABEL <glyph> message``; warning / error findings carry an
    optional hint indented under the label column.  Exit code flips
    to 1 only on at least one ERROR — warnings stay at 0 so the
    output composes cleanly with shell-pipe checks.
    """
    print(f"WORKSPACE       {workspace.root}")
    has_error = False
    for finding in findings:
        print(_format_health_finding(finding))
        if finding.hint and finding.level is not HealthLevel.OK:
            print(f"{' ' * _STATUS_LABEL_WIDTH}  hint: {finding.hint}")
        if finding.level is HealthLevel.ERROR:
            has_error = True
    return 1 if has_error else 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Print a one-line-per-check workspace health snapshot.

    Phase 2a of the workspace-ecosystem workstream.  Runs the three
    fast static checks (workspace.yml validity, devices.yml count,
    projects tree summary).  ``doctor`` (Phase 2b) is the stricter
    sibling that adds Python version checking and per-project AST
    scans for ``run()``.
    """
    workspace = _resolve_workspace(args)
    return _print_health_findings(workspace, collect_health_findings(workspace))


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Strict sibling of ``status`` — adds AST + Python-version checks.

    On top of ``status``'s four checks, ``doctor`` runs:

    * ``check_python_version`` — is the host Python on a supported
      version (3.11+).
    * ``check_project_run_functions`` — AST-walks each project's
      ``app.py`` and verifies a top-level ``run()`` definition
      exists (the workspace_runtime boot contract).

    Same renderer + exit-code rules as ``status``: errors flip exit
    to 1, warnings stay at 0.  Per-project failures list the failing
    project names in the hint so the user can navigate straight to
    the broken file.

    Phase 2b of the workspace-ecosystem workstream.  Per-device
    reachability probes (``check the board responds on its
    address``) are deferred until we have a hardware-cheap probe
    primitive that can run without blocking the static checks.
    """
    workspace = _resolve_workspace(args)
    return _print_health_findings(workspace, collect_doctor_findings(workspace))


#: Built-in demo payload — Step 5 of the beginner-onramp workstream.
#:
#: Cross-runtime safe (CircuitPython + MicroPython): only ``time.sleep``
#: + ``print``.  No hardware access — every supported board reaches the
#: print path identically, so the demo "just works" out-of-the-box on
#: any registered device without runtime-config or pin pickers.  Runs
#: for ~5 seconds and exits cleanly so the deploy command's
#: synchronous-execute path doesn't appear to hang.
DEMO_PAYLOAD: str = (
    "import time\n"
    "print('Hello from ChuMicro!')\n"
    "print('Your board is alive.')\n"
    "for index in range(5):\n"
    "    time.sleep(1)\n"
    "    print('  tick ' + str(index + 1) + '/5')\n"
    "print('demo complete!')\n"
)


def _cmd_demo(args: argparse.Namespace) -> int:
    """Deploy a baked-in LED-blink-shaped "hello world" to the active device.

    Step 5 of the beginner-onramp workstream — gives a user with a
    freshly-registered board something to ship on day one without
    having to write code, configure wifi, or pick a project.  Runs
    synchronously: deploys the payload, captures execute output,
    prints it.  Total wall-clock ~5 seconds.

    The payload is a runtime-agnostic print loop (no ``board`` /
    ``machine`` imports) so the demo works on any supported runtime
    + board.  An LED-blink variant is a future enhancement once the
    LED-pin abstraction lands.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import FileMapSource  # noqa: PLC0415

    entrypoint_path = f"/{device.effective_entrypoint}"
    source = FileMapSource(
        files={entrypoint_path: DEMO_PAYLOAD},
        entrypoint=entrypoint_path,
    )
    print(
        f"demo: deploying built-in payload to "
        f"{device.transport} @ {device.address} ...",
    )
    result = _make_deploy_runner(
        device, non_interactive=args.non_interactive,
    ).deploy(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        _emit_failure_hints(result)
        return 1
    return 0


def _stdin_prompt(prompt_text: str) -> str:
    """Real-stdin prompt — tests inject a deterministic substitute.

    Sole indirection point for ``_cmd_bootstrap`` so the wizard's
    branching logic stays unit-testable without TTY plumbing.
    """
    return input(prompt_text)


def _suggest_device_id(implementation: DeviceImplementation) -> str:
    """Suggest a device id from the probed machine string.

    Strips the ``" with <chip>"`` SoC suffix and slugifies the
    leading board identifier:

    * ``"Raspberry Pi Pico W with rp2040"``     → ``"raspberry-pi-pico-w"``
    * ``"S2Mini with ESP32S2-S2FN4R2"``         → ``"s2mini"``
    * ``"LOLIN_S2_MINI with ESP32-S2FN4R2"``    → ``"lolin-s2-mini"``

    The strip pattern is ``" with <anything-to-end-of-string>"``
    rather than ``\\w+$`` — chip variants like ``ESP32S2-S2FN4R2``
    contain hyphens and would otherwise survive into the slug as
    ``s2mini-with-esp32s2-s2fn4r2`` (F4 of the 2026-05-06
    verification pass).

    Falls back to ``"board"`` when ``machine`` is empty (older
    firmware) or sanitises to nothing — neutral default that the
    user can rename via ``rename --device``.
    """
    machine = implementation.machine or ""
    # Trim the trailing " with <chip>" tail at end-of-string.  Anchored
    # at $ so a board with the word "with" mid-name doesn't lose its tail.
    cleaned = re.sub(r"\s+with\s+.*$", "", machine, flags=re.IGNORECASE)
    # Replace non-identifier runs with single hyphens, lowercase.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    return slug or "board"


def _resolve_bootstrap_port(
    explicit_port: str | None,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> str | None:
    """Pick the port to onboard against.

    * ``explicit_port`` set → use it verbatim.
    * No ports detected → print a hint, return ``None`` (caller exits 1).
    * Exactly one port → use it without prompting.
    * Multiple ports → list them, prompt for a number.

    Args:
        explicit_port: ``--port`` flag value, or ``None`` to discover
            interactively.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.

    Returns:
        The chosen port path, or ``None`` on no-discovery / invalid
        input.
    """
    if explicit_port:
        return explicit_port
    from serial.tools import list_ports as _list_ports  # noqa: PLC0415

    ports = sorted(_list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print(
            "bootstrap: no serial ports detected.  "
            "Plug in a board and try again.",
            file=sys.stderr,
        )
        return None
    if len(ports) == 1:
        only_port = ports[0]
        print(f"bootstrap: only one port found — using {only_port.device}.")
        return only_port.device
    print("bootstrap: pick a board:")
    for index, port in enumerate(ports, start=1):
        description = port.description or "(no description)"
        print(f"  [{index}] {port.device}  {description}")
    raw_choice = prompt_func(f"  Pick [1-{len(ports)}]: ")
    try:
        chosen_index = int(raw_choice.strip())
    except ValueError:
        print(
            f"bootstrap: invalid choice {raw_choice!r}", file=sys.stderr,
        )
        return None
    if chosen_index < 1 or chosen_index > len(ports):
        print(
            f"bootstrap: choice {chosen_index} out of range",
            file=sys.stderr,
        )
        return None
    return ports[chosen_index - 1].device


def _resolve_bootstrap_device_id(
    explicit_id: str | None,
    suggested_id: str,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> str:
    """Either the ``--device-id`` flag's value or an interactive prompt.

    The prompt shows the suggestion in brackets and accepts a blank
    line to mean "use the suggestion".
    """
    if explicit_id:
        return explicit_id
    raw = prompt_func(f"  Device id [{suggested_id}]: ")
    return raw.strip() or suggested_id


def _cmd_bootstrap(  # noqa: C901, PLR0912 — wizard branches stay flat for readability
    args: argparse.Namespace,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> int:
    """Onboard a board end-to-end: pick → probe → register → demo.

    Step 4 of the beginner-onramp workstream — the integration
    command that ties Steps 1-3 + 5 into a single user-visible
    flow.  A user with a freshly-plugged board runs
    ``chumicro-workspace bootstrap`` and walks through:

    1. Pick a port.  When exactly one is detected, it's used
       silently; otherwise the wizard prints a numbered list and
       prompts.  ``--port <path>`` skips the pick.
    2. Probe with runtime auto-inference (Step 3 of the
       workstream).  Failure prints the same diagnosis hints
       ``add-device`` does and exits 1.
    3. Display detected runtime + version + machine.  The
       firmware-support floor is checked; OLD / UNKNOWN /
       UNPARSEABLE statuses print a warning but don't abort.
    4. Pick a device id.  ``--device-id <id>`` skips the prompt.
       The default suggestion is derived from the probed machine
       string (e.g. ``"raspberry-pi-pico-w"``).
    5. Register the device in ``devices.yml`` — same write as
       ``add-device`` but no second probe.
    6. Optional ``--with-demo`` deploys the built-in demo
       payload (Step 5 of the workstream) so the user sees their
       board run code immediately.
    7. Print next-steps for the user (``new`` / ``deploy`` /
       ``repl``).

    Args:
        args: Parsed CLI args.  ``port``, ``device_id``, and
            ``with_demo`` are the wizard's three optional knobs.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.
    """
    workspace = _resolve_workspace(args)

    # 1. Port pick.
    port = _resolve_bootstrap_port(args.port, prompt_func=prompt_func)
    if port is None:
        return 1

    # 2. Probe.
    print(f"bootstrap: probing {port} ...")
    inference = probe_with_runtime_inference(port)
    if inference.runtime is None or inference.info is None:
        from chumicro_deploy import Device  # noqa: PLC0415

        diagnosis = detect_board_state(
            Device(transport="micropython", address=port),
        )
        if inference.last_exception is not None:
            exception = inference.last_exception
            print(
                f"bootstrap: auto-detect failed "
                f"({type(exception).__name__}: {exception}).",
                file=sys.stderr,
            )
        else:
            print(
                "bootstrap: auto-detect failed — "
                "no runtime returned a probe marker.",
                file=sys.stderr,
            )
        for line in diagnosis.next_steps:
            print(f"  {line}", file=sys.stderr)
        return 1

    info = inference.info
    implementation = info.implementation
    print(f"  runtime: {implementation.name} {implementation.version}")
    if implementation.machine:
        print(f"  machine: {implementation.machine}")

    # 3. Firmware-support check.
    support = check_firmware_supported(implementation)
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"  note: {implementation.name} firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)

    # 4. Device id pick.
    suggested_id = _suggest_device_id(implementation)
    device_id = _resolve_bootstrap_device_id(
        args.device_id, suggested_id, prompt_func=prompt_func,
    )

    # 5. Register.
    data = load_devices(workspace.devices_yaml)
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if implementation.machine:
        hardware["machine"] = implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id
    try:
        add_device(
            data,
            device_id=device_id,
            runtime=implementation.name,
            address=port,
            hardware=hardware or None,
            firmware_version=implementation.version or None,
        )
    except DeviceAlreadyExistsError:
        print(
            f"bootstrap: device id {device_id!r} already exists "
            f"in {workspace.devices_yaml}.  Pick a different id "
            "or run `add-device --force` to refresh the existing "
            "entry.",
            file=sys.stderr,
        )
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"  registered {device_id} at {port}.")

    # 6. Optional demo.
    if args.with_demo:
        demo_args = argparse.Namespace(
            workspace_dir=args.workspace_dir,
            device_id=device_id,
            runtime=None,
            non_interactive=False,
        )
        demo_exit = _cmd_demo(demo_args)
        if demo_exit != 0:
            return demo_exit

    # 7. Summary.
    print()
    print("bootstrap: ready.  Next steps:")
    print(
        "  python run.py new <project-name>      "
        "# create a new project under projects/",
    )
    print(
        "  python run.py deploy                "
        "# deploy your only project (no name needed)",
    )
    print(
        "  python run.py repl                  "
        "# open the REPL on your board",
    )
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    """Run the workspace's pytest suite.

    Shells out to ``pytest`` so users get the standard pytest UX
    (``-k``, ``-x``, ``-v``, etc.) without re-implementing argument
    forwarding.  Extra args after ``--`` are passed through verbatim.

    Phase 5 wiring: when ``workspace.yml``'s
    ``quality.coverage_threshold`` is set, prepend
    ``--cov-fail-under=<n>`` so the workspace-level gate kicks in.
    User passthrough args (after ``--``) win over the workspace
    default — pytest takes the last occurrence.
    """
    workspace = _resolve_workspace(args)
    quality = load_quality_config(workspace.workspace_yaml)
    quality_flags: list[str] = []
    if quality.coverage_threshold is not None:
        quality_flags.append(f"--cov-fail-under={quality.coverage_threshold}")
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        [sys.executable, "-m", "pytest", *quality_flags, *args.pytest_args],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


def _cmd_preflight(args: argparse.Namespace) -> int:
    """Run lint + tests as a single sanity gate.

    Composition of :func:`_cmd_lint` then :func:`_cmd_test` — same
    workspace, same ``quality:`` knobs from ``workspace.yml``
    (``lint.enabled`` / ``lint.select`` / ``coverage_threshold``),
    no extra args forwarded.  Aimed at "all the fast static checks
    I'd want before pushing" — without CI, this is the gate the
    user runs by hand.

    Returns nonzero on the first failing step (short-circuit) so
    a lint failure doesn't cost a test run.  Both steps respect
    their disable knobs (``lint.enabled = false`` skips lint
    silently; no equivalent disable for tests today).
    """
    workspace = _resolve_workspace(args)
    print(f"preflight: {workspace.root}")

    print("\npreflight: --- lint ---")
    lint_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        ruff_args=[],
    )
    lint_exit = _cmd_lint(lint_args)
    if lint_exit != 0:
        print(f"\npreflight: lint failed (exit {lint_exit})")
        return lint_exit

    print("\npreflight: --- test ---")
    test_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        pytest_args=[],
    )
    test_exit = _cmd_test(test_args)
    if test_exit != 0:
        print(f"\npreflight: tests failed (exit {test_exit})")
        return test_exit

    print("\npreflight: lint + tests both passed.")
    return 0


def _cmd_dump_config(args: argparse.Namespace) -> int:
    """Print the merged runtime config a project would receive on deploy.

    Runs the deploy-time pipeline up to (but not through) the msgpack
    write — ``workspace.yml`` defaults + project config deep-merged —
    then pretty-prints the result.  Lets users see exactly what their
    on-device ``chumicro_config.runtime`` will read without actually
    deploying.

    Useful for: debugging which layer a key landed in after the merge,
    inspecting the shape before adding consumers on the device,
    confirming that gitignored credential overrides flowed through.

    Output format defaults to JSON (sorted keys, indent 2) for
    diffability; ``--repr`` switches to ``repr()`` for cases where
    the raw Python types matter (e.g. seeing ``bytes`` vs ``str``).
    """
    from chumicro_workspace.deploy_source import find_project_config  # noqa: PLC0415
    from chumicro_workspace.pipeline import compose_runtime_config  # noqa: PLC0415

    workspace = _resolve_workspace(args)
    project_dir = workspace.project_dir(_resolve_project_name(workspace, args.project))
    if not project_dir.is_dir():
        raise SystemExit(f"error: project {project_dir} not found")

    try:
        project_config_path = find_project_config(project_dir)
    except FileNotFoundError:
        project_config_path = None

    resolved = compose_runtime_config(
        workspace_yaml=workspace.workspace_yaml,
        project_config=project_config_path,
    )

    if args.repr:
        print(repr(resolved))
    else:
        import json  # noqa: PLC0415
        print(json.dumps(resolved, indent=2, sort_keys=True, default=repr))
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run ``ruff check`` across the workspace.

    Picks up the workspace's ``[tool.ruff]`` config from
    ``pyproject.toml`` automatically — the canonical workspace
    template ships a ruff config that matches chumicro's own tone.
    Extra args after ``--`` forward to ruff (e.g. ``--fix``,
    ``--select`` overrides).

    No-op (exit 0 with a hint) when ``ruff`` isn't installed —
    keeps the command discoverable in workspaces that haven't
    pulled the ``[dev]`` extra yet.

    Phase 5 wiring: ``workspace.yml``'s ``quality.lint.enabled``
    and ``quality.lint.select`` knobs flow through.  ``enabled =
    false`` skips the run entirely; ``select`` prepends a
    ``--select <comma list>`` flag (so user passthrough still
    overrides — ruff picks up the last ``--select``).
    """
    workspace = _resolve_workspace(args)
    quality = load_quality_config(workspace.workspace_yaml)
    if not quality.lint.enabled:
        print(
            "lint: disabled in workspace.yml ([quality.lint] enabled = false).",
        )
        return 0
    try:
        import ruff  # noqa: F401, PLC0415  — availability probe
    except ImportError:
        print(
            "ruff is not installed in this venv.  Install the dev "
            "extras with:\n"
            "    .venv/bin/pip install -e .[dev]\n"
            "or add ruff to your workspace's pyproject.toml deps.",
        )
        return 0
    quality_flags: list[str] = []
    if quality.lint.select:
        quality_flags.extend(["--select", ",".join(quality.lint.select)])
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        [
            sys.executable, "-m", "ruff", "check",
            *quality_flags, *args.ruff_args, ".",
        ],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


#: Default tail-window duration (seconds) when ``repl <project>`` is
#: invoked without an explicit ``--tail SECONDS`` value.  Picked to
#: cover the common "deploy a heartbeat project, watch a few cycles
#: print, exit clean" inner-loop pattern; users with long boot
#: sequences can override.
_DEFAULT_REPL_TAIL_SECONDS: float = 30.0


def _resolve_repl_mode(requested: str, *, stdin: object) -> str:
    """Pick the actual REPL mode given the user's *requested* value.

    *requested* is ``"auto"`` / ``"line"`` / ``"passthrough"``.  Auto
    picks ``line`` when stdin is a TTY (an interactive terminal) and
    ``passthrough`` otherwise — line mode requires interactive input
    (``prompt_toolkit`` reads from the terminal), so falling back to
    passthrough lets the same command work under CI / piped stdin.

    *stdin* is injected so tests can verify both branches without
    monkey-patching ``sys.stdin``.
    """
    if requested != "auto":
        return requested
    isatty = getattr(stdin, "isatty", None)
    return "line" if (callable(isatty) and isatty()) else "passthrough"


def _cmd_repl(args: argparse.Namespace) -> int:
    """Open an interactive REPL, tail output, or deploy-then-tail.

    Three modes:

    * ``repl`` — interactive REPL on the selected board.
    * ``repl --tail SECONDS`` — capture the next *SECONDS* of REPL
      output, exit cleanly.
    * ``repl <project> [--tail SECONDS]`` — deploy *project* to the
      board first, then tail.  Combines what used to be
      ``deploy <project> && repl --tail`` into one command.  When
      ``--tail`` is omitted with a positional, defaults to
      :data:`_DEFAULT_REPL_TAIL_SECONDS`.

    *project* accepts bare / slash / dotted forms — same shape as
    ``deploy``.  The deploy uses the workspace-runtime boot-shim
    layout (``project_boot_source``); for flat-layout deploys, run
    ``deploy`` and ``repl --tail`` separately.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.project is not None:
        resolved_name = _resolve_project_name(workspace, args.project)
        project_dir = workspace.project_dir(resolved_name)
        if not project_dir.is_dir():
            raise SystemExit(f"error: project {project_dir} not found")
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
        )
        print(f"repl: deploying {resolved_name} ...")
        deleted: list[str] = []
        deploy_result = _make_deploy_runner(
            device, non_interactive=args.non_interactive,
        ).deploy_diff(
            source,
            on_file_deleted=deleted.append,
        )
        for stale_path in deleted:
            print(f"repl: removed stale {stale_path}")
        if deploy_result.execute_output:
            print(deploy_result.execute_output, end="")
        if not deploy_result.success:
            _emit_failure_hints(deploy_result)
            return 1
        tail_seconds = (
            args.tail if args.tail is not None else _DEFAULT_REPL_TAIL_SECONDS
        )
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            tail_seconds,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    if args.tail is not None:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    mode = _resolve_repl_mode(args.mode, stdin=sys.stdin)
    if mode == "line":
        from chumicro_repl import interactive_line  # noqa: PLC0415

        def open_session() -> int:
            return interactive_line(device)
    else:
        from chumicro_repl import interactive  # noqa: PLC0415

        def open_session() -> int:
            return interactive(device)

    if args.non_interactive:
        return open_session()

    from chumicro_repl import coached_session_start  # noqa: PLC0415

    return coached_session_start(open_session)


def _cmd_install_firmware(args: argparse.Namespace) -> int:
    """Download + flash firmware onto the selected board.

    ``upgrade-firmware`` is registered as an alias of this command —
    flashing the same URL onto a board that already has firmware *is*
    an upgrade, so the implementation does not branch.

    ``--url`` is optional: when omitted, the URL is derived via
    :func:`chumicro_workspace.derive_firmware_url` from the device
    entry's ``hardware.firmware_source`` (custom), ``hardware.board_id``
    (CP S3 listing → latest stable), or ``hardware.machine`` (MP
    curated map).  Unresolvable cases surface a precise message + exit
    2 so the user can paste an explicit URL into ``--url`` (or the
    entry's ``hardware.firmware_source``).
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.url is not None:
        firmware_url = args.url
    else:
        entry = _find_devices_yml_entry_for_args(workspace, args)
        if entry is None:
            print(
                "install-firmware: --url omitted and no device entry "
                "to derive from.  Pass --url explicitly or register "
                "the device with `add-device` first.",
                file=sys.stderr,
            )
            return 2
        try:
            firmware_url = derive_firmware_url(entry, allow_prerelease=args.allow_prerelease)
        except UnresolvedFirmwareError as exception:
            print(f"install-firmware: {exception}", file=sys.stderr)
            return 2
        print(f"install-firmware: resolved {firmware_url}")

    from chumicro_deploy import flash_firmware  # noqa: PLC0415

    flash_firmware(
        firmware_url,
        device,
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase,
        flash_offset=args.offset,
    )
    return 0


def _cmd_reset_board(args: argparse.Namespace) -> int:
    """Erase the device's user filesystem and leave it idle.

    Standalone counterpart to ``deploy --wipe`` — same destructive
    primitive (:meth:`chumicro_deploy.TransportProtocol.wipe_filesystem`)
    without coupling the wipe to a follow-up redeploy.  Used to recover
    a board whose flash filled up with stage residue (LittleFS
    metadata + wear-leveling artifacts that ``os.remove`` cannot
    reclaim — see the :meth:`wipe_filesystem` docstring for the
    per-runtime recipe matrix).

    Destructive — every user file the runtime can see is gone after
    this returns, including out-of-scope files like ``settings.toml``,
    hand-edited ``boot.py``, and uploaded assets.  Gated behind
    ``--yes`` to avoid wiping a board on a typoed device id.

    No-op (with a printed note) when the device's effective deploy
    mode is RAM / mount — those modes never wrote to flash so there's
    nothing persistent to wipe.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    transport = device.create_transport()
    target = f"{device.transport}@{device.address}"
    if transport.mode in ("ram", "mount"):
        print(
            f"reset-board: {target} is configured for {transport.mode} "
            "mode — nothing in flash to wipe.  Re-run on a board whose "
            "deploy_mode is flash / copy if you intended to clear "
            "persistent state.",
        )
        return 0

    if not args.yes:
        print(
            f"reset-board: refusing to wipe {target} without --yes.  "
            "This destroys every user file on the board, including "
            "settings.toml and any hand-edited boot.py.",
            file=sys.stderr,
        )
        return 2

    print(f"reset-board: wiping filesystem on {target}")
    transport.connect()
    try:
        transport.wipe_filesystem()
    finally:
        transport.disconnect()
    print(f"reset-board: {target} filesystem wiped.")
    return 0


def _cmd_install_libraries(args: argparse.Namespace) -> int:
    """Install chumicro libraries onto a device via circup (CP) / mip (MP).

    Regular-mode counterpart to dev-mode's ``library_sources:`` auto-sync
    (gap #4 of the workspace-template dev-and-regular-mode-gaps audit).
    AST-walks the project's source tree to discover every
    ``chumicro_<name>`` top-level import, then shells out to the right
    runtime tool to fetch + install those packages from the published
    bundle:

    * **CircuitPython** — one ``circup install <pkg-list>`` invocation
      against the bundle the user has already registered (pre-flight
      check warns if no chumicro bundle is in circup's bundle list).
      The CIRCUITPY drive is auto-detected; pass ``--drive-path`` to
      pin a specific mount when multiple boards share a host.
    * **MicroPython** — one ``mpremote connect <addr> mip install
      github:ChuMicro/<bundle>/<package>`` per chumicro library
      (mip doesn't take a list).

    ``--experimental`` swaps the bundle URL to
    ``ChuMicro-Bundle-Experimental`` (mip), or surfaces a hint for
    the equivalent ``circup bundle-add`` command (circup needs the
    bundle pre-registered).

    ``--dry-run`` prints the commands that would run but does not
    execute them — useful for "what would this do on my air-gapped
    rig?" inspection or for paste-into-elsewhere when host doesn't
    have circup / mpremote installed.
    """
    workspace = _resolve_workspace(args)
    project_name = _resolve_project_name(workspace, args.project)
    project_dir = workspace.project_dir(project_name)
    if not project_dir.is_dir():
        print(
            f"install-libraries: project {project_dir} not found",
            file=sys.stderr,
        )
        return 1

    from chumicro_workspace.install_libraries import (  # noqa: PLC0415
        EXPERIMENTAL_BUNDLE_REPO,
        STABLE_BUNDLE_REPO,
        build_circup_command,
        build_mip_commands,
        discover_chumicro_imports,
        import_name_to_package,
    )

    imports = discover_chumicro_imports(project_dir)
    if not imports:
        print(
            f"install-libraries: no chumicro imports found in {project_name} — "
            "nothing to install.",
        )
        return 0
    packages = sorted(import_name_to_package(name) for name in imports)
    print(
        f"install-libraries: {project_name} imports "
        f"{len(packages)} chumicro libraries:",
    )
    for package in packages:
        print(f"  {package}")

    device = _resolve_device(workspace, args)
    bundle_repo = (
        EXPERIMENTAL_BUNDLE_REPO if args.experimental else STABLE_BUNDLE_REPO
    )
    transport = str(device.transport)

    if transport == "circuitpython":
        command = build_circup_command(packages, drive_path=args.drive_path)
        commands_to_run: list[list[str]] = [command]
        if args.experimental:
            print(
                "install-libraries: --experimental + CP — make sure you've run "
                f"`circup bundle-add ChuMicro/{EXPERIMENTAL_BUNDLE_REPO}` "
                "first; circup pulls from registered bundles only.",
            )
    elif transport == "micropython":
        commands_to_run = build_mip_commands(
            packages, bundle_repo=bundle_repo, address=device.address,
        )
    else:
        print(
            f"install-libraries: unsupported transport {transport!r} "
            f"on device {device.address}.",
            file=sys.stderr,
        )
        return 2

    print(
        f"install-libraries: target {transport}@{device.address} "
        f"({bundle_repo})",
    )
    for command in commands_to_run:
        print(f"  $ {' '.join(command)}")
        if args.dry_run:
            continue
        completed = subprocess.run(command, check=False)  # noqa: S603 — args fully controlled
        if completed.returncode != 0:
            print(
                f"install-libraries: command failed (exit {completed.returncode}); "
                "fix the underlying tool error and re-run install-libraries.",
                file=sys.stderr,
            )
            return completed.returncode
    if args.dry_run:
        print("install-libraries: --dry-run — no commands executed.")
    else:
        print(f"install-libraries: installed {len(packages)} libraries.")
    return 0


# ---------------------------------------------------------------------------
# Stubs — register the surface; implementation lands in a later slice
# ---------------------------------------------------------------------------


def _stub(slice_or_phase: str) -> int:
    """Emit a uniform "not implemented yet" message and return exit-code 2."""
    print(
        f"not implemented yet — landing in {slice_or_phase}.",
        file=sys.stderr,
    )
    return 2


def _cmd_add_device(args: argparse.Namespace) -> int:
    """Probe a board + register it in devices.yml.

    Builds a fresh entry by probing the supplied address: ``runtime``
    + ``hardware.uid`` + ``hardware.machine`` come from
    :func:`chumicro_deploy.probe_device`; ``address`` rides through
    as-is.  When ``--runtime`` is omitted, the runtime is inferred
    by trying every candidate transport in turn — the user can plug
    a fresh board in and register it without knowing what firmware
    it runs.  Re-running with the same id triggers a re-probe and is
    blocked unless ``--force`` is passed (the typical second
    invocation is "I swapped boards on this id" — make the user
    confirm).
    """
    workspace = _resolve_workspace(args)
    from chumicro_deploy import Device, probe_device  # noqa: PLC0415

    if args.runtime is None:
        inference = probe_with_runtime_inference(args.address)
        if inference.runtime is None or inference.info is None:
            # Fall through to the existing diagnose-and-print-error
            # path with whichever transport candidate was last tried.
            probe_device_obj = Device(
                transport="micropython", address=args.address,
            )
            diagnosis = detect_board_state(probe_device_obj)
            if inference.last_exception is not None:
                exception = inference.last_exception
                print(
                    f"add-device: auto-detect failed "
                    f"({type(exception).__name__}: {exception}).",
                    file=sys.stderr,
                )
            else:
                print(
                    "add-device: auto-detect failed — "
                    "no runtime returned a probe marker.",
                    file=sys.stderr,
                )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1
        info = inference.info
        print(
            f"add-device: auto-detected runtime = {inference.runtime}",
        )
    else:
        probe_device_obj = Device(transport=args.runtime, address=args.address)
        try:
            info = probe_device(probe_device_obj)
        except Exception as exception:  # noqa: BLE001 — onboarding diagnoses every failure
            diagnosis = detect_board_state(probe_device_obj)
            print(
                f"add-device: probe failed "
                f"({type(exception).__name__}: {exception}).",
                file=sys.stderr,
            )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1
        if info.implementation is None:
            diagnosis = detect_board_state(probe_device_obj)
            if diagnosis.state is BoardState.UF2_BOOTLOADER:
                print(
                    "add-device: board is in UF2 bootloader, not REPL — "
                    "install firmware first.",
                    file=sys.stderr,
                )
            else:
                print(
                    "add-device: probe did not return implementation marker",
                    file=sys.stderr,
                )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1

    firmware_version = info.implementation.version
    support = check_firmware_supported(info.implementation)

    data = load_devices(workspace.devices_yaml)
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if info.implementation.machine:
        hardware["machine"] = info.implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id

    # When the user didn't supply a positional id, derive one from the
    # probe's machine + runtime (F4 of the 2026-05-06 verification).
    # Suggested id collisions resolve via numeric suffix; the user can
    # rename the entry afterwards via ``rename --device``.
    if args.id is None:
        existing_ids = set(list_device_ids(data))
        args.id = _suggest_add_device_id(
            implementation=info.implementation,
            existing_ids=existing_ids,
        )
        print(f"add-device: using suggested id {args.id!r} (derived from probe)")

    try:
        add_device(
            data,
            device_id=args.id,
            runtime=info.implementation.name,
            address=args.address,
            hardware=hardware or None,
            description=args.description,
            firmware_version=firmware_version or None,
        )
    except DeviceAlreadyExistsError:
        if not args.force:
            print(
                f"add-device: {args.id!r} already exists; pass --force "
                "to re-probe and update the entry",
                file=sys.stderr,
            )
            return 1
        # Re-probe path: keep the existing entry's user-owned fields,
        # refresh the address silently, and update hardware-once leaves
        # under --force semantics so a board swap is reflected.
        update_device_address(data, args.id, args.address)
        if firmware_version:
            update_device_firmware_version(data, args.id, firmware_version)
        try:
            update_device_hardware(data, args.id, hardware, force=True)
        except HardwareOverwriteError as exception:
            print(f"add-device: {exception}", file=sys.stderr)
            return 1

    dump_devices(data, workspace.devices_yaml)
    print(f"add-device: registered {args.id} ({info.implementation.name})")
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"add-device: warning — {info.implementation.name} "
            f"firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)
    return 0


def _cmd_rename(args: argparse.Namespace) -> int:
    """Rename a project directory or a device id.

    Two modes (mutually exclusive): ``--project OLD NEW`` moves the
    project directory under ``projects/`` (Slice 4 — both names accept
    bare / slash / dotted forms, intermediate namespace dirs are
    auto-created when the new path is in a fresh namespace);
    ``--device OLD NEW`` rewrites the devices.yml entry id + every
    reference to it under ``defaults:``.

    A project rename does NOT touch already-deployed devices —
    re-deploy the project under its new name to refresh ``/active.py``
    on each board.
    """
    workspace = _resolve_workspace(args)

    if (args.project is None) == (args.device is None):
        print(
            "rename: pass exactly one of --project OLD NEW or --device OLD NEW",
            file=sys.stderr,
        )
        return 2

    if args.project is not None:
        old_input, new_input = args.project
        _validate_project_name(old_input)
        _validate_project_name(new_input)
        # Old name accepts bare-name disambiguation against the live
        # tree (mirrors deploy / switch).  New name is just normalised
        # — it doesn't exist yet so disambiguation doesn't apply.
        resolved_old = _resolve_project_name(workspace, old_input)
        resolved_new = new_input.replace(".", "/")
        old_path = workspace.project_dir(resolved_old)
        new_path = workspace.project_dir(resolved_new)
        if not old_path.is_dir():
            print(f"rename: project {old_path} not found", file=sys.stderr)
            return 1
        if new_path.exists():
            print(f"rename: {new_path} already exists", file=sys.stderr)
            return 1
        created_namespaces = _ensure_namespace_parents(workspace, new_path)
        for namespace_dir in created_namespaces:
            print(
                f"rename: creating namespace "
                f"{namespace_dir.relative_to(workspace.root)}/",
            )
        old_path.rename(new_path)
        print(f"rename: {resolved_old} → {resolved_new}")
        return 0

    old_id, new_id = args.device
    data = load_devices(workspace.devices_yaml)
    try:
        rename_device(data, old_id, new_id)
    except DeviceNotFoundError:
        print(f"rename: device {old_id!r} not found in devices.yml", file=sys.stderr)
        return 1
    except DeviceAlreadyExistsError as exception:
        print(f"rename: {exception}", file=sys.stderr)
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"rename: device {old_id} → {new_id}")
    return 0


def _cmd_sim(_args: argparse.Namespace) -> int:
    """Run a project in CPython simulation."""
    return _stub("Phase 4a (sim runner — slice TBD after Slices 3-7)")


def _cmd_env(_args: argparse.Namespace) -> int:  # noqa: CHU001 — workstream-spec command name
    """List / show workspace environments."""
    return _stub("Phase 4a (environments — slice TBD after Slices 3-7)")


def _cmd_use(_args: argparse.Namespace) -> int:
    """Switch the active workspace environment."""
    return _stub("environments — not implemented yet")


def _cmd_sync(_args: argparse.Namespace) -> int:
    """Re-apply the workspace template (superseded by `update`)."""
    return _stub("superseded by `chumicro-workspace update`")


def _cmd_upgrade(_args: argparse.Namespace) -> int:
    """Pin to a newer workspace template version (superseded by `update --ref`)."""
    return _stub(
        "superseded by `chumicro-workspace update --ref <ref>`",
    )


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace",
        description=(
            "Host-side dispatcher for ChuMicro project workspaces — "
            "deploy projects, probe boards, open REPLs, and manage "
            "devices.yml from one CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ----- setup ---------------------------------------------------------
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install dependencies and materialize template files.",
    )
    _add_workspace_arg(setup_parser)
    setup_parser.set_defaults(func=_cmd_setup)

    # ----- init ----------------------------------------------------------
    init_parser = subparsers.add_parser(
        "init",
        help="Clone the workspace template into a target directory.",
    )
    init_parser.add_argument(
        "target",
        type=Path,
        help="Workspace directory to create.",
    )
    init_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    init_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to clone (defaults to the remote's HEAD).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Clear the target before cloning if non-empty.",
    )
    init_parser.set_defaults(func=_cmd_init)

    # ----- update --------------------------------------------------------
    update_parser = subparsers.add_parser(
        "update",
        help=(
            "Re-flow tool-owned template files from upstream. "
            "User-owned files are skipped."
        ),
    )
    _add_workspace_arg(update_parser)
    update_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    update_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to fetch (defaults to the remote's HEAD).",
    )
    update_parser.set_defaults(func=_cmd_update)

    # ----- new -----------------------------------------------------------
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
            "`new garage/heater --from examples/two_projects/server`."
        ),
    )
    new_parser.add_argument(
        "--library",
        action="store_true",
        help=(
            "Scaffold a chumicro-style library under "
            "<workspace>/libraries/<name>/ (Phase 4).  Mutually "
            "exclusive with --from / --workbench; uses the built-in "
            "scaffolder."
        ),
    )
    new_parser.add_argument(
        "--workbench",
        action="store_true",
        help=(
            "Scaffold a host-only workbench tool under "
            "<workspace>/workbench/<name>/.  Same scaffolder as "
            "--library, but uses a workbench-flavoured pyproject "
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

    # ----- add-device ----------------------------------------------------
    add_device_parser = subparsers.add_parser(
        "add-device",
        help="Probe a board and register it in devices.yml.",
    )
    _add_workspace_arg(add_device_parser)
    add_device_parser.add_argument(
        "id",
        nargs="?",
        default=None,
        help=(
            "User-friendly device id (e.g. 'back-porch-mp').  Optional: "
            "when omitted, a default is derived from the probe's "
            "machine string + runtime suffix (e.g. "
            "'raspberry-pi-pico-w-cp').  When the suggested id collides "
            "with an existing entry in devices.yml, a numeric suffix "
            "is appended (e.g. 'raspberry-pi-pico-w-cp-2')."
        ),
    )
    add_device_parser.add_argument(
        "--address",
        required=True,
        help="Serial port path of the connected board.",
    )
    add_device_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Runtime to probe — picks the right Device facade for "
            "probe_device.  Optional: when omitted, the runtime is "
            "auto-detected by trying both transports against the "
            "given address (Step 3 of the beginner-onramp)."
        ),
    )
    add_device_parser.add_argument(
        "--description",
        default=None,
        help="Free-form note recorded under 'description:' (user-owned zone).",
    )
    add_device_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing entry with this id — refreshes the "
            "address and hardware-once fields from the live probe."
        ),
    )
    add_device_parser.set_defaults(func=_cmd_add_device)

    # ----- probe ---------------------------------------------------------
    probe_parser = subparsers.add_parser(
        "probe",
        help="Print the runtime identity reported by the selected board.",
    )
    _add_workspace_arg(probe_parser)
    _add_device_selector(probe_parser)
    probe_parser.set_defaults(func=_cmd_probe)

    # ----- discover ------------------------------------------------------
    discover_parser = subparsers.add_parser(
        "discover",
        help="List the serial ports the host currently sees.",
    )
    discover_parser.set_defaults(func=_cmd_discover)

    # ----- devices -------------------------------------------------------
    devices_parser = subparsers.add_parser(
        "devices",
        help="Print every entry in devices.yml.",
    )
    _add_workspace_arg(devices_parser)
    devices_parser.set_defaults(func=_cmd_devices)

    # ----- deploy --------------------------------------------------------
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy one or more projects — app code + merged runtime config msgpack.",
    )
    _add_workspace_arg(deploy_parser)
    _add_device_selector(deploy_parser)
    deploy_parser.add_argument(
        "names",
        nargs="*",
        metavar="name",
        help=(
            "Name of the project under projects/ to deploy.  Optional when "
            "the workspace contains exactly one project — that project is "
            "deployed by default.  One positional per `deploy` call; "
            "multi-project deploys are no longer supported."
        ),
    )
    deploy_parser.add_argument(
        "--entrypoint",
        default=None,
        help=(
            "Override the on-device entrypoint path.  Defaults to "
            "/code.py on CircuitPython and /main.py on MicroPython."
        ),
    )
    deploy_parser.add_argument(
        "--import-graph",
        action="store_true",
        help=(
            "AST-walk the entrypoint and ship only transitively-"
            "imported modules instead of the full project directory.  "
            "Reads workspace.yml's library_sources: for overrides.  "
            "Combines with --boot-shim to ship libraries alongside "
            "the boot-shim layout (walk starts from app.py)."
        ),
    )
    deploy_parser.add_argument(
        "--boot-shim",
        action="store_true",
        help=(
            "Ship project files at the device root + synthesise "
            "/code.py (CP) or /main.py (MP) that imports app.run.  "
            "app.py must export run().  Combines with --import-graph "
            "to also ship libraries the project imports.  Auto-detected "
            "when the project ships app.py with run() and no code.py / "
            "main.py — passing --boot-shim explicitly is rarely needed."
        ),
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the file map deploy would ship without writing to "
            "the device.  Doubles as documentation: the output is the "
            "canonical reference for 'what does deploy actually do'."
        ),
    )
    deploy_parser.add_argument(
        "--all-devices",
        action="store_true",
        help=(
            "Deploy to every device in devices.yml in sequence.  "
            "Mutually exclusive with --device / --runtime.  "
            "Per-device failures don't abort the loop — every device "
            "gets a chance, exit code reflects whether any failed."
        ),
    )
    deploy_parser.add_argument(
        "--all-projects",
        action="store_true",
        help=(
            "Deploy every project in workspace.yml's `deploy_targets:` "
            "mapping to its declared device(s).  Mutually exclusive "
            "with positional names / --device / --runtime / "
            "--all-devices.  Per-project failures don't abort the loop; "
            "exit code reflects whether any failed."
        ),
    )
    deploy_parser.add_argument(
        "--wipe",
        action="store_true",
        help=(
            "Erase the entire device filesystem before deploying.  "
            "Destructive — wipes user-managed files (settings.toml, "
            "uploaded assets, hand-edited boot.py) along with managed "
            "deploy scope.  Use for clean-slate / corruption-recovery "
            "flows; an ordinary deploy already cleans stale /lib/* "
            "files via the diff-deploy primitive.  No-op in RAM mode "
            "(nothing in flash to wipe)."
        ),
    )
    deploy_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Skip the recovery-coaching wrapper and let transport "
            "errors propagate uncaught.  Use in CI / scripted flows "
            "that don't have stdin to answer retry prompts.  "
            "Interactive coaching is on by default."
        ),
    )
    deploy_parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help=(
            "Skip the pre-deploy fast health gate.  By default, deploy "
            "runs `status`-equivalent checks (workspace.yml / "
            "devices.yml shape) and aborts on "
            "ERROR-level findings before sending bytes to the device. "
            "Use this flag for power-user CLI runs or CI flows that "
            "have already validated the workspace state externally."
        ),
    )
    deploy_parser.add_argument(
        "--target-runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Override the deploy-time runtime filter.  Defaults to "
            "the device's configured runtime — files marked for a "
            "different runtime via __chumicro_runtimes__ are filtered "
            "out.  Set this to override the auto-derived value."
        ),
    )
    deploy_parser.set_defaults(func=_cmd_deploy)

    # ----- projects --------------------------------------------------------
    projects_parser = subparsers.add_parser(
        "projects",
        help="List the projects defined under the workspace's projects/ tree.",
    )
    _add_workspace_arg(projects_parser)
    projects_parser.add_argument(
        "--flat",
        action="store_true",
        help=(
            "Print one slash-form path per line instead of the default "
            "tree view (handy for shell pipelines)."
        ),
    )
    projects_parser.set_defaults(func=_cmd_projects)

    # ----- status --------------------------------------------------------
    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Print a one-line-per-check workspace health snapshot "
            "(workspace.yml validity, devices.yml count, "
            "projects tree summary)."
        ),
    )
    _add_workspace_arg(status_parser)
    status_parser.set_defaults(func=_cmd_status)

    # ----- doctor --------------------------------------------------------
    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Strict sibling of `status` — adds Python version check "
            "and a per-project AST scan for `run()`."
        ),
    )
    _add_workspace_arg(doctor_parser)
    doctor_parser.set_defaults(func=_cmd_doctor)

    # ----- demo ----------------------------------------------------------
    demo_parser = subparsers.add_parser(
        "demo",
        help=(
            "Deploy a built-in 'hello world' payload to the active "
            "device.  Cross-runtime safe; ~5 seconds to run."
        ),
    )
    _add_workspace_arg(demo_parser)
    _add_device_selector(demo_parser)
    demo_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Skip the recovery-coaching wrapper and let transport "
            "errors propagate uncaught.  Use in CI / scripted flows."
        ),
    )
    demo_parser.set_defaults(func=_cmd_demo)

    # ----- bootstrap -----------------------------------------------------
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help=(
            "End-to-end onboarding wizard: pick a port, auto-probe "
            "the runtime, register the device, optionally deploy "
            "the demo payload.  All prompts are skippable via "
            "flags for non-interactive runs."
        ),
    )
    _add_workspace_arg(bootstrap_parser)
    bootstrap_parser.add_argument(
        "--port",
        default=None,
        help=(
            "Skip the interactive port pick — use this serial port "
            "path verbatim (e.g. '/dev/cu.usbmodem1101')."
        ),
    )
    bootstrap_parser.add_argument(
        "--device-id",
        dest="device_id",
        default=None,
        help=(
            "Skip the interactive device-id prompt — register the "
            "board under this id."
        ),
    )
    bootstrap_parser.add_argument(
        "--no-demo",
        dest="with_demo",
        action="store_false",
        default=True,
        help=(
            "Skip the built-in demo deploy at the end of the wizard.  "
            "Default behaviour is to chain into the demo so a freshly "
            "registered board ships *something* in one command — pass "
            "this flag in CI / scripted flows where you'll deploy your "
            "own payload next."
        ),
    )
    bootstrap_parser.set_defaults(func=_cmd_bootstrap)

    # ----- sim -----------------------------------------------------------
    sim_parser = subparsers.add_parser(
        "sim",
        help="Run a project in CPython simulation (planned, not yet shipped).",
    )
    _add_workspace_arg(sim_parser)
    sim_parser.set_defaults(func=_cmd_sim)

    # ----- test ----------------------------------------------------------
    test_parser = subparsers.add_parser(
        "test",
        help="Run pytest in the workspace root.  Extra args pass through.",
    )
    _add_workspace_arg(test_parser)
    test_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to pytest (place after `--`).",
    )
    test_parser.set_defaults(func=_cmd_test)

    # ----- lint ----------------------------------------------------------
    lint_parser = subparsers.add_parser(
        "lint",
        help="Run `ruff check` across the workspace.  Extra args pass through.",
    )
    _add_workspace_arg(lint_parser)
    lint_parser.add_argument(
        "ruff_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to ruff (place after `--`).",
    )
    lint_parser.set_defaults(func=_cmd_lint)

    # ----- preflight -----------------------------------------------------
    preflight_parser = subparsers.add_parser(
        "preflight",
        help=(
            "Run lint + tests as a single sanity gate (the same shape "
            "chumicro itself uses, scaled down for workspaces without "
            "CI).  Respects workspace.yml's `quality:` knobs."
        ),
    )
    _add_workspace_arg(preflight_parser)
    preflight_parser.set_defaults(func=_cmd_preflight)

    # ----- dump-config ---------------------------------------------------
    dump_config_parser = subparsers.add_parser(
        "dump-config",
        help=(
            "Print the merged runtime config a project would receive on "
            "deploy (workspace.yml defaults + per-project config "
            "deep-merged), without actually deploying."
        ),
    )
    _add_workspace_arg(dump_config_parser)
    dump_config_parser.add_argument(
        "project",
        help="Project name (bare / slash / dotted).",
    )
    dump_config_parser.add_argument(
        "--repr",
        action="store_true",
        help=(
            "Use repr() instead of JSON for the dump.  Useful when the "
            "raw Python types matter (e.g. distinguishing bytes vs str)."
        ),
    )
    dump_config_parser.set_defaults(func=_cmd_dump_config)

    # ----- repl ----------------------------------------------------------
    repl_parser = subparsers.add_parser(
        "repl",
        help=(
            "Interactive REPL on the selected board, or deploy a project "
            "and tail its output in one command."
        ),
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help=(
            "Optional project name (bare / slash / dotted).  When given, "
            "deploys the project first then enters tail mode for "
            "--tail SECONDS (default 30)."
        ),
    )
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode for SECONDS instead of the interactive "
            "TUI.  When a positional project is given, defaults to 30s."
        ),
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="Tail mode only: do not exit non-zero on a detected traceback.",
    )
    repl_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Skip the recovery-coaching wrapper around session-start "
            "errors (port-busy / port-not-found / permission-denied / "
            "raw-REPL-unresponsive).  With a positional project, also "
            "skips the wrapper around the deploy-then-tail flow.  "
            "Use in CI / scripted flows that can't answer retry "
            "prompts."
        ),
    )
    repl_parser.add_argument(
        "--mode",
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "Interactive REPL mode.  `line` (the better-featured "
            "default for terminal sessions) ships a host-side line "
            "editor with persistent history, `:edit` editor handoff, "
            "`:save`/`:load`/`:snippets`, and Tab completion against "
            "the on-device namespace.  `passthrough` forwards "
            "keystrokes byte-by-byte (mpremote-style — needed for "
            "raw REPL framing or paste mode).  `auto` (default) "
            "picks `line` when stdin is a TTY and `passthrough` "
            "otherwise.  No effect with `--tail` or with a "
            "positional project (those flows always use the tail "
            "follower)."
        ),
    )
    repl_parser.set_defaults(func=_cmd_repl)

    # ----- env -----------------------------------------------------------
    env_parser = subparsers.add_parser(
        "env",
        help="List / show workspace environments (planned).",
    )
    _add_workspace_arg(env_parser)
    env_parser.set_defaults(func=_cmd_env)

    # ----- use -----------------------------------------------------------
    use_parser = subparsers.add_parser(
        "use",
        help="Switch the active workspace environment (planned).",
    )
    _add_workspace_arg(use_parser)
    use_parser.set_defaults(func=_cmd_use)

    # ----- rename --------------------------------------------------------
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a project directory or a device id.",
    )
    _add_workspace_arg(rename_parser)
    rename_target = rename_parser.add_mutually_exclusive_group(required=True)
    rename_target.add_argument(
        "--project",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename projects/OLD/ to projects/NEW/.",
    )
    rename_target.add_argument(
        "--device",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename a devices.yml entry id (also rewrites defaults: references).",
    )
    rename_parser.set_defaults(func=_cmd_rename)

    # ----- install-firmware ----------------------------------------------
    install_firmware_parser = subparsers.add_parser(
        "install-firmware",
        help="Download + flash firmware onto the selected board.",
    )
    _add_workspace_arg(install_firmware_parser)
    _add_device_selector(install_firmware_parser)
    _add_firmware_args(install_firmware_parser)
    install_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- reset-board ----------------------------------------------------
    reset_board_parser = subparsers.add_parser(
        "reset-board",
        help=(
            "Wipe the device's user filesystem (clean-slate, no redeploy)."
        ),
        description=(
            "Erase every user file the runtime can see on the selected "
            "board — including out-of-scope files like settings.toml and "
            "hand-edited boot.py — without redeploying any project.  "
            "Standalone counterpart to `deploy --wipe`.  Used to recover "
            "a board whose flash filled up with stage residue (the "
            "MicroPython path runs `os.VfsLfs2.mkfs`, which `os.remove` "
            "alone cannot match — LittleFS metadata + wear-leveling "
            "artifacts survive a file-walk).  No-op in RAM / mount mode."
        ),
    )
    _add_workspace_arg(reset_board_parser)
    _add_device_selector(reset_board_parser)
    reset_board_parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Confirm the destructive wipe.  Without this flag, the "
            "command exits 2 without touching the board so a typoed "
            "device id cannot accidentally erase production state."
        ),
    )
    reset_board_parser.set_defaults(func=_cmd_reset_board)

    # ----- install-libraries ---------------------------------------------
    install_libraries_parser = subparsers.add_parser(
        "install-libraries",
        help=(
            "Install chumicro libraries the project imports onto the "
            "device via circup (CP) / mip (MP)."
        ),
        description=(
            "AST-walks PROJECT for chumicro_<name> imports and shells "
            "out to circup (CP) or mpremote-mip (MP) per device's "
            "runtime.  Regular-mode counterpart to dev-mode's "
            "library_sources auto-sync.  Use --dry-run to preview the "
            "exact commands without executing them."
        ),
    )
    _add_workspace_arg(install_libraries_parser)
    _add_device_selector(install_libraries_parser)
    install_libraries_parser.add_argument(
        "project",
        help=(
            "Project name (bare, slash, or dotted form).  Looked up "
            "across the workspace's projects/ tree."
        ),
    )
    install_libraries_parser.add_argument(
        "--experimental",
        action="store_true",
        help=(
            "Install from ChuMicro-Bundle-Experimental instead of "
            "ChuMicro-Bundle (stable, default)."
        ),
    )
    install_libraries_parser.add_argument(
        "--drive-path",
        default=None,
        help=(
            "CP only — explicit CIRCUITPY mount.  Pass when multiple "
            "CIRCUITPY drives are mounted so circup knows which one "
            "to install onto.  Ignored on MP."
        ),
    )
    install_libraries_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the commands that would run without executing them. "
            "Useful for air-gapped hosts or when reviewing what gets "
            "fetched before committing to the install."
        ),
    )
    install_libraries_parser.set_defaults(func=_cmd_install_libraries)

    # ----- upgrade-firmware ----------------------------------------------
    upgrade_firmware_parser = subparsers.add_parser(
        "upgrade-firmware",
        help="Alias of install-firmware — same flash flow.",
    )
    _add_workspace_arg(upgrade_firmware_parser)
    _add_device_selector(upgrade_firmware_parser)
    _add_firmware_args(upgrade_firmware_parser)
    upgrade_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- sync ----------------------------------------------------------
    sync_parser = subparsers.add_parser(
        "sync",
        help="Deprecated — superseded by `update`.",
    )
    _add_workspace_arg(sync_parser)
    sync_parser.set_defaults(func=_cmd_sync)

    # ----- upgrade -------------------------------------------------------
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Deprecated — superseded by `update --ref <ref>`.",
    )
    _add_workspace_arg(upgrade_parser)
    upgrade_parser.set_defaults(func=_cmd_upgrade)

    return parser


def _add_firmware_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared firmware-flash flags."""
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "Firmware download URL.  When omitted, the URL is "
            "derived from the device entry's hardware fields (CP: "
            "S3-bucket lookup; MP: curated machine→BOARD map; or "
            "hardware.firmware_source override)."
        ),
    )
    parser.add_argument(
        "--allow-prerelease",
        action="store_true",
        help=(
            "CP-only: include pre-release versions (-rc.0, -beta.1) "
            "when deriving the latest URL.  Stable-only by default."
        ),
    )
    parser.add_argument(
        "--method",
        choices=("uf2", "esptool"),
        required=True,
        help="Flash backend: uf2 for RP2040/RP2350, esptool for ESP32 family.",
    )
    parser.add_argument(
        "--bootloader-drive",
        dest="bootloader_drive_path",
        type=Path,
        default=None,
        help="uf2 path only: explicit bootloader drive mount.",
    )
    parser.add_argument(
        "--erase",
        action="store_true",
        help="esptool path only: erase-flash before write-flash.",
    )
    parser.add_argument(
        "--offset",
        default="0x0",
        help="esptool path only: write-flash offset (default 0x0).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when bootloader entry needs help.",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* and dispatch to the selected command.

    Returns the process exit code.  Stub commands return 2 so CI /
    scripts can distinguish "not implemented yet" from runtime errors.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
