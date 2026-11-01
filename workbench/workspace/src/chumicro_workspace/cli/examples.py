"""``demo`` and ``deploy-example`` subcommands.

``demo`` ships a baked-in cross-runtime print-loop payload to the
active device, giving a freshly-registered board something to run on
day one.  ``deploy-example`` is the front-door command for shipping
a library example (``libraries/<lib>/examples/<name>.py``) and
tailing its output, with distinct exit codes per failure class so
agents and CI runners can branch without parsing stderr.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from chumicro_deploy import Device, FileMapSource
from chumicro_deploy.recovery import DeployFailureKind, classify_deploy_failure
from chumicro_deploy.runtime_marker import read_runtime_marker

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _emit_failure_hints,
    _resolve_device,
    _resolve_workspace,
)
from chumicro_workspace.cli.bootstrap import _cmd_bootstrap
from chumicro_workspace.cli.deploy import (
    ExampleSpec,
    _make_deploy_runner,
    resolve_project_deploy_source,
)
from chumicro_workspace.workspace import WorkspaceLayout, runner_invocation

# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------


#: Built-in demo payload: a ``while True`` loop that prints a count
#: once a second until the board loses power, the shape every first
#: board program has.
#:
#: Cross-runtime safe (CircuitPython + MicroPython): only ``time.sleep``
#: and ``print``.  No hardware access, so every supported board reaches
#: the print path identically and the demo runs without runtime-config
#: or pin pickers.
DEMO_PAYLOAD: str = (
    "import time\n"
    "\n"
    "print('Hello from ChuMicro!')\n"
    "print('Your board is alive. It counts once a second until you unplug it.')\n"
    "\n"
    "count = 0\n"
    "while True:\n"
    "    count += 1\n"
    "    print('  tick ' + str(count))\n"
    "    time.sleep(1)\n"
)


def _cmd_demo(args: argparse.Namespace) -> int:
    """Deploy :data:`DEMO_PAYLOAD` to the active device and print its first output.

    Gives a user with a freshly-registered board something to ship
    on day one without having to write code, configure wifi, or pick
    a project.  The deploy captures the first ten seconds of output,
    prints it, and returns while the board keeps counting.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
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
    ).deploy_diff(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        _emit_failure_hints(result)
        return 1
    device_flag = f" --device {args.device_id}" if args.device_id else ""
    print(
        "demo: the board keeps counting.  Watch it with "
        f"`{runner_invocation(workspace.root)} repl --tail 30{device_flag}`.",
    )
    return 0


# ---------------------------------------------------------------------------
# deploy-example: front-door command for running a library example on a board
# ---------------------------------------------------------------------------


#: Distinct exit codes for `chumicro-workspace deploy-example` so agents
#: and CI runners can branch on the code without parsing stderr.  The
#: codes are a stable contract.  Adding a new one is safe, renumbering an
#: existing one is a breaking change.
DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED = 2
DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED = 3
DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED = 4
DEPLOY_EXAMPLE_EXIT_WIZARD_CANCELLED = 5
DEPLOY_EXAMPLE_EXIT_NO_PYTHON_RUNTIME = 6


def _list_examples(libraries_root: Path, library_name: str | None) -> int:
    """Print every available example under ``libraries/[<lib>/]examples/``.

    With *library_name* set, prints only that library's examples.
    Without, prints every library's set.  Examples list as
    ``<lib>/<example_stem>`` so the user can pass either form to
    ``deploy-example`` later.
    """
    if not libraries_root.is_dir():
        print(
            f"deploy-example --list: {libraries_root} not found.  "
            "deploy-example expects a libraries/ directory under the "
            "workspace root.",
            file=sys.stderr,
        )
        return DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
    targets = (
        [libraries_root / library_name]
        if library_name
        else sorted(
            path for path in libraries_root.iterdir() if path.is_dir()
        )
    )
    found = 0
    for library_dir in targets:
        examples_dir = library_dir / "examples"
        if not examples_dir.is_dir():
            continue
        for example in sorted(examples_dir.glob("*.py")):
            print(f"{library_dir.name}/{example.stem}")
            found += 1
    if found == 0:
        if library_name:
            print(
                f"deploy-example --list: no examples under "
                f"{libraries_root / library_name}/examples/",
                file=sys.stderr,
            )
        else:
            print(
                f"deploy-example --list: no examples found under "
                f"{libraries_root}/*/examples/",
                file=sys.stderr,
            )
        return DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
    return 0


def _resolve_deploy_example_modes(args: argparse.Namespace) -> tuple[bool, bool]:
    """Resolve the ``(non_interactive, tail)`` mode pair for deploy-example.

    TTY auto-detection sets the default.  Explicit ``--non-interactive``
    / ``--no-tail`` flags override.

    Returns:
        ``(non_interactive, should_tail)``.  ``should_tail`` is
        always ``False`` when ``non_interactive`` is ``True``, because
        long-running tail processes are inherently interactive.
    """
    if args.non_interactive:
        non_interactive = True
    else:
        non_interactive = not sys.stdin.isatty()
    if non_interactive:
        return True, False
    # Interactive default: tail unless --no-tail.
    should_tail = args.tail
    return False, should_tail


def _print_no_device_hint(
    workspace_root: Path,
    runtime_required: str | None,
) -> None:
    """Print the structured stderr hint for the no-device-registered case.

    Non-interactive shape: emit a deterministic stderr hint and let the
    caller (agent / CI runner) read exit code 3 to follow the hint and
    register a device explicitly.
    """
    runtime = runtime_required or "circuitpython"
    invocation = runner_invocation(workspace_root)
    print(
        f"deploy-example: no {runtime} device registered.\n"
        f"  to register:    {invocation} add-device "
        f"<id> --address <port> --runtime {runtime}\n"
        f"  to list ports:  {invocation} discover\n"
        f"  rerun without --non-interactive for the registration wizard.",
        file=sys.stderr,
    )


class _DeployExampleError(Exception):
    """Raised by deploy-example stage helpers; caller prints + returns the code.

    Carries both the user-facing message (str payload) and the distinct
    exit code (``DEPLOY_EXAMPLE_EXIT_*``) so the dispatcher catches once
    at the top and returns the right code instead of threading "result
    or exit-code" tuples through every stage.
    """

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class _DeployExamplePaths:
    """Validated paths for a deploy-example invocation.

    *example_path* is ``libraries/<lib>/examples/<stem>.py``; *library_root*
    is ``libraries/<lib>/`` (the parent that owns it).  *stem* is the
    example filename without the trailing ``.py``.
    """

    library_root: Path
    example_path: Path
    stem: str


def _resolve_library_dir(libraries_root: Path, name: str) -> Path | None:
    """Resolve a deploy-example library argument to its directory.

    Accepts either the import-name form a workspace lands acquired
    libraries under (``chumicro_mqtt``) or the bare short name (``mqtt``):
    a workspace holds ``libraries/chumicro_<name>/`` while the mono-repo
    uses ``libraries/<name>/``, so both are tried.  Returns the directory,
    or ``None`` when neither exists.
    """
    candidate = libraries_root / name
    if candidate.is_dir():
        return candidate
    if not name.startswith("chumicro_"):
        prefixed = libraries_root / f"chumicro_{name}"
        if prefixed.is_dir():
            return prefixed
    return None


def _resolve_deploy_example_paths(
    libraries_root: Path, args: argparse.Namespace,
) -> _DeployExamplePaths:
    """Validate that the requested library + example actually exist."""
    if not args.library:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            "library positional required "
            "(use --list to discover available libraries).",
        )
    if not args.example_name:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            "example positional required "
            "(use --list <lib> to see available examples).",
        )
    library_root = _resolve_library_dir(libraries_root, args.library)
    if library_root is None:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            f"library {args.library!r} not found under {libraries_root}.",
        )
    stem = (
        args.example_name[:-3]
        if args.example_name.endswith(".py")
        else args.example_name
    )
    example_path = library_root / "examples" / f"{stem}.py"
    if not example_path.is_file():
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            f"example file {example_path} not found.",
        )
    return _DeployExamplePaths(
        library_root=library_root, example_path=example_path, stem=stem,
    )


