"""Host-side driver for the press_through_fetch demo.

Starts a stdlib HTTP server on the host's LAN IP, deploys the board's
``app.py`` via :func:`chumicro_workspace.deploy_api.deploy_project` with
the fetch URL and the button pin baked into the runtime_config payload,
waits for wifi and the first fetch, then asks the operator to press the
button and confirms the press and its held duration came back.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.
"""

from __future__ import annotations

import argparse
import http.server
import sys
import threading
from pathlib import Path

from chumicro_pytest_device.fixtures.lan import detect_lan_ip
from chumicro_workspace.deploy_api import (
    DeployApiError,
    DeviceNotFoundError,
    deploy_project,
)
from chumicro_workspace.markers import MarkerTimeoutError

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]

_RESPONSE_BODY = b'{"message": "hello from the press_through_fetch demo"}'


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answer any GET with a fixed JSON body + Content-Length."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler dispatch name
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_RESPONSE_BODY)))
        self.end_headers()
        self.wfile.write(_RESPONSE_BODY)

    def log_message(self, *_args):
        """Silence the per-request stderr log so the demo output stays clean."""


def _start_http_server(bind_host: str):
    """Start a threaded HTTP server on *bind_host*:0; return (server, port)."""
    server = http.server.ThreadingHTTPServer((bind_host, 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


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
        "--button-pin", default=None,
        help=(
            "pin the button is wired to, against GND with the internal "
            "pull-up on: a number on MicroPython, a board attribute name "
            "on CircuitPython (default: 3 or GP3 by runtime)"
        ),
    )
    parser.add_argument(
        "--wifi-timeout-s", type=float, default=45.0,
        help="seconds to wait for the board WIFI_OK marker",
    )
    parser.add_argument(
        "--press-timeout-s", type=float, default=60.0,
        help="seconds to wait for the operator's press",
    )
    args = parser.parse_args(argv)

    button_pin = args.button_pin
    if button_pin is None:
        button_pin = "3" if args.runtime == "micropython" else "GP3"

    lan_ip = detect_lan_ip()
    if lan_ip is None:
        print(
            "driver: could not detect a LAN IP for the HTTP server.  Is "
            "wifi up on the host?",
            file=sys.stderr,
        )
        return 1

    server, port = _start_http_server(lan_ip)
    fetch_url = f"http://{lan_ip}:{port}/hello"
    print(f"driver: http server up at {fetch_url}")

    session = None
    try:
        try:
            session = deploy_project(
                project_dir=_DEMO_DIR,
                device_id=args.device,
                runtime=args.runtime,
                deploy_mode="flash",
                extra_runtime_config={
                    "requests.fetch.url": fetch_url,
                    "buttons.demo.pin": button_pin,
                },
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

        fetched = session.wait_for("FETCHED", timeout_s=30.0)
        print(
            f"driver: board FETCHED status={fetched.values.get('status')} "
            f"bytes={fetched.values.get('bytes')}",
        )

        print(f"driver: press the button on pin {button_pin} now")
        press = session.wait_for("PRESS", timeout_s=args.press_timeout_s)
        print(f"driver: board PRESS count={press.values.get('count')}")

        release = session.wait_for("RELEASE", timeout_s=30.0)
        held_ms = int(release.values.get("held_ms", "0"))
        print(f"driver: board RELEASE held_ms={held_ms}")
        if held_ms <= 0:
            print(
                "driver: expected a positive held_ms measured from the "
                f"press edge, got {held_ms}.",
                file=sys.stderr,
            )
            return 4

        session.wait_for("DEMO_COMPLETE", timeout_s=15.0)
        print("driver: demo completed cleanly; the board is still fetching.")
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
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
