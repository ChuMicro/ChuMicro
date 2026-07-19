"""Host-side driver for the mqtt_pub_sub demo.

Spins up a local Mosquitto broker on the host's LAN IP, deploys the
board's ``app.py`` via :func:`chumicro_workspace.deploy_api.deploy_project`
with broker coords baked into the runtime_config payload, and runs a
CPython-side :class:`MQTTClient` as the counterparty: subscribes to
wildcard topics (``demo/+/state``, ``demo/+/telemetry``) to verify the
board's retained "online" + three QoS 1 telemetry publishes, and
publishes a QoS 1 command back so the board's inbound path (its
``on_message`` callback) fires in one run.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.

Requires ``mosquitto`` on PATH (``brew install mosquitto`` /
``apt install mosquitto``).
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_pytest_device.fixtures.lan import detect_lan_ip
from chumicro_pytest_device.fixtures.mosquitto import start_mosquitto_broker
from chumicro_timing import ticks_ms
from chumicro_workspace.deploy_api import (
    DeployApiError,
    DeviceNotFoundError,
    deploy_project,
)
from chumicro_workspace.markers import MarkerTimeoutError

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]

#: Pinned per-board identifier the driver injects into runtime_config.
#: Both sides need the same value so the driver knows the topic prefix
#: the board will publish under (``demo/<client_id>/...``).
_BOARD_CLIENT_ID = "chumicro-mqtt-demo-board"

#: Identifier the host MQTT client registers with the broker.  Must
#: differ from the board's so the broker doesn't kick one of them off
#: on the duplicate-client-id rule.
_HOST_CLIENT_ID = "chumicro-mqtt-demo-driver"


def _resolve_broker() -> tuple[subprocess.Popen[bytes], Path, str, int]:
    """Spin up Mosquitto bound to the host's LAN IP, return the handle."""
    if shutil.which("mosquitto") is None:
        raise SystemExit(
            "driver: `mosquitto` is not on PATH.  Install it "
            "(`brew install mosquitto` / `apt install mosquitto`) so the "
            "demo can run a broker locally for the board to reach over wifi.",
        )
    lan_ip = detect_lan_ip()
    if lan_ip is None:
        raise SystemExit(
            "driver: couldn't detect a LAN IP: the board needs an "
            "address it can reach over wifi.  Check that the host is "
            "connected to the same network the board will join.",
        )
    workdir = Path(tempfile.mkdtemp(prefix="chumicro_mqtt_demo_broker_"))
    broker = start_mosquitto_broker(lan_ip, workdir)
    if broker is None:
        shutil.rmtree(workdir, ignore_errors=True)
        raise SystemExit(
            f"driver: failed to start mosquitto on {lan_ip}.  Check "
            f"{workdir}/broker.log for the broker's own output.",
        )
    process, port = broker
    return process, workdir, lan_ip, port


def _new_host_client(broker_host: str, broker_port: int) -> MQTTClient:
    # Host-side CPython driver: stdlib connect is the one-shot form here.
    sock = socket.create_connection((broker_host, broker_port))
    sock.setblocking(False)
    return MQTTClient(
        sock,
        client_id=_HOST_CLIENT_ID,
        keep_alive_seconds=30,
        ack_timeout_seconds=5.0,
    )


def _drive_host(client: MQTTClient, predicate, *, timeout_s: float) -> bool:
    """Tick the host MQTT client until *predicate* is truthy or *timeout_s*."""
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            return False
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
        time.sleep(0.01)
    return True