def _resolve_example_runtime_required(
    marker: tuple[str, ...] | None, args: argparse.Namespace,
) -> str | None:
    """Decide which runtime the example mandates.

    * None marker / no constraint → returns None (universal example, fall
      through to whatever the device runs).
    * Single-runtime marker → returns that runtime.
    * Multi-runtime marker → ``--runtime`` wins if it's in the set.  An
      explicit ``--device <id>`` defers the decision to the device-resolve
      step (returns None).  Neither flag with a multi-runtime marker is
      ambiguous, so raise the precheck error.
    """
    if marker is None:
        return None
    if len(marker) == 1:
        (runtime_required,) = marker
        return runtime_required
    if args.runtime and args.runtime in marker:
        return args.runtime
    if args.device_id is None:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            f"example targets multiple runtimes ({sorted(marker)}); "
            "pass --runtime to disambiguate.",
        )
    return None


def _resolve_deploy_example_device(
    workspace: WorkspaceLayout,
    args: argparse.Namespace,
    *,
    runtime_required: str | None,
    non_interactive: bool,
) -> Device:
    """Resolve a Device for the deploy-example invocation.

    Falls into the bootstrap wizard when no device is registered and the
    mode allows it (interactive + ``--auto-register``).  Raises
    :class:`_DeployExampleError` on the non-interactive / opt-out cases
    and on wizard cancellation.
    """
    runtime_filter = (
        None if args.device_id is not None else (runtime_required or args.runtime)
    )
    device_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        device_id=args.device_id,
        runtime=runtime_filter,
    )
    try:
        return _resolve_device(workspace, device_args)
    except (SystemExit, ValueError, FileNotFoundError):
        # devices.yml missing / unloadable / no matching entry: route
        # to the wizard fallback below.  ``_resolve_device`` raises
        # ``SystemExit`` for the missing-file path and forwards
        # ``ValueError`` / ``FileNotFoundError`` from
        # ``load_devices_yml`` for parse + lookup failures.
        pass

    if non_interactive or not args.auto_register:
        _print_no_device_hint(workspace.root, runtime_required)
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED, "",
        )
    # ``_cmd_bootstrap`` delegates to ``add-device``, so the Namespace
    # has to carry that command's whole attribute set.  ``id`` /
    # ``address`` / ``runtime`` stay None so the wizard picks the port
    # and auto-detects the runtime, same as a bare ``bootstrap`` run.
    bootstrap_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        id=None,
        address=None,
        runtime=None,
        description=None,
        force=False,
        demo=False,  # don't double up; we deploy the example next
        non_interactive=False,  # only the interactive path lands here
        _env=args._env,
    )
    if _cmd_bootstrap(bootstrap_args) != 0:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_WIZARD_CANCELLED, "",
        )
    try:
        return _resolve_device(workspace, device_args)
    except SystemExit as exception:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED, "",
        ) from exception


