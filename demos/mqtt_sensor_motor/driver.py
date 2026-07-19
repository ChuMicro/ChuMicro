"""Host-side driver for the mqtt_sensor_motor demo.

Spins up a local Mosquitto broker on the host's LAN IP, deploys the
board's ``app.py`` via :func:`chumicro_workspace.deploy_api.deploy_project`
with broker coords baked into the runtime_config payload, and runs a
CPython-side :class:`MQTTClient` as the counterparty.

The host subscribes to the board's wildcard topics
(``demo/+/availability``, ``demo/+/telemetry``, ``demo/+/motor/state``)
*before* the board reaches the broker: the board's first telemetry
samples drain from its pre-connect queue at CONNACK, and a late
subscriber misses them.  Then it drives the round trip:

1. expect the retained/live ``"online"`` availability;
2. expect >= 3 telemetry samples with plausible celsius and a
   strictly increasing ``seq``;
3. publish ``motor/set`` = ``75`` (QoS 1) and expect both the board's
   ``MOTOR_APPLIED speed=75`` marker and a retained ``motor/state`` of
   ``75``;
4. publish ``motor/set`` = ``0`` and expect ``motor/state`` = ``0``;
5. at shutdown, expect the retained ``"offline"`` availability and the
   board's ``DEMO_COMPLETE`` marker.

Any miss exits non-zero with a message aimed at a transcript reader.

Pinned ``deploy_mode="flash"`` so the demo always runs the
production-shaped path regardless of any per-device override in
``devices.yml``.

Requires ``mosquitto`` on PATH (``brew install mosquitto`` /
``apt install mosquitto``).
"""

from __future__ import annotations

import argparse
import json
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
#: the board publishes under (``demo/<client_id>/...``).
_BOARD_CLIENT_ID = "chumicro-sensor-motor-board"

#: Identifier the host MQTT client registers with the broker.  Must
#: differ from the board's so the broker doesn't evict one of them on
#: the duplicate-client-id rule.
_HOST_CLIENT_ID = "chumicro-sensor-motor-driver"

#: Telemetry samples the driver waits for before it starts commanding.
_TELEMETRY_TARGET = 3
#: Generous plausibility window covering real CPU temps and the
#: synthetic wave (25 +/- 8 C) alike.
_CELSIUS_MIN = -40.0
_CELSIUS_MAX = 125.0


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
    workdir = Path(tempfile.mkdtemp(prefix="chumicro_sensor_motor_broker_"))
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

    ``MarkerQueue.poll`` checks without blocking, so the loop ticks the
    host client between polls.  If it stalled, the board's inbound
    stream (its QoS-1 telemetry) would back up and get missed.
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


def _validate_telemetry(samples: list[str]) -> str | None:
    """Return an error string if the telemetry samples are implausible."""
    last_seq = 0
    for raw in samples:
        try:
            reading = json.loads(raw)
        except ValueError:
            return f"telemetry payload was not JSON: {raw!r}"
        celsius = reading.get("celsius")
        seq = reading.get("seq")
        if not isinstance(celsius, (int, float)):
            return f"telemetry missing numeric 'celsius': {raw!r}"
        if not _CELSIUS_MIN <= celsius <= _CELSIUS_MAX:
            return (
                f"telemetry celsius {celsius} outside "
                f"[{_CELSIUS_MIN}, {_CELSIUS_MAX}]: {raw!r}"
            )
        if not isinstance(seq, int) or seq <= last_seq:
            return (
                f"telemetry seq not strictly increasing "
                f"(got {seq!r} after {last_seq}): {raw!r}"
            )
        last_seq = seq
    return None


