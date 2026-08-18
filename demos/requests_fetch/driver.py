"""Host-side driver for the requests_fetch demo.

Starts a stdlib HTTP server on the host's LAN IP that returns a small
JSON body, deploys the board's ``app.py`` via
:func:`chumicro_workspace.deploy_api.deploy_project` with the fetch URL
baked into the runtime_config payload, then waits for the board's
marker sequence to confirm the one-shot GET completed.

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

_RESPONSE_BODY = b'{"message": "hello from the requests_fetch demo"}'


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
        "--wifi-timeout-s", type=float, default=45.0,
        help="seconds to wait for the board WIFI_OK marker",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=30.0,
        help="seconds to wait for FETCHED after FETCHING",
    )
    args = parser.parse_args(argv)

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
                extra_runtime_config={"requests.fetch.url": fetch_url},
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

        session.wait_for("FETCHING", timeout_s=10.0)
        print(f"driver: board FETCHING url={fetch_url}")

        fetched_marker = session.wait_for(
            "FETCHED", timeout_s=args.completion_timeout_s,
        )
        status = fetched_marker.values.get("status")
        print(
            f"driver: board FETCHED status={status} "
            f"bytes={fetched_marker.values.get('bytes')}",
        )
        if status != "200":
            print(
                f"driver: expected status 200 from the demo server, got {status}.",
                file=sys.stderr,
            )
            return 4

        # The board lingers a few seconds after FETCHED before it prints
        # DEMO_COMPLETE, so this wait covers the linger too.
        session.wait_for("DEMO_COMPLETE", timeout_s=15.0)
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
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
