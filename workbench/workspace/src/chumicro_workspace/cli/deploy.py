"""``deploy`` + ``projects`` subcommands.

Resolves which project / device pairs to ship to, picks the deploy
layout from project shape, and dispatches to the right
``chumicro_workspace`` source builder.  Project listing
(``projects --flat`` or the indented Unicode tree) lives alongside
because it shares :class:`WorkspaceLayout` walks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chumicro_deploy import (
    Deployer,
    Device,
    InteractiveDeployer,
    NonInteractiveDeployer,
)
from chumicro_deploy.config.default import load_devices_yml

from chumicro_workspace.boot_shim import (
    project_app_exports_async_run,
    project_app_exports_run,
    project_boot_source,
    project_boot_with_import_graph_source,
)
from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _emit_failure_hints,
    _render_dry_run_summary,
    _resolve_all_devices,
    _resolve_device,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.deploy_source import project_directory_source
from chumicro_workspace.deploy_targets import read_deploy_targets
from chumicro_workspace.health import HealthLevel, collect_health_findings
from chumicro_workspace.import_graph import project_import_graph_source
from chumicro_workspace.workspace import (
    ProjectClassification,
    WorkspaceLayout,
)

# ---------------------------------------------------------------------------
# Deploy-runner construction
# ---------------------------------------------------------------------------


def _make_deploy_runner(device: Any, *, non_interactive: bool) -> Any:
    """Construct the deploy runner for a CLI command.

    Returns one of two :class:`chumicro_deploy._RecoveringDeployer`
    subclasses depending on whether the CLI has stdin to prompt
    against.  Both surface the same coached recovery output (failure
    classification, F6 lsof diagnosis when applicable, canonical
    fix steps) — they differ only in whether they retry on
    retryable failures:

    * ``non_interactive=True`` → :class:`NonInteractiveDeployer`.
      Prints the report once and re-raises.  CI / scripted flows
      where the retry prompt has nowhere to go.
    * ``non_interactive=False`` → :class:`InteractiveDeployer`.
      Prompts the user to fix the condition and press Enter to
      retry (default ``max_attempts=3``).

    Returns the runner; caller invokes ``.deploy()`` or
    ``.deploy_diff()`` as needed (both signatures match
    :class:`Deployer`'s exactly).
    """
    deployer = Deployer(device)
    if non_interactive:
        return NonInteractiveDeployer(deployer)
    return InteractiveDeployer(deployer)


# ---------------------------------------------------------------------------
# Deploy layout + plan resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ResolvedLayout:
    """Resolved deploy layout — boot-shim and import-graph flags.

    Returned by :func:`_resolve_deploy_layout` so the CLI dispatch
    has the final flag values without mutating ``args.boot_shim``
    or ``args.import_graph`` mid-flight (those represent what the
    *user* passed; the resolver decides what to actually do).
    """

    boot_shim: bool
    import_graph: bool


class _DeployLayoutError(Exception):
    """Raised by :func:`_resolve_deploy_layout` on shape / target mismatch.

    The instance's ``str`` is the multi-line user-facing message; the
    caller in :func:`_cmd_deploy` prints it to stderr and continues to
    the next project / device with exit code 2.
    """


class _DeployPlanError(Exception):
    """Raised by :func:`_build_deploy_plan` on input-validation failure.

    The instance's ``str`` is the user-facing message; the caller in
    :func:`_cmd_deploy` prints it to stderr and returns 2.
    """


def _resolve_deploy_layout(
    *,
    project_dir: Path,
    target_entrypoint: str,
    user_passed_boot_shim: bool,
    user_passed_import_graph: bool,
) -> _ResolvedLayout:
    """Resolve the deploy layout for *project_dir* against *target_entrypoint*.

    When the user passed an explicit ``--boot-shim`` or
    ``--import-graph`` flag, those wins are preserved verbatim.
    Otherwise the layout is auto-detected from the project's shape:

    Decision matrix:

        code.py     main.py     app.py:run()   target   →  result
        ----------  ----------  -------------  -------     ----------
        Yes         *           *              CP          plain
        *           Yes         *              MP          plain
        Yes         No          *              MP          USER ERROR
        No          Yes         *              CP          USER ERROR
        No          No          Yes            any         shim+import
        No          No          No             any         USER ERROR

    Raises:
        _DeployLayoutError: Project shape doesn't match the target
            runtime's entrypoint convention.  The instance's str is
            the actionable user-facing message.
    """
    if user_passed_boot_shim or user_passed_import_graph:
        # User-specified flags win; auto-detect is a no-op.
        return _ResolvedLayout(
            boot_shim=user_passed_boot_shim,
            import_graph=user_passed_import_graph,
        )

    has_code_py = (project_dir / "code.py").is_file()
    has_main_py = (project_dir / "main.py").is_file()
    has_app_run = project_app_exports_run(project_dir)

    target_is_cp = target_entrypoint == "code.py"
    target_is_mp = target_entrypoint == "main.py"

    # Plain deploy when the runtime-matching entrypoint is present.
    if (target_is_cp and has_code_py) or (target_is_mp and has_main_py):
        return _ResolvedLayout(boot_shim=False, import_graph=False)

    # Wrong-runtime entrypoint present: user intended this project
    # for the *other* runtime and targeted the wrong board.  Surface
    # as a clear error rather than silently shimming around it.
    if target_is_mp and has_code_py and not has_main_py:
        raise _DeployLayoutError(
            f"project {project_dir.name!r} has code.py "
            "(CircuitPython entrypoint) but you targeted a MicroPython "
            "board.\n"
            "  Fix: rename code.py → main.py for MicroPython, or "
            "deploy --runtime circuitpython.",
        )
    if target_is_cp and has_main_py and not has_code_py:
        raise _DeployLayoutError(
            f"project {project_dir.name!r} has main.py "
            "(MicroPython entrypoint) but you targeted a CircuitPython "
            "board.\n"
            "  Fix: rename main.py → code.py for CircuitPython, or "
            "deploy --runtime micropython.",
        )

    # app.py defines `async def run` — the boot shim calls run()
    # synchronously, so an async run evaluates to a coroutine that is
    # never awaited: the board would boot and do nothing, with no
    # traceback.  Reject it explicitly rather than ship a dead board,
    # and steer the user off async entirely — chumicro projects don't
    # use it anywhere.
    if project_app_exports_async_run(project_dir):
        raise _DeployLayoutError(
            f"project {project_dir.name!r} defines `async def run()` in "
            "app.py, which chumicro can't run: the boot shim calls "
            "run() synchronously, so an async run() becomes a coroutine "
            "that is never awaited — the board boots and does nothing, "
            "with no error.\n"
            "  chumicro projects don't use async/await at all.  Make "
            "run() a plain `def run()` and drive long-running work with "
            "the tick-based runner pattern: each service exposes "
            "check(now_ms) / handle(now_ms) and the main loop stays a "
            "synchronous `while True:` (see chumicro_runner).",
        )

    # No runtime-specific entrypoint — try shim mode.
    if has_app_run:
        return _ResolvedLayout(boot_shim=True, import_graph=True)

    # Nothing to dispatch on.
    app_py_present = (project_dir / "app.py").is_file()
    app_clause = (
        "app.py present but has no top-level run() callable"
        if app_py_present
        else "no app.py with run() callable"
    )
    raise _DeployLayoutError(
        f"project {project_dir.name!r} has no entrypoint "
        "chumicro-deploy can use:\n"
        "  - no code.py at the project root (CircuitPython entrypoint)\n"
        "  - no main.py at the project root (MicroPython entrypoint)\n"
        f"  - {app_clause} (boot-shim mode requires app.py to "
        "export run())\n"
        "\n"
        "  Fix: name your script code.py (CP) or main.py (MP), OR\n"
        "       wrap your top-level code in `def run(): ...` in app.py.",
    )


def _build_deploy_plan(
    workspace: WorkspaceLayout, args: argparse.Namespace,
) -> list[tuple[str, Path, list[Device]]]:
    """Resolve the (project, devices) pairs ``deploy`` will iterate.

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

    Raises:
        _DeployPlanError: Input validation failed — the str payload is
            the actionable user-facing message.
    """
    if args.all_projects:
        if (
            args.names
            or args.device_id is not None
            or args.runtime is not None
            or args.all_devices
        ):
            raise _DeployPlanError(
                "--all-projects is mutually exclusive with positional "
                "names / --device / --runtime / --all-devices.",
            )
        targets = read_deploy_targets(workspace.workspace_yaml)
        if not targets:
            raise _DeployPlanError(
                "--all-projects requires a `deploy_targets:` block "
                f"in {workspace.workspace_yaml.name}.  Map each project to "
                "one or more device ids and re-run.",
            )
        plan: list[tuple[str, Path, list[Device]]] = []
        for project_path, device_ids in targets.items():
            project_dir = workspace.project_dir(project_path)
            if not project_dir.is_dir():
                raise _DeployPlanError(
                    f"deploy_targets references unknown project "
                    f"{project_path!r} (no projects/{project_path}/ directory).",
                )
            try:
                project_devices = [
                    load_devices_yml(workspace.devices_yaml, device_id=did)
                    for did in device_ids
                ]
            except (FileNotFoundError, ValueError) as error:
                raise _DeployPlanError(
                    f"deploy_targets[{project_path!r}]: {error}",
                ) from error
            plan.append((project_path, project_dir, project_devices))
        return plan

    # Positional / default project resolution.
    if not args.names:
        candidates = workspace.list_projects()
        if not candidates:
            raise _DeployPlanError(
                "no projects to deploy.  Create one with `new <name>` first.",
            )
        if len(candidates) > 1:
            raise _DeployPlanError(
                "multiple projects in workspace; specify which "
                f"to deploy ({', '.join(candidates)}).",
            )
        project_name = candidates[0]
        print(f"deploy: defaulting to {project_name} (only project in workspace).")
    else:
        if len(args.names) > 1:
            raise _DeployPlanError(
                "multi-project deploys are no longer supported — "
                "pass one positional name per `deploy` call.",
            )
        project_name = _resolve_project_name(workspace, args.names[0])
    project_dir = workspace.project_dir(project_name)
    if not project_dir.is_dir():
        raise SystemExit(f"error: project {project_dir} not found")

    if args.all_devices:
        if args.device_id is not None or args.runtime is not None:
            raise _DeployPlanError(
                "--all-devices is mutually exclusive with --device / --runtime.",
            )
        return [(project_name, project_dir, _resolve_all_devices(workspace))]

    # Default-from-mapping: when the user passed neither --device nor
    # --runtime, consult workspace.yml's deploy_targets[project] before
    # falling back to devices.yml's defaults block.  Lets a workspace
    # owner with multiple boards stop typing --device for every deploy.
    if args.device_id is None and args.runtime is None:
        targets = read_deploy_targets(workspace.workspace_yaml)
        mapped = targets.get(project_name)
        if mapped:
            try:
                mapped_devices = [
                    load_devices_yml(workspace.devices_yaml, device_id=did)
                    for did in mapped
                ]
            except (FileNotFoundError, ValueError) as error:
                raise _DeployPlanError(
                    f"deploy_targets[{project_name!r}]: {error}",
                ) from error
            return [(project_name, project_dir, mapped_devices)]
    return [(project_name, project_dir, [_resolve_device(workspace, args)])]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


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

    Multi-project deploys (``deploy <a> <b> <c>``) are not supported;
    pass one positional per ``deploy`` call.
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

    try:
        deploy_plan = _build_deploy_plan(workspace, args)
    except _DeployPlanError as plan_error:
        print(f"deploy: {plan_error}", file=sys.stderr)
        return 2

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
            # Resolve deploy layout from project shape + user flags.
            # Project shape determines the auto-detected mode:
            #
            # * ``code.py`` at root    → plain (CP entrypoint, user-owned).
            # * ``main.py`` at root    → plain (MP entrypoint, user-owned).
            # * ``app.py`` with run()  → boot-shim + import-graph (deploy
            #   synthesises ``/code.py`` or ``/main.py`` and ships imported
            #   libraries from ``library_sources`` and ``shared/``).
            # * Runtime mismatch (e.g. ``code.py`` only, but target is MP)
            #   surfaces as a user error before any bytes leave the host.
            try:
                layout_choice = _resolve_deploy_layout(
                    project_dir=project_dir,
                    target_entrypoint=device.effective_entrypoint,
                    user_passed_boot_shim=args.boot_shim,
                    user_passed_import_graph=args.import_graph,
                )
            except _DeployLayoutError as layout_error:
                print(f"deploy: {layout_error}", file=sys.stderr)
                exit_code = 2
                continue

            if layout_choice.boot_shim and layout_choice.import_graph:
                layout = "boot-shim+import-graph"
                source = project_boot_with_import_graph_source(
                    project_dir,
                    workspace=workspace,
                    entrypoint_filename=device.effective_entrypoint,
                    target_runtime=target_runtime,
                )
            elif layout_choice.boot_shim:
                layout = "boot-shim"
                source = project_boot_source(
                    project_dir,
                    workspace=workspace,
                    entrypoint_filename=device.effective_entrypoint,
                    target_runtime=target_runtime,
                )
            elif layout_choice.import_graph:
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
                    secrets_toml=workspace.secrets_toml,
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


# ---------------------------------------------------------------------------
# Projects listing
# ---------------------------------------------------------------------------


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

    Two views: the default :func:`_render_projects_tree` draws an
    indented Unicode tree so namespaced workspaces are legible at
    a glance; ``--flat`` falls back to the one-project-per-line
    slash-form output (handy for shell pipelines and ``grep``-style
    filtering).

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


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_deploy_parser(subparsers: argparse._SubParsersAction) -> None:
    """``deploy`` — the workspace's central command.  Single project per call."""
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
    _add_non_interactive_arg(deploy_parser)
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


def _add_projects_parser(subparsers: argparse._SubParsersAction) -> None:
    """``projects`` — list workspace projects (tree or flat view)."""
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
