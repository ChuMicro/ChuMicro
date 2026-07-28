"""Shared helpers used across multiple ``chumicro-workspace`` subcommands.

Workspace + device resolution, common argparse argument-attach helpers,
probe + deploy-failure formatters, and the ``--dry-run`` summary
renderer.  Subcommand modules under :mod:`chumicro_workspace.cli`
import from here.

Kept private.  The underscore-prefixed names are an internal contract
between the CLI submodules and are re-exported from
:mod:`chumicro_workspace.cli` for the test suite's benefit only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chumicro_deploy import Device
from chumicro_deploy.config.default import load_devices_yml, load_devices_yml_raw
from chumicro_deploy.config.devices_yaml import (
    list_device_ids,
    load_devices,
)
from serial.tools import list_ports

from chumicro_workspace.onboarding import (
    RuntimeInferenceResult,
    detect_board_state,
)
from chumicro_workspace.recovery import detect_hints, format_hints
from chumicro_workspace.workspace import (
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    from chumicro_deploy import DeviceInfo


# ---------------------------------------------------------------------------
# Common argparse helpers
# ---------------------------------------------------------------------------


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--workspace-dir`` flag.

    Defaults to walking up from the current working directory until a
    ``workspace.yml`` is found, matching ``git``'s discovery shape.
    Override when running multiple workspaces in parallel or when the
    user invokes the CLI from outside the tree (CI runners, IDE tasks).
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


def _add_non_interactive_arg(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--non-interactive`` flag.

    Tells the command to skip user prompts and recovery-coaching
    wrappers, failing fast with a distinct exit code instead.
    Auto-detected from stdin TTY status when omitted; CI / agent
    callers pass it explicitly to guarantee no interactive blocking.
    """
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Skip prompts and recovery-coaching wrappers and fail fast "
            "with a distinct exit code.  Auto-detected from stdin TTY "
            "status; pass explicitly for CI / scripted runs."
        ),
    )


# ---------------------------------------------------------------------------
# Workspace + device resolution
# ---------------------------------------------------------------------------


def _resolve_workspace(args: argparse.Namespace) -> WorkspaceLayout:
    """Locate the workspace root for *args*.

    Wraps :class:`WorkspaceLayout.from_dir` so missing workspaces
    surface as a ``SystemExit`` instead of a stack trace.
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

    Thin policy wrapper over
    :func:`chumicro_deploy.config.default.load_devices_yml_raw`.  That
    function does the ``--device id`` / ``--runtime`` /
    single-default resolution.  This wrapper adds the workspace-side
    None-on-miss policy (``install-firmware`` treats a missing entry
    as "fall back to --url", not an error).  Returns the raw entry
    dict for ``hardware`` / ``firmware_source`` access (those keys
    aren't on the :class:`Device` dataclass) or ``None``.
    """
    if not workspace.devices_yaml.is_file():
        return None
    # Preserve the original precedence: an explicit id wins and
    # suppresses the runtime hint, so the two never collide into
    # load_devices_yml_raw's mutual-exclusion error.
    device_id = args.device_id
    runtime = None if device_id is not None else getattr(args, "runtime", None)
    try:
        return load_devices_yml_raw(
            workspace.devices_yaml, device_id=device_id, runtime=runtime,
        )
    except (ValueError, FileNotFoundError):
        return None


def _resolve_device(workspace: WorkspaceLayout, args: argparse.Namespace) -> Device:
    """Construct a :class:`Device` for the selected entry in devices.yml.

    A missing, empty, or otherwise unresolvable ``devices.yml`` exits
    with a coached one-line message instead of letting
    ``load_devices_yml``'s ``ValueError`` reach the user as a traceback
    (a fresh workspace materializes an empty ``devices: []`` file, so the
    empty case is the common one, not a corner case).
    """
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found; run "
            "'add-device' to register a board first.",
        )
    try:
        return load_devices_yml(
            workspace.devices_yaml,
            device_id=args.device_id,
            runtime=args.runtime,
        )
    except ValueError as error:
        raise SystemExit(
            f"error: {error}; run 'add-device' to register a board, "
            "or pass --device <id> to pick a registered one.",
        ) from error


