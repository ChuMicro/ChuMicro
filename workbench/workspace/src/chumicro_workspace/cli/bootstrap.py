"""``bootstrap`` subcommand — end-to-end onboarding wizard.

Single user-visible flow that picks a port, runs runtime auto-detection,
prompts for a device id, writes ``devices.yml``, and optionally deploys
the built-in demo payload.  Each numbered step in the wizard has its
own helper so the dispatcher reads as a list of named phases.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_deploy.config.devices_yaml import (
    DeviceAlreadyExistsError,
    add_device,
    dump_devices,
    load_devices,
)
from serial.tools import list_ports

from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _emit_probe_failure,
    _hardware_from_probe_info,
    _resolve_workspace,
    _stdin_prompt,
)
from chumicro_workspace.cli.devices import _suggest_device_id
from chumicro_workspace.firmware_support import (
    FirmwareSupportStatus,
    check_firmware_supported,
)
from chumicro_workspace.firmware_support import (
    explain as explain_firmware_support,
)
from chumicro_workspace.onboarding import probe_with_runtime_inference
from chumicro_workspace.workspace import WorkspaceLayout

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import DeviceImplementation, DeviceInfo


# ---------------------------------------------------------------------------
# Step helpers (one per numbered phase in the wizard)
# ---------------------------------------------------------------------------


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
    ports = sorted(list_ports.comports(), key=lambda port: port.device)
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


def _bootstrap_probe(
    port: str, *, uf2_search_paths: tuple[Path, ...] | None,
) -> tuple[DeviceInfo, DeviceImplementation] | None:
    """Probe *port* with runtime auto-inference.

    Returns the resolved ``(info, implementation)`` pair on success or
    ``None`` after emitting failure diagnostics — caller turns that into
    a non-zero exit code.
    """
    print(f"bootstrap: probing {port} ...")
    inference = probe_with_runtime_inference(port)
    if inference.runtime is None or inference.info is None:
        _emit_probe_failure(
            "bootstrap",
            address=port,
            uf2_search_paths=uf2_search_paths,
            auto_detect_inference=inference,
        )
        return None

    info = inference.info
    implementation = info.implementation
    print(f"  runtime: {implementation.name} {implementation.version}")
    if implementation.machine:
        print(f"  machine: {implementation.machine}")
    return info, implementation


def _warn_if_firmware_unsupported(
    implementation: DeviceImplementation,
) -> None:
    """Print firmware-support warnings for OLD / UNKNOWN / UNPARSEABLE."""
    support = check_firmware_supported(implementation)
    if support.status is FirmwareSupportStatus.SUPPORTED:
        return
    print(
        f"  note: {implementation.name} firmware compatibility:",
        file=sys.stderr,
    )
    for line in explain_firmware_support(support):
        print(f"  {line}", file=sys.stderr)


def _register_bootstrap_device(
    workspace: WorkspaceLayout,
    *,
    device_id: str,
    port: str,
    info: DeviceInfo,
    implementation: DeviceImplementation,
) -> bool:
    """Write the probed device into ``devices.yml``.

    Returns ``True`` on success; ``False`` after printing the
    already-exists hint so the caller can exit non-zero.
    """
    data = load_devices(workspace.devices_yaml)
    try:
        add_device(
            data,
            device_id=device_id,
            runtime=implementation.name,
            address=port,
            hardware=_hardware_from_probe_info(info),
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
        return False
    dump_devices(data, workspace.devices_yaml)
    print(f"  registered {device_id} at {port}.")
    return True


def _maybe_run_demo(args: argparse.Namespace, device_id: str) -> int:
    """Run the demo deploy when ``--with-demo`` was passed; otherwise no-op.

    Local-import :func:`_cmd_demo` so this module is importable in any
    order during package init — the demo handler currently lives in
    ``cli/__init__.py`` and will move to ``cli/examples.py``; either
    home stays reachable via the package namespace.
    """
    if not args.with_demo:
        return 0
    from chumicro_workspace.cli import _cmd_demo  # noqa: PLC0415
    demo_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        device_id=device_id,
        runtime=None,
        non_interactive=False,
    )
    return _cmd_demo(demo_args)


def _print_bootstrap_next_steps() -> None:
    """Print the new / deploy / repl pointer block."""
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


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _cmd_bootstrap(
    args: argparse.Namespace,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> int:
    """Onboard a board end-to-end: pick → probe → register → demo.

    Single user-visible flow that ties port-pick + runtime-inference
    probe + device-registration + optional demo deploy together.  A
    user with a freshly-plugged board runs ``chumicro-workspace
    bootstrap`` and walks through:

    1. Pick a port.  When exactly one is detected, it's used
       silently; otherwise the wizard prints a numbered list and
       prompts.  ``--port <path>`` skips the pick.
    2. Probe with runtime auto-inference.  Failure prints the
       same diagnosis hints ``add-device`` does and exits 1.
    3. Display detected runtime + version + machine.  The
       firmware-support floor is checked; OLD / UNKNOWN /
       UNPARSEABLE statuses print a warning but don't abort.
    4. Pick a device id.  ``--device-id <id>`` skips the prompt.
       The default suggestion is derived from the probed machine
       string (e.g. ``"raspberry-pi-pico-w"``).
    5. Register the device in ``devices.yml`` — same write as
       ``add-device`` but no second probe.
    6. Optional ``--with-demo`` deploys the built-in demo payload
       so the user sees their board run code immediately.
    7. Print next-steps for the user (``new`` / ``deploy`` /
       ``repl``).

    Args:
        args: Parsed CLI args.  ``port``, ``device_id``, and
            ``with_demo`` are the wizard's three optional knobs.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.
    """
    workspace = _resolve_workspace(args)

    port = _resolve_bootstrap_port(args.port, prompt_func=prompt_func)
    if port is None:
        return 1

    probed = _bootstrap_probe(
        port, uf2_search_paths=args._env.uf2_search_paths,
    )
    if probed is None:
        return 1
    info, implementation = probed

    _warn_if_firmware_unsupported(implementation)

    suggested_id = _suggest_device_id(implementation)
    device_id = _resolve_bootstrap_device_id(
        args.device_id, suggested_id, prompt_func=prompt_func,
    )

    if not _register_bootstrap_device(
        workspace,
        device_id=device_id,
        port=port,
        info=info,
        implementation=implementation,
    ):
        return 1

    demo_exit = _maybe_run_demo(args, device_id)
    if demo_exit != 0:
        return demo_exit

    _print_bootstrap_next_steps()
    return 0


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_bootstrap_parser(subparsers: argparse._SubParsersAction) -> None:
    """``bootstrap`` — end-to-end onboarding wizard."""
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
            "Default behavior is to chain into the demo so a freshly "
            "registered board ships *something* in one command — pass "
            "this flag in CI / scripted flows where you'll deploy your "
            "own payload next."
        ),
    )
    bootstrap_parser.set_defaults(func=_cmd_bootstrap)