def _publish_speed(
    host_client: MQTTClient, command_topic: str, speed: int, *, timeout_s: float,
) -> bool:
    """Publish a QoS-1 speed command and drive until its PUBACK lands."""
    acked = [False]
    host_client.publish(
        command_topic, str(speed).encode(), qos=1,
        on_publish=lambda *_: acked.__setitem__(0, True),
    )
    return _drive_host(host_client, lambda: acked[0], timeout_s=timeout_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive the mqtt_sensor_motor demo against a board.",
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
        help="seconds to wait for the first three telemetry receipts",
    )
    args = parser.parse_args(argv)

    broker_process, broker_workdir, broker_host, broker_port = _resolve_broker()
    print(f"driver: started mosquitto on {broker_host}:{broker_port}")

    command_topic = f"demo/{_BOARD_CLIENT_ID}/motor/set"
    availability_received: list[str] = []
    telemetry_received: list[str] = []
    state_received: list[str] = []

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

        def _on_host_message(topic, payload):
            text = (
                payload.decode("utf-8", "replace")
                if isinstance(payload, bytes) else str(payload)
            )
            if topic.endswith("/availability"):
                availability_received.append(text)
                print(f"driver: HOST_RX {topic} payload={text} (retained)")
            elif topic.endswith("/telemetry"):
                telemetry_received.append(text)
                print(f"driver: HOST_RX {topic} payload={text}")
            elif topic.endswith("/motor/state"):
                state_received.append(text)
                print(f"driver: HOST_RX {topic} payload={text} (retained)")
            else:
                print(f"driver: HOST_RX {topic} payload={text}")

        host_client.on_message = _on_host_message

        # Subscribe to every board topic BEFORE the board reaches the
        # broker: its first telemetry drains from the pre-connect queue
        # at CONNACK, and a late subscriber misses it.  The board is
        # still doing wifi bring-up while these SUBACKs land.
        subscribed = [0]
        for topic_filter in (
            "demo/+/availability", "demo/+/telemetry", "demo/+/motor/state",
        ):
            host_client.subscribe(
                topic_filter, qos=1,
                on_subscribe=lambda *_: subscribed.__setitem__(
                    0, subscribed[0] + 1,
                ),
            )
        if not _drive_host(
            host_client, lambda: subscribed[0] >= 3, timeout_s=5.0,
        ):
            print(
                "driver: host SUBACKs for the board topics didn't all "
                f"arrive (got {subscribed[0]}/3).",
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

        # Availability: the retained "online" arrives live (host was
        # already subscribed when the board published it on connect).
        if not _drive_host(
            host_client,
            lambda: any(text == "online" for text in availability_received),
            timeout_s=15.0,
        ):
            print(
                "driver: expected retained 'online' on demo/+/availability "
                f"but saw {availability_received!r}.",
                file=sys.stderr,
            )
            return 4

        # Telemetry: >= 3 samples with plausible celsius and increasing seq.
        if not _drive_host(
            host_client,
            lambda: len(telemetry_received) >= _TELEMETRY_TARGET,
            timeout_s=args.telemetry_timeout_s,
        ):
            print(
                f"driver: only received {len(telemetry_received)}/"
                f"{_TELEMETRY_TARGET} telemetry messages within "
                f"{args.telemetry_timeout_s}s.",
                file=sys.stderr,
            )
            return 6
        telemetry_error = _validate_telemetry(
            telemetry_received[:_TELEMETRY_TARGET],
        )
        if telemetry_error is not None:
            print(f"driver: {telemetry_error}", file=sys.stderr)
            return 6
        print(
            f"driver: telemetry {len(telemetry_received)} received, "
            f"celsius + seq plausible",
        )

        # Command 75 -> expect the MOTOR_APPLIED marker and a state echo.
        if not _publish_speed(
            host_client, command_topic, 75, timeout_s=10.0,
        ):
            print(
                f"driver: host cmd 75 to {command_topic} got no PUBACK.",
                file=sys.stderr,
            )
            return 7
        print(f"driver: host published motor/set 75 to {command_topic}")
        applied = _await_marker_while_driving_host(
            session, host_client, "MOTOR_APPLIED", timeout_s=15.0,
        )
        if applied.values.get("speed") != "75":
            print(
                f"driver: MOTOR_APPLIED speed={applied.values.get('speed')}, "
                f"expected 75.",
                file=sys.stderr,
            )
            return 7
        if not _drive_host(
            host_client, lambda: state_received and state_received[-1] == "75",
            timeout_s=10.0,
        ):
            print(
                f"driver: expected retained motor/state '75' but saw "
                f"{state_received!r}.",
                file=sys.stderr,
            )
            return 7
        print("driver: motor at 75 confirmed (marker + state echo)")

        # Command 0 -> expect the state echo to fall back to 0.
        if not _publish_speed(
            host_client, command_topic, 0, timeout_s=10.0,
        ):
            print(
                f"driver: host cmd 0 to {command_topic} got no PUBACK.",
                file=sys.stderr,
            )
            return 7
        print(f"driver: host published motor/set 0 to {command_topic}")
        if not _drive_host(
            host_client, lambda: state_received and state_received[-1] == "0",
            timeout_s=10.0,
        ):
            print(
                f"driver: expected retained motor/state '0' but saw "
                f"{state_received!r}.",
                file=sys.stderr,
            )
            return 7
        print("driver: motor at 0 confirmed (state echo)")

        # Graceful shutdown: the board announces "offline" before its
        # clean disconnect (which would otherwise suppress the will).
        if not _drive_host(
            host_client,
            lambda: availability_received and availability_received[-1] == "offline",
            timeout_s=15.0,
        ):
            print(
                "driver: expected retained 'offline' at shutdown but saw "
                f"{availability_received!r}.",
                file=sys.stderr,
            )
            return 8
        _await_marker_while_driving_host(
            session, host_client, "DEMO_COMPLETE", timeout_s=15.0,
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
        return 9
    finally:
        if host_client is not None:
            try:
                host_client.disconnect()
                _drive_host(
                    host_client,
                    lambda: host_client.state != ProtocolState.CONNECTED,
                    timeout_s=2.0,
                )
            except Exception as disconnect_error:  # noqa: BLE001
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