def _resolve_all_devices(workspace: WorkspaceLayout) -> list[Device]:
    """Return a :class:`Device` for every entry in devices.yml.

    Used by ``deploy --all-devices``.  Loads each entry via
    :func:`load_devices_yml` so the per-entry validation +
    runtime-default resolution stays consistent with single-device
    deploys.  Order matches the YAML file order so deploys reach
    boards in a predictable sequence.
    """
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found; run "
            "'add-device' to register a board first.",
        )
    device_ids = list_device_ids(load_devices(workspace.devices_yaml))
    if not device_ids:
        raise SystemExit(
            f"error: {workspace.devices_yaml} has no devices to deploy to.",
        )
    return [
        load_devices_yml(workspace.devices_yaml, device_id=device_id)
        for device_id in device_ids
    ]


# ---------------------------------------------------------------------------
# Probe + deploy failure formatting
# ---------------------------------------------------------------------------


def _emit_probe_failure(
    command_name: str,
    *,
    address: str,
    transport: str = "micropython",
    uf2_search_paths: list[Path] | None,
    auto_detect_inference: RuntimeInferenceResult | None = None,
    probe_exception: BaseException | None = None,
) -> None:
    """Emit the standard probe-failure block for *command_name* to stderr.

    Writes a header line stating the cause, followed by indented
    next-step hints from
    :func:`~chumicro_workspace.onboarding.detect_board_state`.

    Pass exactly one of *auto_detect_inference* or *probe_exception*.
    Their text differs (``auto-detect failed`` vs ``probe failed``)
    but the diagnosis appended below is the same.

    The diagnostic probe runs under *transport* (defaults to
    ``"micropython"``).  The transport choice rarely matters on the
    probe-already-failed path because :func:`detect_board_state`
    falls back to UF2 and error-string heuristics regardless.
    """
    diagnosis = detect_board_state(
        Device(transport=transport, address=address),
        uf2_search_paths=uf2_search_paths,
    )
    if probe_exception is not None:
        print(
            f"{command_name}: probe failed "
            f"({type(probe_exception).__name__}: {probe_exception}).",
            file=sys.stderr,
        )
    elif (
        auto_detect_inference is not None
        and auto_detect_inference.last_exception is not None
    ):
        exception = auto_detect_inference.last_exception
        print(
            f"{command_name}: auto-detect failed "
            f"({type(exception).__name__}: {exception}).",
            file=sys.stderr,
        )
    else:
        print(
            f"{command_name}: auto-detect failed: "
            "no runtime returned a probe marker.",
            file=sys.stderr,
        )
    for line in diagnosis.next_steps:
        print(f"  {line}", file=sys.stderr)


def _hardware_from_probe_info(info: DeviceInfo) -> dict[str, str] | None:
    """Build the ``hardware:`` dict for a fresh devices.yml entry from *info*.

    Picks the three hardware-once fields the probe knows about (uid,
    machine, board_id) and returns ``None`` (not an empty dict) when
    none are populated so :func:`chumicro_deploy.add_device`'s
    "no hardware section" branch fires cleanly.
    """
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if info.implementation and info.implementation.machine:
        hardware["machine"] = info.implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id
    return hardware or None


