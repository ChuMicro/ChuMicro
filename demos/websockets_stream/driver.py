"""Host-side driver for the websockets_stream demo.

Runs a WebSocket server on the host's LAN IP that, on each connection,
streams a few text messages then closes, built on
``chumicro_websockets.WebSocketServer`` itself (CPython), so the demo
exercises both ends of the library.  Deploys the board's ``app.py`` via
:func:`chumicro_workspace.deploy_api.deploy_project` with the server URL
baked into the runtime_config payload, then waits for the board's
marker sequence to confirm it received the whole stream.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from chumicro_pytest_device.fixtures.lan import detect_lan_ip
from chumicro_runner import Runner
from chumicro_sockets import listener as make_listener
from chumicro_websockets import WebSocketServer
from chumicro_workspace.deploy_api import (
    DeployApiError,
    DeviceNotFoundError,
    deploy_project,
)
from chumicro_workspace.markers import MarkerTimeoutError

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]

_STREAM_MESSAGE_COUNT = 3


def _start_stream_server(bind_host: str):
    """Start a host WebSocket server that streams then closes; return (port, stop).

    Each accepted connection gets ``_STREAM_MESSAGE_COUNT`` text
    messages followed by a clean close.  The server is driven by a
    plain tick loop on a daemon thread (host-side, so a 10 ms poll is
    fine).  The board uses the efficient ``runner.wait`` path.
    """
    listener = make_listener(bind_host, 0)
    port = listener.getsockname()[1]

    def on_connection(connection):
        for sequence in range(1, _STREAM_MESSAGE_COUNT + 1):
            connection.send_text(f"stream message {sequence}")
        connection.close()

    server = WebSocketServer(listener, on_connection)
    stop_event = threading.Event()

    def run():
        def report_fault(entry, error):
            print(f"driver: SERVICE_FAULT {entry.service!r} {error!r}", file=sys.stderr)

        runner = Runner(on_handler_error=report_fault)
        runner.add(server)
        while not stop_event.is_set():
            runner.tick()
            time.sleep(0.01)
        server.close()

    threading.Thread(target=run, daemon=True).start()
    return port, stop_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--wifi-timeout-s", type=float, default=45.0,
        help="seconds to wait for the board WIFI_OK marker",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=30.0,
        help="seconds to wait for STREAM_CLOSED after WS_CONNECTING",
    )
    args = parser.parse_args(argv)

    lan_ip = detect_lan_ip()
    if lan_ip is None:
        print(
            "driver: could not detect a LAN IP for the WebSocket server.  "
            "Is wifi up on the host?",
            file=sys.stderr,
        )
        return 1

    port, stop_event = _start_stream_server(lan_ip)
    stream_url = f"ws://{lan_ip}:{port}/"
    print(f"driver: websocket stream server up at {stream_url}")

    session = None
    try:
        try:
            session = deploy_project(
                project_dir=_DEMO_DIR,
                device_id=args.device,
                runtime=args.runtime,
                deploy_mode="flash",
                extra_runtime_config={"websockets.stream.url": stream_url},
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
            f"({session.device_entry.runtime} @ "
            f"{session.device_entry.address})",
        )

        wifi_marker = session.wait_for("WIFI_OK", timeout_s=args.wifi_timeout_s)
        print(f"driver: board WIFI_OK ip={wifi_marker.values.get('ip')}")

        # Wait on the terminal STREAM_CLOSED marker (it carries the count,
        # which proves the messages arrived) rather than the intermediate
        # WS_OPEN / MESSAGE markers: a single corrupted serial line on a
        # non-terminal marker shouldn't fail an otherwise-clean run.
        closed_marker = session.wait_for(
            "STREAM_CLOSED", timeout_s=args.completion_timeout_s,
        )
        count = closed_marker.values.get("count")
        print(f"driver: board STREAM_CLOSED count={count} code={closed_marker.values.get('code')}")
        if count != str(_STREAM_MESSAGE_COUNT):
            print(
                f"driver: expected {_STREAM_MESSAGE_COUNT} streamed messages, "
                f"board reported {count}.",
                file=sys.stderr,
            )
            return 4

        session.wait_for("DEMO_COMPLETE", timeout_s=5.0)
        print("driver: demo completed cleanly.")
        return 0
    except MarkerTimeoutError as marker_error:
        print(f"driver: {marker_error}", file=sys.stderr)
        if session is not None:
            try:
                captured = session.wait_for_completion(timeout_s=10.0)
            except BaseException:
                captured = session.captured_stdout or ""
            if captured:
                print(
                    "driver: --- captured board stdout ---\n"
                    f"{captured}\n--- end captured ---",
                    file=sys.stderr,
                )
        return 3
    finally:
        if session is not None:
            session.shutdown()
        stop_event.set()


if __name__ == "__main__":
    raise SystemExit(main())