def _validate_example_runtime_matches_device(
    *,
    device_runtime: str,
    runtime_required: str | None,
    marker: tuple[str, ...] | None,
) -> None:
    """Cross-check the device's runtime against the example's marker."""
    if runtime_required and device_runtime != runtime_required:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            f"example requires {runtime_required} but selected device "
            f"runs {device_runtime}.  Pass --device <id> or --runtime "
            f"{runtime_required} to pick a matching board.",
        )
    if marker is not None and device_runtime not in marker:
        raise _DeployExampleError(
            DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
            f"example targets {sorted(marker)} but selected device runs "
            f"{device_runtime}.  Pick a compatible board with --device <id>.",
        )


def _cmd_deploy_example(args: argparse.Namespace) -> int:
    """Deploy a library example to a registered device.

    Front-door command for running ``libraries/<lib>/examples/<name>.py``
    on a board.  Handles four first-touch board states (no device
    registered, happy path, no Python runtime / Arduino, port
    unreachable) and supports both interactive (TTY-detected, falls
    into the bootstrap wizard on missing device) and
    ``--non-interactive`` (CI / agent-friendly, fails fast with
    structured stderr hints) modes.

    Exit codes (distinct so agents and CI runners can branch on the
    code without parsing stderr):

    * 0: Deploy succeeded.
    * 2: Precheck failed (file missing, runtime mismatch, missing
      config key).
    * 3: No device registered for runtime, ``--no-auto-register`` in
      effect (or non-interactive default).
    * 4: Deploy failed (transport error, recovery hints on stderr).
    * 5: Bootstrap wizard canceled by user (interactive mode only).
    * 6: ``NO_PYTHON_RUNTIME``: board has Arduino or unknown firmware.
    """
    workspace = _resolve_workspace(args)
    libraries_root = workspace.root / "libraries"

    # --list short-circuits everything else.
    if args.list:
        return _list_examples(libraries_root, args.library)

    non_interactive, should_tail = _resolve_deploy_example_modes(args)

    try:
        paths = _resolve_deploy_example_paths(libraries_root, args)
        marker = read_runtime_marker(paths.example_path)
        runtime_required = _resolve_example_runtime_required(marker, args)
        device = _resolve_deploy_example_device(
            workspace, args,
            runtime_required=runtime_required,
            non_interactive=non_interactive,
        )
        device_runtime = str(device.transport)
        _validate_example_runtime_matches_device(
            device_runtime=device_runtime,
            runtime_required=runtime_required,
            marker=marker,
        )
        target_runtime = runtime_required or device_runtime
        # The example stages through the one source owner +
        # clean-slate primitive every project deploy uses; only the
        # inner payload is example-specific.
        try:
            _layout, source = resolve_project_deploy_source(
                workspace=workspace,
                device=device,
                example=ExampleSpec(
                    library_root=paths.library_root,
                    example_name=paths.stem,
                    libraries_root=libraries_root,
                ),
                target_runtime=target_runtime,
            )
        except (FileNotFoundError, ValueError) as build_error:
            raise _DeployExampleError(
                DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
                f"precheck failed: {build_error}",
            ) from build_error
    except _DeployExampleError as error:
        if str(error):
            print(f"deploy-example: {error}", file=sys.stderr)
        return error.exit_code

    print(
        f"deploy-example: deploying {args.library}/{paths.stem} → "
        f"{device.transport} @ {device.address} ...",
    )

    # Wrap in the recovery-coaching deployer.  Non-interactive mode
    # re-raises after printing; interactive prompts to retry.
    runner = _make_deploy_runner(device, non_interactive=non_interactive)
    deleted: list[str] = []
    try:
        result = runner.deploy_diff(
            source,
            clean=args.clean,
            wipe=args.wipe,
            on_file_deleted=deleted.append,
            tail_seconds=args.tail_seconds,
        )
    except Exception as deploy_error:  # noqa: BLE001 - classify + route
        kind = classify_deploy_failure(deploy_error)
        if kind is DeployFailureKind.NO_PYTHON_RUNTIME:
            return DEPLOY_EXAMPLE_EXIT_NO_PYTHON_RUNTIME
        return DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED
    for stale_path in deleted:
        print(f"deploy-example: removed stale {stale_path}")

    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        _emit_failure_hints(result)
        return DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED

    if should_tail:
        # Optional REPL drop, interactive mode only.  Opens an
        # interactive serial REPL against the device so the user can
        # follow the example's output and press Ctrl-D to exit.
        print("deploy-example: dropping into chumicro-repl ...")
        try:
            from chumicro_repl.cli import main as repl_main  # noqa: PLC0415
            return repl_main(["--address", str(device.address)])
        except ImportError:
            print(
                "deploy-example: chumicro-repl not installed; skipping "
                "tail.  Install with `pip install chumicro-repl`.",
                file=sys.stderr,
            )
    return 0


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_demo_parser(subparsers: argparse._SubParsersAction) -> None:
    """``demo``: deploy the built-in payload."""
    demo_parser = subparsers.add_parser(
        "demo",
        help="Send the board a counting program to check that it works.",
        description=(
            "Copy a small program to the board that prints 'Hello from "
            "ChuMicro!' and then counts once a second for as long as the "
            "board has power.  The command shows the first output and "
            "leaves the program running.  The program uses no pins, so "
            "it runs on any CircuitPython or MicroPython board.  The "
            "next deploy replaces it."
        ),
    )
    _add_workspace_arg(demo_parser)
    _add_device_selector(demo_parser)
    _add_non_interactive_arg(demo_parser)
    demo_parser.set_defaults(func=_cmd_demo)