def _emit_failure_hints(deploy_result: Any) -> None:
    """Print the traceback + matching app-level recovery hints to stderr.

    The deploy result's ``traceback`` and ``execute_output`` are
    both scanned for known patterns from
    :mod:`chumicro_workspace.recovery`.  Any matching hints append
    below the traceback under a "--- hints ---" section so users who
    hit a common failure (missing config key, library not installed)
    get the workspace-shaped pointer instead of just the raw stdlib
    error.

    Skip the hints section silently when no pattern matches.
    Showing an empty block reads worse than showing nothing.
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


# ---------------------------------------------------------------------------
# Dry-run rendering
# ---------------------------------------------------------------------------


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


def _classify_dry_run_path(path: str) -> str:
    """Return a one-word category for *path* in the deploy file map.

    Drives the right-column annotation of ``deploy --dry-run`` so
    the reader can scan "what's shim infrastructure vs my code"
    without parsing paths by eye.

    The classifier still returns ``shim`` for ``/code.py`` and
    ``/main.py`` even when those are user-owned in plain mode,
    since they're always the firmware entrypoint, regardless of who
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
        category = _classify_dry_run_path(path)
        lines.append(f"  {path.ljust(path_width)}  {size}  {category}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def _stdin_prompt(prompt_text: str) -> str:
    """Return ``input(prompt_text)``.

    Routed through a named helper so interactive subcommands can inject
    a deterministic substitute under test instead of monkey-patching
    the builtin.
    """
    return input(prompt_text)


def _resolve_serial_port(
    explicit_port: str | None,
    *,
    command_name: str = "add-device",
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> str | None:
    """Pick the serial port to operate on.

    * ``explicit_port`` set: use it verbatim.
    * No ports detected: print a hint to stderr, return ``None``.
    * Exactly one port: use it without prompting.
    * Multiple ports: list them, prompt for a number.

    Args:
        explicit_port: ``--address`` / ``--port`` flag value, or
            ``None`` to discover interactively.
        command_name: Prefix used in the user-facing log lines so
            output reads as the calling subcommand's voice.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.

    Returns:
        The chosen port path, or ``None`` on no-discovery / invalid
        input.  Caller turns ``None`` into a non-zero exit code.
    """
    if explicit_port:
        return explicit_port
    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print(
            f"{command_name}: no serial ports detected.  "
            "Plug in a board and try again.",
            file=sys.stderr,
        )
        return None
    if len(ports) == 1:
        only_port = ports[0]
        print(f"{command_name}: only one port found, using {only_port.device}.")
        return only_port.device
    print(f"{command_name}: pick a board:")
    for index, port in enumerate(ports, start=1):
        description = port.description or "(no description)"
        print(f"  [{index}] {port.device}  {description}")
    raw_choice = prompt_func(f"  Pick [1-{len(ports)}]: ")
    try:
        chosen_index = int(raw_choice.strip())
    except ValueError:
        print(
            f"{command_name}: invalid choice {raw_choice!r}",
            file=sys.stderr,
        )
        return None
    if chosen_index < 1 or chosen_index > len(ports):
        print(
            f"{command_name}: choice {chosen_index} out of range",
            file=sys.stderr,
        )
        return None
    return ports[chosen_index - 1].device


# ---------------------------------------------------------------------------
# Project-name resolution (shared by deploy / deploy-example / config / rename)
# ---------------------------------------------------------------------------


def _resolve_project_name(workspace: WorkspaceLayout, name: str) -> str:
    """Resolve a user-typed project name to a canonical slash-form path.

    Accepts three shapes:

    * **Bare** (``"door_open"``): looked up across the whole
      ``projects/`` tree.  A unique match returns that project.
      Multiple matches raise ``SystemExit`` listing the candidates.
      No match returns *name* unchanged, and the caller's existence
      check surfaces the ``FileNotFoundError``-shaped message.
    * **Slash** (``"garage/sensors/door_open"``): direct path.
    * **Dotted** (``"garage.sensors.door_open"``): same as slash,
      normalized before return because ``/`` is the standard form
      used by :meth:`WorkspaceLayout.list_projects`.
    """
    normalized = name.replace(".", "/")
    if "/" in normalized:
        return normalized
    candidates = [
        path for path in workspace.list_projects()
        if path == name or path.endswith("/" + name)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        candidate_list = "\n".join(f"  {path}" for path in candidates)
        raise SystemExit(
            f"deploy: {name!r} is ambiguous.  Multiple projects match:\n"
            f"{candidate_list}\n"
            f"specify the path: `python3 run.py deploy {candidates[0]}`",
        )
    # No match: let the caller's existence check produce the standard
    # "project not found" message after constructing the dir path.
    return name
