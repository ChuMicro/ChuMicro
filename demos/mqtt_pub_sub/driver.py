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
import time
from pathlib import Path

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_pytest_device.fixtures.mosquitto import provision_lan_broker
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


def _reactor_pump(client: MQTTClient):
    """One-tick pump for ``session.wait_for(pump=...)``: keeps the host
    MQTT client's inbound stream draining while a marker wait blocks."""
    def pump() -> None:
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
    return pump


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

    try:
        broker_process, broker_workdir, broker_host, broker_port = (
            provision_lan_broker(workdir_prefix="chumicro_mqtt_demo_broker_")
        )
    except RuntimeError as broker_error:
        raise SystemExit(f"driver: {broker_error}") from broker_error
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
        pump = _reactor_pump(host_client)
        connected_marker = session.wait_for(
            "MQTT_CONNECTED", timeout_s=args.connect_timeout_s, pump=pump,
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
        session.wait_for("RETAINED_STATE_SENT", timeout_s=15.0, pump=pump)

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
        session.wait_for("SUBSCRIBED", timeout_s=15.0, pump=pump)

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
            f"driver: host published cmd to {command_topic} (qos=1), PUBACK received",
        )

        # The board's on_message fires when the command lands.
        session.wait_for("CMD_RECEIVED", timeout_s=15.0, pump=pump)

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

        session.wait_for(
            "DEMO_COMPLETE", timeout_s=args.completion_timeout_s, pump=pump,
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