def _add_deploy_example_parser(subparsers: argparse._SubParsersAction) -> None:
    """``deploy-example``: front-door for the first-touch board flow."""
    deploy_example_parser = subparsers.add_parser(
        "deploy-example",
        help="Copy one library example onto a board and show its output.",
        description=(
            "Copy libraries/<library>/examples/<example>.py onto the "
            "board as its startup file, together with the libraries it "
            "imports, then restart the board.  On a terminal, the "
            "command then opens the board's prompt so the output keeps "
            "scrolling.  Ctrl-X leaves the prompt.  With no board registered, "
            "the command first runs the bootstrap steps.  Networked "
            "examples read WiFi settings from secrets.toml.  Exit codes: "
            "2 a check failed before copying, 3 no board is registered, "
            "4 the deploy failed, 5 board setup was cancelled, 6 the "
            "board runs neither CircuitPython nor MicroPython."
        ),
    )
    _add_workspace_arg(deploy_example_parser)
    deploy_example_parser.add_argument(
        "library",
        nargs="?",
        default=None,
        help=(
            "Library folder under libraries/, such as timing.  "
            "chumicro_timing works too.  Optional with --list."
        ),
    )
    deploy_example_parser.add_argument(
        "example_name",
        nargs="?",
        default=None,
        metavar="example",
        help=(
            "Example file under libraries/<library>/examples/, such as "
            "circuitpython_blink.  The .py ending is optional."
        ),
    )
    deploy_example_parser.add_argument(
        "--list",
        action="store_true",
        help=(
            "List the examples as library/example and exit.  Give a "
            "library name to list only its examples."
        ),
    )
    _add_device_selector(deploy_example_parser)
    _add_non_interactive_arg(deploy_example_parser)
    deploy_example_parser.add_argument(
        "--no-auto-register",
        dest="auto_register",
        action="store_false",
        default=True,
        help=(
            "With no board registered for the example's runtime, exit 3 "
            "and print the add-device command to run, in place of "
            "starting board setup."
        ),
    )
    tail_group = deploy_example_parser.add_mutually_exclusive_group()
    tail_group.add_argument(
        "--tail",
        dest="tail",
        action="store_true",
        default=True,
        help=(
            "After the deploy, open the board's prompt so its output "
            "keeps scrolling.  On by default on a terminal.  "
            "--non-interactive turns it off."
        ),
    )
    tail_group.add_argument(
        "--no-tail",
        dest="tail",
        action="store_false",
        help="Exit right after the deploy.",
    )
    deploy_example_parser.add_argument(
        "--no-wipe",
        dest="clean",
        action="store_false",
        default=True,
        help=(
            "Remove old files only from /lib/ and the startup and "
            "settings files.  Other files on the board stay, such as "
            "settings.toml or images you copied over.  The default "
            "removes every file this deploy does not copy, except "
            "boot.py, boot_out.txt, and _chu_kv.msgpack."
        ),
    )
    deploy_example_parser.add_argument(
        "--wipe",
        action="store_true",
        help=(
            "Erase the board's whole filesystem before copying, "
            "boot.py, boot_out.txt, and _chu_kv.msgpack included.  Use "
            "it to recover a board whose files are corrupted."
        ),
    )
    deploy_example_parser.add_argument(
        "--tail-seconds",
        type=float,
        default=None,
        help=(
            "Seconds of output to capture right after the restart, on a "
            "CircuitPython board in flash mode.  MicroPython boards "
            "ignore it.  Defaults to 10.  Raise it for a board whose "
            "first output comes late, such as a Pi Pico W joining WiFi.  "
            "0 returns as soon as the board restarts and leaves it "
            "running."
        ),
    )
    deploy_example_parser.set_defaults(func=_cmd_deploy_example)