def _await_marker_while_driving_host(
    session, host_client: MQTTClient, marker_name: str, *, timeout_s: float,
):
    """Wait for *marker_name* while keeping the host MQTT client ticking.

    The marker queue's wait_for is a blocking get; if the host MQTT
    client doesn't tick during that wait, its inbound stream stalls and
    later publishes (e.g. the board's QoS 1 telemetry) are missed.
    ``MarkerQueue.poll`` checks without blocking, so the loop ticks the
    host client between polls until the marker arrives or the timeout
    fires.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        marker = session.runner.marker_queue.poll(marker_name)
        if marker is not None:
            return marker
        if time.monotonic() >= deadline:
            raise MarkerTimeoutError(
                f"driver: timed out after {timeout_s:.1f}s waiting for "
                f"marker {marker_name!r}",
            )
        if host_client.check(ticks_ms()):
            host_client.handle(ticks_ms())
        time.sleep(0.02)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the mqtt_pub_sub demo against a registered board."
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
        "--connect-timeout-s", type=float, default=60.0,
        help="seconds to wait for the board's MQTT_CONNECTED marker",
    )
    parser.add_argument(
        "--telemetry-timeout-s", type=float, default=30.0,
        help="seconds to wait for all three telemetry receipts on the host",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=120.0,
        help="seconds to wait for DEMO_COMPLETE after the round trip",
    )
    args = parser.parse_args(argv)

    broker_process, broker_workdir, broker_host, broker_port = _resolve_broker()
    print(f"driver: started mosquitto on {broker_host}:{broker_port}")

    session = None
    host_client: MQTTClient | None = None
    try:
        try:
            session = deploy_project(
                project_dir=_DEMO_DIR,
                device_id=args.device,
                runtime=args.runtime,
                deploy_mode="flash",
                extra_runtime_config={
                    "mqtt.broker.host": broker_host,
                    "mqtt.broker.port": broker_port,
                    "mqtt.client_id": _BOARD_CLIENT_ID,
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

        host_client = _new_host_client(broker_host, broker_port)
        host_client.connect()
        if not _drive_host(
            host_client,
            lambda: host_client.state == ProtocolState.CONNECTED,
            timeout_s=10.0,
        ):
            print(
                f"driver: host MQTT client didn't reach CONNECTED "
                f"(state={host_client.state}, "
                f"last_error={host_client.last_error})",
                file=sys.stderr,
            )
            return 2
        print(f"driver: host MQTT client connected ({_HOST_CLIENT_ID})")

        retained_received: list[tuple[str, bytes]] = []
        telemetry_received: list[tuple[str, bytes]] = []

        def _on_host_message(topic, payload):
            text = (
                payload.decode("utf-8", "replace")
                if isinstance(payload, bytes) else str(payload)
            )
            if "/state" in topic:
                retained_received.append((topic, payload))
                print(f"driver: HOST_RX {topic} payload={text} (retained)")
            elif "/telemetry" in topic:
                telemetry_received.append((topic, payload))
                print(f"driver: HOST_RX {topic} payload={text}")
            else:
                print(f"driver: HOST_RX {topic} payload={text}")

        host_client.on_message = _on_host_message

        # Subscribe to telemetry BEFORE the board reaches the broker:
        # the board's first samples drain from its pre-connect publish
        # queue at CONNACK, and a late subscriber misses them.  The
        # board is still doing wifi bring-up while this SUBACK lands.
        telemetry_subscribed = [False]
        host_client.subscribe(
            "demo/+/telemetry", qos=1,
            on_subscribe=lambda *_: telemetry_subscribed.__setitem__(0, True),
        )
        if not _drive_host(
            host_client, lambda: telemetry_subscribed[0], timeout_s=5.0,
        ):
            print(
                "driver: host SUBACK for demo/+/telemetry didn't arrive.",
                file=sys.stderr,
            )
            return 5

        print(
            f"driver: waiting for board MQTT_CONNECTED "
            f"(up to {args.connect_timeout_s}s)...",
        )
        connected_marker = _await_marker_while_driving_host(
            session, host_client, "MQTT_CONNECTED",
            timeout_s=args.connect_timeout_s,
        )
        print(
            f"driver: board MQTT_CONNECTED "
            f"client_id={connected_marker.values.get('client_id')} "
            f"broker={connected_marker.values.get('broker')}",
        )

        # Wait for the board's retained publish so a fresh wildcard
        # subscriber sees the retained payload on SUBACK (the state
        # subscribe below deliberately happens AFTER this marker: it
        # pins retained-delivery-on-SUBACK semantics).
        _await_marker_while_driving_host(
            session, host_client, "RETAINED_STATE_SENT", timeout_s=15.0,
        )

        state_subscribed = [False]
        host_client.subscribe(
            "demo/+/state", qos=1,
            on_subscribe=lambda *_: state_subscribed.__setitem__(0, True),
        )
        if not _drive_host(
            host_client, lambda: state_subscribed[0], timeout_s=5.0,
        ):
            print(
                "driver: host SUBACK for demo/+/state didn't arrive.",
                file=sys.stderr,
            )
            return 3

        # Retained payload lands as the SUBACK clears the broker; give
        # the reactor a beat to drain it.
        _drive_host(host_client, lambda: retained_received, timeout_s=5.0)
        if not retained_received:
            print(
                "driver: expected retained 'online' on demo/+/state but "
                "nothing arrived.",
                file=sys.stderr,
            )
            return 4

        # Board prints SUBSCRIBED after its own SUBACK lands.
        _await_marker_while_driving_host(
            session, host_client, "SUBSCRIBED", timeout_s=15.0,
        )

        command_topic = f"demo/{_BOARD_CLIENT_ID}/cmd"
        command_acked = [False]
        host_client.publish(
            command_topic, b"ping",
            qos=1,
            on_publish=lambda *_: command_acked.__setitem__(0, True),
        )
        if not _drive_host(
            host_client, lambda: command_acked[0], timeout_s=10.0,
        ):
            print(
                f"driver: host cmd publish to {command_topic} got no PUBACK.",
                file=sys.stderr,
            )
            return 6
        print(
            f"driver: host published cmd to {command_topic} (qos=1), PUBACK in",
        )

        # The board's on_message fires when the command lands.
        _await_marker_while_driving_host(
            session, host_client, "CMD_RECEIVED", timeout_s=15.0,
        )

        # Drive host until all three telemetry samples have arrived.
        if not _drive_host(
            host_client, lambda: len(telemetry_received) >= 3,
            timeout_s=args.telemetry_timeout_s,
        ):
            print(
                f"driver: only received {len(telemetry_received)}/3 "
                f"telemetry messages within {args.telemetry_timeout_s}s.",
                file=sys.stderr,
            )
            return 7
        print(f"driver: telemetry {len(telemetry_received)}/3 received")

        _await_marker_while_driving_host(
            session, host_client, "DEMO_COMPLETE",
            timeout_s=args.completion_timeout_s,
        )

        print("driver: demo completed cleanly.")
        return 0
    except MarkerTimeoutError as marker_error:
        print(f"driver: {marker_error}", file=sys.stderr)
        if session is not None:
            try:
                captured = session.wait_for_completion(timeout_s=30.0)
            except BaseException:
                captured = session.captured_stdout or ""
            if captured:
                print(
                    "driver: --- captured board stdout ---\n"
                    f"{captured}\n--- end captured ---",
                    file=sys.stderr,
                )
        return 8
    finally:
        if host_client is not None:
            try:
                host_client.disconnect()
                _drive_host(
                    host_client,
                    lambda: host_client.state != ProtocolState.CONNECTED,
                    timeout_s=2.0,
                )
            except Exception as disconnect_error:
                print(
                    f"driver: warning, host MQTT disconnect raised "
                    f"{type(disconnect_error).__name__}: {disconnect_error}",
                    file=sys.stderr,
                )
        if session is not None:
            session.shutdown()
        broker_process.terminate()
        try:
            broker_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            broker_process.kill()
        shutil.rmtree(broker_workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
