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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from chumicro_deploy import (
    CircuitpythonTransportError,
    Deployer,
    Device,
    MicropythonTransportError,
    RecoveringDeployer,
    UnresolvedImportError,
)
from chumicro_deploy.config.default import load_devices_yml

from chumicro_workspace.boot_shim import (
    module_calls_hard_reset,
    project_app_exports_async_run,
    project_app_exports_run,
    project_boot_source,
    project_boot_with_import_graph_source,
    source_calls_hard_reset_at_top_level,
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
from chumicro_workspace.example_source import example_source
from chumicro_workspace.health import HealthLevel, collect_health_findings
from chumicro_workspace.import_graph import (
    project_import_graph_source,
    shared_import_hint,
)
from chumicro_workspace.workspace import (
    ProjectClassification,
    WorkspaceLayout,
)

#: Tail-window default (seconds) when ``deploy --tail`` is passed
#: without an explicit value.
_DEFAULT_TAIL_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Deploy-runner construction
# ---------------------------------------------------------------------------


def _make_deploy_runner(device: Any, *, non_interactive: bool) -> RecoveringDeployer:
    """Construct the deploy runner for a CLI command.

    Both modes surface the same coached recovery output and differ
    only in retry behavior:

    * ``non_interactive=True``: report once and re-raise (for CI and
      scripted flows where there is no stdin to prompt against).
    * ``non_interactive=False``: prompt to fix the condition and
      press Enter to retry (default ``max_attempts=3``).

    Caller invokes ``.deploy_diff()`` on the result.
    """
    deployer = Deployer(device)
    return RecoveringDeployer(
        deployer, prompt=None if non_interactive else input,
    )


# ---------------------------------------------------------------------------
# Deploy layout + plan resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ResolvedLayout:
    """Resolved deploy layout: boot-shim and import-graph flags.

    Returned by :func:`_resolve_deploy_layout` so the CLI dispatch
    has the final flag values without mutating ``args.boot_shim``
    or ``args.import_graph`` mid-flight (those represent what the
    *user* passed, and the resolver decides what to actually do).
    """

    boot_shim: bool
    import_graph: bool


@dataclass(frozen=True)
class ExampleSpec:
    """A library example resolved as a deploy payload.

    The example-specific payload :func:`resolve_project_deploy_source`
    branches on; the staging contract (one source owner, shared
    delete / keep policy) is stated there.

    Attributes:
        library_root: ``libraries/<lib>/``, the library that owns
            the example.
        example_name: Example filename stem (no trailing ``.py``).
        libraries_root: ``libraries/``, enumerated for the sibling
            ``src/`` search paths and manifest validation roots.
        extra_modules: Dotted module names to force-include past the
            AST walker (dynamic-import cases).
    """

    library_root: Path
    example_name: str
    libraries_root: Path
    extra_modules: list[str] | None = None


class _DeployLayoutError(Exception):
    """Raised by :func:`_resolve_deploy_layout` on shape / target mismatch.

    The instance's ``str`` is the user-facing multi-line message.
    """


class _DeployPlanError(Exception):
    """Raised by :func:`_build_deploy_plan` on input-validation failure.

    The instance's ``str`` is the user-facing message.
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
    # A microcontroller.reset() / machine.reset() in a shipped boot
    # entrypoint crash-loops the board: it resets on boot, reboots,
    # re-runs the entrypoint, and resets again, bricking the deploy cycle
    # until the board is wiped.  Refuse before any layout choice so a
    # stray reset can't ship.  app.py is the boot-shim entrypoint
    # (imported and run every boot); code.py / main.py are the plain-mode
    # entrypoints.
    # Scope: these three entrypoints get the strict scan (any reset,
    # even inside a function, since an entrypoint has no business
    # resetting).
    # The rest of the staged closure gets the top-level-only scan in
    # resolve_project_deploy_source, so an imported module may keep a
    # reset inside a deliberate-condition function but not at module
    # top level.  Aliased and from-import forms are matched by both.
    for entrypoint_name in ("code.py", "main.py", "app.py"):
        entrypoint_path = project_dir / entrypoint_name
        if not entrypoint_path.is_file():
            continue
        reset_line = module_calls_hard_reset(entrypoint_path)
        if reset_line is not None:
            raise _DeployLayoutError(
                f"project {project_dir.name!r} ships {entrypoint_name} with "
                f"a hard reset call (microcontroller.reset() / "
                f"machine.reset()) at line {reset_line}, which chumicro "
                f"refuses to deploy: a reset in the boot entrypoint reboots "
                f"the board on every boot, crash-looping it until you wipe "
                f"it.\n"
                f"  Fix: move the reset into a module the entrypoint imports "
                f"and calls only on a deliberate condition, never at boot in "
                f"{entrypoint_name}.",
            )

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

    # app.py defines `async def run`: the boot shim calls run()
    # synchronously, so an async run evaluates to a coroutine that is
    # never awaited.  The board would boot and do nothing, with no
    # traceback.  Reject it explicitly rather than ship a dead board,
    # and steer the user off async entirely (chumicro projects don't
    # use it anywhere).
    if project_app_exports_async_run(project_dir):
        raise _DeployLayoutError(
            f"project {project_dir.name!r} defines `async def run()` in "
            "app.py, which chumicro can't run: the boot shim calls "
            "run() synchronously, so an async run() becomes a coroutine "
            "that is never awaited, so the board boots and does nothing, "
            "with no error.\n"
            "  chumicro projects don't use async/await at all.  Make "
            "run() a plain `def run()` and drive long-running work with "
            "the tick-based runner pattern: each service exposes "
            "check(now_ms) / handle(now_ms) and the main loop stays a "
            "synchronous `while True:` (see chumicro_runner).",
        )

    # No runtime-specific entrypoint: try shim mode.
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


def resolve_project_deploy_source(*args, **kwargs):
    """Resolve the deploy layout + source, refusing boot-reachable resets.

    Wraps :func:`_resolve_project_deploy_source_unchecked` with the
    closure-wide hard-reset scan: every staged ``.py``'s module top
    level runs at boot, so a ``machine.reset()`` /
    ``microcontroller.reset()`` there crash-loops the board exactly
    like one in the entrypoint (which its own stricter scan already
    refuses).  Resets inside function bodies stay allowed, since that
    is the recommended deliberate-condition pattern.
    """
    layout, source = _resolve_project_deploy_source_unchecked(*args, **kwargs)
    for staged_path, content in source.files().items():
        if not staged_path.endswith(".py"):
            continue
        reset_line = source_calls_hard_reset_at_top_level(
            content.decode("utf-8", "replace"),
        )
        if reset_line is not None:
            raise _DeployLayoutError(
                f"staged module {staged_path!r} calls a board hard reset "
                f"(microcontroller.reset() / machine.reset()) at module "
                f"top level, line {reset_line}: top-level code runs on "
                f"every boot, so this crash-loops the board until it is "
                f"wiped.  Move the reset inside a function called only on "
                f"a deliberate condition.",
            )
    return layout, source


def _resolve_project_deploy_source_unchecked(
    *,
    workspace: WorkspaceLayout,
    device: Device,
    project_dir: Path | None = None,
    example: ExampleSpec | None = None,
    user_boot_shim: bool = False,
    user_import_graph: bool = False,
    user_entrypoint: str | None = None,
    target_runtime: str | None = None,
) -> tuple[str, object]:
    """Resolve ``(layout_label, FileSource)`` for a deploy.

    Both ``deploy`` and ``deploy-example`` route through this function
    so a project and a library example stage onto the device under the
    same delete / keep policy.  Only the inner payload differs.
    ``deploy`` passes a *project_dir* plus its ``--boot-shim`` /
    ``--import-graph`` / ``--entrypoint`` / ``--target-runtime`` flags.
    ``deploy-example`` passes an *example* spec.

    Exactly one of *project_dir* / *example* must be given.

    Raises:
        ValueError: Neither or both of *project_dir* / *example*.
        _DeployLayoutError: project shape doesn't match the target
            runtime's entrypoint convention.  Callers surface the
            instance's str as the user-facing message.  A malformed
            project is refused identically on every path, never
            silently shipped as a library-less boot deploy.
        FileNotFoundError, ValueError: forwarded from
            :func:`example_source` for a malformed example (callers
            classify these as a precheck failure).
    """
    if (project_dir is None) == (example is None):
        raise ValueError(
            "resolve_project_deploy_source needs exactly one of "
            "project_dir / example",
        )
    target = target_runtime or str(device.transport)
    if example is not None:
        library_roots = sorted(
            path
            for path in example.libraries_root.iterdir()
            if path.is_dir()
        )
        return "example", example_source(
            example.library_root,
            example.example_name,
            library_roots=library_roots,
            runtime=target,
            secrets_toml=workspace.secrets_toml,
            extra_modules=example.extra_modules,
        )
    layout_choice = _resolve_deploy_layout(
        project_dir=project_dir,
        target_entrypoint=device.effective_entrypoint,
        user_passed_boot_shim=user_boot_shim,
        user_passed_import_graph=user_import_graph,
    )
    if layout_choice.boot_shim and layout_choice.import_graph:
        return "boot-shim+import-graph", project_boot_with_import_graph_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
            target_runtime=target,
        )
    if layout_choice.boot_shim:
        return "boot-shim", project_boot_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
            target_runtime=target,
        )
    if layout_choice.import_graph:
        device_entrypoint = user_entrypoint or f"/{device.effective_entrypoint}"
        return "import-graph", project_import_graph_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
            device_entrypoint=device_entrypoint,
            target_runtime=target,
        )
    return "flat", project_directory_source(
        project_dir,
        secrets_toml=workspace.secrets_toml,
        entrypoint=(user_entrypoint or f"/{device.effective_entrypoint}"),
        target_runtime=target,
    )


def _build_deploy_plan(
    workspace: WorkspaceLayout, args: argparse.Namespace,
) -> list[tuple[str, Path, list[Device]]]:
    """Resolve the (project, devices) pairs ``deploy`` will iterate.

    Three input shapes:

    * ``--all-projects``: walks ``workspace.yml``'s ``deploy_targets``
      mapping, one tuple per (project, devices-it-targets) pair.
    * Positional name + ``--all-devices``: one tuple targeting every
      device in ``devices.yml``.
    * Positional name (or default-when-only-one-project): one tuple
      whose device list is the user's ``--device`` / ``--runtime``
      choice.  When no per-deploy override is passed, the project's
      ``deploy_targets`` entry is consulted, falling through to the
      workspace's ``devices.yml`` default.

    Raises:
        _DeployPlanError: Input validation failed.  The str payload is
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

    Single-project default uses :func:`project_directory_source`, the
    flat layout where the project's files land at the device root.
    ``--import-graph`` ships only transitively-imported modules.
    ``--boot-shim`` ships project files at the device root plus a
    synthesised ``/code.py`` (CP) or ``/main.py`` (MP) that imports
    the project's ``app.run``.  Auto-detected when the project ships
    ``app.py`` + ``run()`` and no runtime-specific entrypoint.

    Positional name accepts bare (``"door_open"``), slash
    (``"garage/sensors/door_open"``), or dotted forms.  Bare names that
    match more than one project in the tree exit 2 with a list of
    candidates.

    When invoked with no positional name and the workspace contains
    exactly one project, that project is deployed by default, covering
    the "I only have one app" beginner case.  Zero projects or
    multiple projects both require an explicit positional.

    Multi-project deploys (``deploy <a> <b> <c>``) are not supported.
    Pass one positional per ``deploy`` call.
    """
    workspace = _resolve_workspace(args)

    # Auto-detect non-interactive from stdin TTY so a piped / CI run skips
    # the coaching prompts instead of blocking on input() (matches
    # deploy-example); an explicit --non-interactive always wins.
    non_interactive = args.non_interactive or not sys.stdin.isatty()

    # Pre-deploy fast health gate.  Catches the user-visible failure
    # modes that *would* deploy but ship junk to the device (missing
    # workspace.yml, malformed devices.yml, etc.).  Skips the slower
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

    if args.tail is not None:
        target_count = sum(len(devices) for _n, _d, devices in deploy_plan)
        if target_count != 1:
            print(
                "deploy: --tail follows one board's output, so it needs "
                "exactly one (project, device) target; this plan resolves "
                f"to {target_count}.  Drop --tail, or narrow to a single "
                "project and --device.",
                file=sys.stderr,
            )
            return 2

    exit_code = 0
    tail_target: Device | None = None
    for project_name, project_dir, devices in deploy_plan:
        if len(deploy_plan) > 1:
            print(f"\ndeploy: === {project_name} ===")
        for device in devices:
            if len(devices) > 1 or len(deploy_plan) > 1:
                print(
                    f"deploy: --- {device.transport}@{device.address} ---",
                )
            # A CLI mode override applies to this run only; the
            # persistent setting stays in devices.yml.  Must land
            # before layout resolution, which is mode-dependent.
            requested_mode = args.force_deploy_mode or args.deploy_mode
            if requested_mode is not None and requested_mode != device.deploy_mode:
                device = replace(device, deploy_mode=requested_mode)
            # Source policy (layout resolution + the four source
            # factories) lives in one owner; no command places a
            # project on a board by another route.
            # `--target-runtime` overrides the device's runtime;
            # `_resolve_deploy_layout` raises on a project/runtime
            # entrypoint mismatch before any bytes leave the host.
            try:
                layout, source = resolve_project_deploy_source(
                    project_dir=project_dir,
                    workspace=workspace,
                    device=device,
                    user_boot_shim=args.boot_shim,
                    user_import_graph=args.import_graph,
                    user_entrypoint=args.entrypoint,
                    target_runtime=args.target_runtime,
                )
            except _DeployLayoutError as layout_error:
                print(f"deploy: {layout_error}", file=sys.stderr)
                exit_code = 2
                continue
            except UnresolvedImportError as import_error:
                # The import-graph walk found a module that resolves to no
                # deployed file; refuse before sending bytes rather than
                # ship an import that would ImportError at first boot.
                # Print the refusal cleanly (it would otherwise dump a raw
                # traceback), and when the missing module is a mis-spelled
                # shared/ import, append the bare-name fix.
                print(f"deploy: {import_error}", file=sys.stderr)
                hint = shared_import_hint(import_error.unresolved)
                if hint is not None:
                    print(f"  hint: {hint}", file=sys.stderr)
                exit_code = 2
                continue
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
            try:
                result = _make_deploy_runner(
                    device, non_interactive=non_interactive,
                ).deploy_diff(
                    source,
                    clean=args.clean,
                    wipe=args.wipe,
                    on_file_deleted=deleted.append,
                    force_deploy_mode=args.force_deploy_mode,
                )
            except (CircuitpythonTransportError, MicropythonTransportError) as deploy_error:
                # RecoveringDeployer already printed the coached recovery
                # (and, interactively, offered a retry); in non-interactive
                # mode it re-raises.  Absorb that here so a physical-layer
                # failure exits cleanly instead of dumping a traceback, and
                # continue so the remaining devices in a multi-device deploy
                # still get their turn.
                print(
                    f"deploy: {device.transport}@{device.address}: {deploy_error}",
                    file=sys.stderr,
                )
                exit_code = 1
                continue
            for stale_path in deleted:
                print(f"deploy: removed stale {stale_path}")
            if result.execute_output:
                print(result.execute_output, end="")
            if not result.success:
                _emit_failure_hints(result)
                exit_code = 1
            else:
                tail_target = device

    if args.tail is not None and tail_target is not None and exit_code == 0:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            tail_target,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
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
    which skip ``_template`` and leading ``.`` / ``_`` names.
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
    """``deploy``: the workspace's main command.  Single project per call."""
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy one or more projects: app code + merged runtime config msgpack.",
    )
    _add_workspace_arg(deploy_parser)
    _add_device_selector(deploy_parser)
    deploy_parser.add_argument(
        "names",
        nargs="*",
        metavar="name",
        help=(
            "Name of the project under projects/ to deploy.  Optional when "
            "the workspace contains exactly one project; that project is "
            "deployed by default.  One positional per `deploy` call."
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
            "main.py, so passing --boot-shim explicitly is rarely needed."
        ),
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the file map deploy would ship without writing to "
            "the device.  Doubles as documentation: the output is the "
            "reference for 'what does deploy actually do'."
        ),
    )
    deploy_parser.add_argument(
        "--all-devices",
        action="store_true",
        help=(
            "Deploy to every device in devices.yml in sequence.  "
            "Mutually exclusive with --device / --runtime.  "
            "Per-device failures don't abort the loop: every device "
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
        "--no-wipe",
        dest="clean",
        action="store_false",
        default=True,
        help=(
            "Additive mode: reconcile only the entrypoint / state "
            "files + /lib, leaving every other board file "
            "(settings.toml, uploaded assets, hand-installed circup "
            "libs) in place.  The default is clean-slate: the deploy "
            "removes anything that isn't the new payload or a "
            "device-required keep-set file (boot.py, boot_out.txt, "
            "_chu_kv.msgpack); a board-resident settings.toml is "
            "evicted (it competes with config-driven wifi).  Use "
            "--no-wipe only when you deliberately hand-manage board "
            "files."
        ),
    )
    deploy_parser.add_argument(
        "--wipe",
        action="store_true",
        help=(
            "Erase the *entire* device filesystem before deploying, "
            "the keep set (boot.py, boot_out.txt, _chu_kv.msgpack) "
            "included.  Stricter than the clean-slate default (which "
            "preserves the keep set); for corruption recovery.  No-op "
            "in RAM mode (nothing in flash to wipe)."
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
            "the device's configured runtime; files marked for a "
            "different runtime via __chumicro_runtimes__ are filtered "
            "out.  Set this to override the auto-derived value."
        ),
    )
    deploy_mode_group = deploy_parser.add_mutually_exclusive_group()
    deploy_mode_group.add_argument(
        "--deploy-mode",
        choices=("ram", "flash"),
        default=None,
        help=(
            "Override the device's deploy_mode for this run only.  The "
            "requires_flash pre-flight still applies: a project that "
            "imports a flagged library auto-promotes ram -> flash and "
            "prints why.  The devices.yml deploy_mode field is the "
            "persistent form of this setting."
        ),
    )
    deploy_mode_group.add_argument(
        "--force-deploy-mode",
        choices=("ram", "flash"),
        default=None,
        help=(
            "Set the mode for this run AND bypass the requires_flash "
            "pre-flight: `ram` stays ram even when a flagged library "
            "is in the import graph.  For debugging the auto-switch "
            "behavior itself; prefer --deploy-mode otherwise."
        ),
    )
    deploy_parser.add_argument(
        "--tail",
        nargs="?",
        type=float,
        const=_DEFAULT_TAIL_SECONDS,
        default=None,
        metavar="SECONDS",
        help=(
            "After a successful deploy, tail the board's serial output "
            f"for SECONDS (default {_DEFAULT_TAIL_SECONDS:g} when the "
            "value is omitted), then exit.  Replaces the old "
            "`repl <project>` deploy-then-watch shortcut: one deploy "
            "path, the watch is a flag on it.  Requires exactly one "
            "(project, device) target."
        ),
    )
    deploy_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help=(
            "With --tail: do not exit non-zero when a traceback is "
            "detected in the tailed output."
        ),
    )
    deploy_parser.set_defaults(func=_cmd_deploy)


def _add_projects_parser(subparsers: argparse._SubParsersAction) -> None:
    """``projects``: list workspace projects (tree or flat view)."""
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
