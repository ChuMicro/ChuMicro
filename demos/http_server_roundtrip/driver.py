"""Host-side driver for the http_server_roundtrip demo.

Picks a registered device, deploys ``app.py`` via
:func:`chumicro_workspace.deploy_api.deploy_project`, and fires HTTP
requests against the routes the board advertises (``GET /hello``,
``GET /uptime``, ``POST /echo``), printing each response as it lands.

Run: ``.venv/bin/python demos/http_server_roundtrip/driver.py``
By default targets the first CircuitPython device in ``devices.yml``;
pass ``--device <id>`` or ``--runtime micropython`` to override.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chumicro_pytest_device.fixtures.host_driver import bind_to
from chumicro_workspace.deploy_api import (
    DeployApiError,
    DeviceNotFoundError,
    deploy_project,
)
from chumicro_workspace.markers import MarkerTimeoutError

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]


def _format_body(body: bytes) -> str:
    """Pretty-print the response body: JSON when valid, repr otherwise."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return repr(body)
    return json.dumps(parsed, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the http_server_roundtrip demo against a registered board."
        ),
    )
    parser.add_argument(
        "--device", default=None,
        help="device id from devices.yml (default: first matching --runtime)",
    )
    parser.add_argument(
        "--runtime", default=None,
        choices=("circuitpython", "micropython"),
        help=(
            "runtime filter: when --device isn't given, picks the "
            "first matching device (default: circuitpython)"
        ),
    )
    parser.add_argument(
        "--ready-timeout-s", type=float, default=60.0,
        help="seconds to wait for SERVER_READY from the board",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=90.0,
        help="seconds to wait for the bootstrap to finish after the round trip",
    )
    args = parser.parse_args(argv)

    try:
        session = deploy_project(
            project_dir=_DEMO_DIR,
            device_id=args.device,
            runtime=args.runtime,
            deploy_mode="flash",
            workspace_root=_REPO_ROOT,
        )
    except DeviceNotFoundError as device_error:
        print(f"driver: {device_error}", file=sys.stderr)
        return 2
    except DeployApiError as deploy_error:
        print(f"driver: {deploy_error}", file=sys.stderr)
        return 2

    print(
        f"driver: targeting {session.device_entry.identifier} "
        f"({session.device_entry.runtime} @ {session.device_entry.address})",
    )

    try:
        hit = bind_to(session.runner)

        print(
            f"driver: waiting for SERVER_READY (up to "
            f"{args.ready_timeout_s}s)...",
        )
        try:
            hello_response = hit("/hello", timeout_s=args.ready_timeout_s)
        except MarkerTimeoutError as marker_error:
            print(
                f"driver: SERVER_READY didn't arrive within "
                f"{args.ready_timeout_s}s.  The board may still be booting, "
                f"wifi credentials in secrets.toml may be wrong, or the "
                f"board can't reach the AP.  Detail: {marker_error}",
                file=sys.stderr,
            )
            return 2
        print(
            f"driver: GET /hello -> {hello_response.status} "
            f"{hello_response.reason}\n{_format_body(hello_response.body)}",
        )

        uptime_response = hit("/uptime", timeout_s=10.0)
        print(
            f"driver: GET /uptime -> {uptime_response.status} "
            f"{uptime_response.reason}\n{_format_body(uptime_response.body)}",
        )

        echo_payload = b'{"from": "demo driver"}'
        echo_response = hit(
            "/echo", timeout_s=10.0, method="POST", body=echo_payload,
        )
        print(
            f"driver: POST /echo -> {echo_response.status} "
            f"{echo_response.reason}\n{_format_body(echo_response.body)}",
        )

        print("driver: waiting for board to print DEMO_COMPLETE...")
        # The board keeps serving after the third route, like any board
        # program does, so wait on the marker rather than on the process
        # finishing.  session.shutdown() in the finally tears it down.
        try:
            session.wait_for(
                "DEMO_COMPLETE", timeout_s=args.completion_timeout_s,
            )
        except MarkerTimeoutError as completion_error:
            print(
                f"driver: board didn't print DEMO_COMPLETE within "
                f"{args.completion_timeout_s}s: {completion_error}",
                file=sys.stderr,
            )
            return 3
        print("driver: demo completed cleanly.")
        return 0
    finally:
        session.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
