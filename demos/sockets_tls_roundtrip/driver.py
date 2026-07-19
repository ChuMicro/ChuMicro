"""Host-side driver for the sockets_tls_roundtrip demo.

Generates a fresh self-signed cert + key in a temp directory, spins up
a TLS echo server on the host's LAN IP using that cert, deploys the
board's ``app.py`` via :func:`chumicro_workspace.deploy_api.deploy_project`
with the echo coords AND the cert PEM bytes baked into the
runtime_config payload, and waits for the board's marker sequence to
confirm the TLS handshake + round trip.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from chumicro_pytest_device.fixtures.lan import detect_lan_ip
from chumicro_pytest_device.fixtures.tls_echo import (
    generate_self_signed_cert,
    start_tls_echo_server,
)
from chumicro_workspace.deploy_api import (
    DeployApiError,
    DeviceNotFoundError,
    deploy_project,
)
from chumicro_workspace.markers import MarkerTimeoutError

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device", default=None,
        help="device id from devices.yml (default: first matching --runtime)",
    )
    parser.add_argument(
        "--runtime", default=None,
        help="runtime to pick the default device for (circuitpython | micropython)",
    )
    parser.add_argument(
        "--wifi-timeout-s", type=float, default=45.0,
        help="seconds to wait for the board WIFI_OK marker",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=60.0,
        help="seconds to wait for DEMO_COMPLETE after WIFI_OK "
             "(TLS handshakes are slower than plain TCP)",
    )
    args = parser.parse_args(argv)

    lan_ip = detect_lan_ip()
    if lan_ip is None:
        print(
            "driver: could not detect a LAN IP for the echo server.  Is "
            "wifi up on the host?",
            file=sys.stderr,
        )
        return 1

    cert_workdir = Path(tempfile.mkdtemp(prefix="sockets-tls-demo-"))
    cert_path, key_path = generate_self_signed_cert(cert_workdir, common_name=lan_ip)
    ca_pem_bytes = cert_path.read_bytes()
    echo_host, echo_port, echo_stop = start_tls_echo_server(
        lan_ip, cert_path, key_path,
    )
    print(f"driver: tls echo server up on {echo_host}:{echo_port}")
    print(f"driver: self-signed cert at {cert_path} (CN={lan_ip})")

    session = None
    try:
        try:
            session = deploy_project(
                project_dir=_DEMO_DIR,
                device_id=args.device,
                runtime=args.runtime,
                deploy_mode="flash",
                extra_runtime_config={
                    "sockets.echo.host": echo_host,
                    "sockets.echo.port": echo_port,
                    # PEM bytes ship as a str over msgpack.  The board
                    # encodes back to bytes before passing to
                    # ssl_context_with_ca.
                    "sockets.echo.ca_pem": ca_pem_bytes.decode("ascii"),
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

        connecting_marker = session.wait_for("CONNECTING", timeout_s=10.0)
        print(
            f"driver: board CONNECTING host={connecting_marker.values.get('host')} "
            f"port={connecting_marker.values.get('port')}",
        )

        session.wait_for("CONNECTED", timeout_s=30.0)
        print("driver: board CONNECTED")

        sent_marker = session.wait_for("SENT", timeout_s=5.0)
        print(f"driver: board SENT bytes={sent_marker.values.get('bytes')}")

        echo_marker = session.wait_for("ECHO_RECEIVED", timeout_s=10.0)
        print(
            f"driver: board ECHO_RECEIVED "
            f"bytes={echo_marker.values.get('bytes')} "
            f"payload_hex={echo_marker.values.get('payload_hex')}",
        )

        session.wait_for("DEMO_COMPLETE", timeout_s=args.completion_timeout_s)
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
        echo_stop.set()


if __name__ == "__main__":
    raise SystemExit(main())
