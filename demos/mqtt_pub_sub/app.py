"""Board-side of the mqtt_pub_sub demo.

Composes the canonical libraries: chumicro_config loads the deployed
runtime_config; chumicro_test_harness.network.wifi_up brings the wifi
substrate up; chumicro_mqtt.MQTTClient.from_config dials the broker;
chumicro_runner.Runner drives the MQTT client cooperatively in one
``while not done: now_ms = runner.tick(); runner.wait(now_ms)`` loop.
Orchestration is event-driven through library callbacks
(``on_publish``, ``on_subscribe``, ``on_message``) and a per-tick
state advance — no hand-rolled drive-until helpers.

Stdout markers (``WIFI_OK``, ``MQTT_CONNECTED``, ``RETAINED_STATE_SENT``,
``SUBSCRIBED``, ``TELEMETRY_SENT``, ``CMD_RECEIVED``, ``PATTERN_HIT``,
``DEMO_COMPLETE``) drive the host driver via the stdout-marker protocol.

WifiService isn't on the runner here because CircuitPython's
``wifi.radio.connect`` is blocking (15 s budget) — running it inside a
runner tick disturbs the USB-CDC and the cooperative loop assumption.
``wifi_up`` is the single blocking call at boot; everything after is
genuine non-blocking runner-tick work.
"""

import json

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_test_harness.network import wifi_up
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

_TELEMETRY_COUNT = 3
_TELEMETRY_INTERVAL_MS = 1_500
_DEMO_OVERALL_DEADLINE_MS = 120_000
_DISCONNECT_DRAIN_MS = 250


config = load_runtime_config()
client_id = config.get("mqtt.client_id", "chumicro-mqtt-demo-board")
state_topic = f"demo/{client_id}/state"
command_topic = f"demo/{client_id}/cmd"
telemetry_topic = f"demo/{client_id}/telemetry"

radio, ip_address = wifi_up(
    config.get("wifi.ssid"),
    config.get("wifi.password"),
)
print(f"WIFI_OK ip={ip_address}")

runner = Runner()
mqtt = MQTTClient.from_config(config, radio=radio)
runner.add(mqtt)


class DemoState:
    """Per-tick state machine: drives the demo through its phases.

    Each ``advance(now_ms)`` inspects the MQTT state and fires one-shot
    actions when their prerequisites are met.  All side effects (prints,
    publishes, subscribes) happen here so the main loop stays a plain
    ``while not done: tick; advance; wait``.
    """

    PHASE_BOOT = "boot"
    PHASE_RETAIN_PENDING = "retain_pending"
    PHASE_SUBSCRIBE_PENDING = "subscribe_pending"
    PHASE_PUBLISHING = "publishing"
    PHASE_DRAINING = "draining"
    PHASE_DISCONNECTING = "disconnecting"
    PHASE_DONE = "done"

    def __init__(self) -> None:
        self.phase = self.PHASE_BOOT
        self.start_ticks_ms = ticks_ms()
        self.telemetry_sent = 0
        self.telemetry_acked = 0
        self.next_telemetry_due_ms = 0
        self.command_received = False
        self.disconnect_started_ms = 0

    @property
    def done(self) -> bool:
        return self.phase == self.PHASE_DONE

    def advance(self, now_ms):
        if self.phase == self.PHASE_BOOT:
            if mqtt.state == ProtocolState.CONNECTED:
                broker_host = config["mqtt.broker.host"]
                broker_port = config["mqtt.broker.port"]
                print(
                    f"MQTT_CONNECTED broker={broker_host}:{broker_port} "
                    f"client_id={client_id}",
                )
                mqtt.publish(
                    state_topic, b"online",
                    qos=1, retain=True, prefixed=False,
                    on_publish=self._on_retained_published,
                )
                self.phase = self.PHASE_RETAIN_PENDING
            return

        if self.phase == self.PHASE_RETAIN_PENDING:
            return  # Wait for retained PUBACK callback to advance.

        if self.phase == self.PHASE_SUBSCRIBE_PENDING:
            return  # Wait for SUBACK callback to advance.

        if self.phase == self.PHASE_PUBLISHING:
            if (
                self.telemetry_sent < _TELEMETRY_COUNT
                and ticks_diff(now_ms, self.next_telemetry_due_ms) >= 0
            ):
                self.telemetry_sent += 1
                payload = json.dumps({
                    "seq": self.telemetry_sent,
                    "value": 20 + self.telemetry_sent,
                    "uptime_ms": ticks_diff(now_ms, self.start_ticks_ms),
                })
                mqtt.publish(
                    telemetry_topic, payload.encode(),
                    qos=1, prefixed=False,
                    on_publish=self._on_telemetry_published,
                )
                self.next_telemetry_due_ms = ticks_add(
                    now_ms, _TELEMETRY_INTERVAL_MS,
                )
            if (
                self.telemetry_sent == _TELEMETRY_COUNT
                and self.telemetry_acked == _TELEMETRY_COUNT
                and self.command_received
            ):
                self.phase = self.PHASE_DRAINING
            return

        if self.phase == self.PHASE_DRAINING:
            mqtt.disconnect()
            self.phase = self.PHASE_DISCONNECTING
            self.disconnect_started_ms = now_ms
            return

        if self.phase == self.PHASE_DISCONNECTING:
            if (
                ticks_diff(now_ms, self.disconnect_started_ms)
                >= _DISCONNECT_DRAIN_MS
            ):
                print("DEMO_COMPLETE")
                self.phase = self.PHASE_DONE
            return

    def _on_retained_published(self, *_args):
        print(f"RETAINED_STATE_SENT topic={state_topic}")
        mqtt.subscribe(
            command_topic, qos=1, prefixed=False,
            on_subscribe=self._on_subscribed,
        )
        self.phase = self.PHASE_SUBSCRIBE_PENDING

    def _on_subscribed(self, *_args):
        print(f"SUBSCRIBED topic={command_topic}")
        self.next_telemetry_due_ms = ticks_ms()
        self.phase = self.PHASE_PUBLISHING

    def _on_telemetry_published(self, *_args):
        self.telemetry_acked += 1
        print(f"TELEMETRY_SENT seq={self.telemetry_acked}")


demo = DemoState()
# Register advance() as a periodic so the runner wakes up between MQTT
# events to fire the pacing timer.  Without this, runner.wait sleeps
# until MQTT's next keepalive deadline (~30 s) and the demo's
# 1.5 s telemetry cadence stretches across that whole interval.
runner.add_periodic(lambda now_ms: demo.advance(now_ms), period_ms=100)


def _on_message(topic, payload):
    decoded = (
        payload.decode("utf-8", "replace") if isinstance(payload, bytes)
        else payload
    )
    demo.command_received = True
    print(f"CMD_RECEIVED topic={topic} payload={decoded}")


def _on_cmd_pattern(topic, _payload):
    print(f"PATTERN_HIT topic={topic}")


mqtt.on_message = _on_message
mqtt.add_pattern_handler("demo/+/cmd", _on_cmd_pattern)
mqtt.connect()

overall_deadline_ms = ticks_add(ticks_ms(), _DEMO_OVERALL_DEADLINE_MS)
while not demo.done:
    now_ms = runner.tick()
    if ticks_diff(now_ms, overall_deadline_ms) >= 0:
        print(
            f"STATUS: FAIL_DEMO_DEADLINE phase={demo.phase} "
            f"telemetry_sent={demo.telemetry_sent} "
            f"telemetry_acked={demo.telemetry_acked} "
            f"command_received={demo.command_received}",
        )
        raise SystemExit(1)
    runner.wait(now_ms)
