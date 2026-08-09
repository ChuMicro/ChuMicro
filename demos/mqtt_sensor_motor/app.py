"""Board-side of the mqtt_sensor_motor demo: a temperature-controlled fan node.

Reads the on-chip temperature, publishes it as JSON telemetry every
two seconds, and drives a PWM "motor" (a fan/pump ESC input) from
speed commands the broker delivers.  Wires ``chumicro_wifi.WifiService``
+ ``chumicro_mqtt.MQTTClient`` into one ``chumicro_runner.Runner`` and
drives them with ``runner.run_until(...)`` (no async, no threads).

It reads like a mainstream MQTT device sketch (paho / Adafruit
MiniMQTT): set a Last Will, set the callbacks once, connect, let the
loop run.  The demo deliberately leans on library behavior instead of
reimplementing it:

* **Pre-connect queue.**  ``publish_telemetry`` calls ``publish()`` with
  no CONNECTED guard.  A sample produced before the broker session is
  up buffers in the client's bounded pre-connect queue and flushes on
  CONNACK (the default ``when_disconnected="queue"`` policy), so the
  telemetry cadence never has to state-check the client.
* **Declarative subscribe.**  The command subscription is declared once
  at startup with ``subscribe()`` (before ``connect()``), not inside
  ``on_connect``.  The client records it in its desired set, puts it on
  the wire on the first CONNACK, and replays it on every self-heal
  reconnect, so the app carries no reconnect bookkeeping.
* **Availability via Last Will.**  A retained ``"offline"`` will the
  broker publishes if the board drops uncleanly, paired with a retained
  ``"online"`` sent on connect.  A clean shutdown suppresses the will,
  so the shutdown path publishes ``"offline"`` explicitly.
* **Self-heal.**  The wifi callback composes the pair: ``mqtt.hold()``
  while the link is down, ``mqtt.connect()`` the moment it returns, and
  the socket-factory transport rebuilds the connection.

Command path: an inbound speed (int 0-100) is clamped, applied to the
motor PWM (and mirrored onto the onboard LED so the bench shows speed),
then echoed back retained on ``motor/state`` (the closed loop).

Marker lines (``SENSOR_SOURCE``, ``MOTOR_READY``, ``WIFI_OK``,
``MQTT_CONNECTED``, ``TELEMETRY_SENT``, ``MOTOR_APPLIED``,
``DEMO_COMPLETE``) drive the host driver over stdout.
"""

import json
import math
import sys

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_test_harness.markers import marker
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

#: A general-purpose GPIO broken out on both sweep form factors and free
#: of any onboard function: Pico W ``GP16`` and Lolin S2 mini ``IO16``
#: (labelled D4).  A real fan/pump ESC's signal wire goes here.
_MOTOR_GPIO = 16
_PWM_FREQUENCY_HZ = 1_000
#: 16-bit full scale shared by CircuitPython ``duty_cycle``, MicroPython
#: ``duty_u16``, and the rp2 ADC's ``read_u16`` (one honest constant).
_U16_FULL_SCALE = 65_535

_TELEMETRY_INTERVAL_MS = 2_000
#: The host driver needs three telemetry samples and two motor commands
#: (speed 75 then 0) to see the full round trip; completion gates on both.
_TELEMETRY_TARGET = 3
_COMMAND_TARGET = 2
_DEMO_DEADLINE_MS = 120_000
#: Keep ticking this long after the last publish so the broker's QoS-1
#: acks land before the clean disconnect tears the socket down.
_FLUSH_DRAIN_MS = 750

_synthetic_start_ms = ticks_ms()


def _synthetic_celsius():
    """Deterministic temperature wave for boards without a CPU sensor."""
    seconds = ticks_diff(ticks_ms(), _synthetic_start_ms) / 1000.0
    return 25.0 + 8.0 * math.sin(seconds / 5.0)


# --- Cross-runtime hardware shim ------------------------------------
# Sensor, motor PWM, and LED mirror are the only per-board surface; the
# rest of the app is identical on all four sweep boards.  Branch on the
# runtime first, then (on MicroPython) on the chip for the temperature
# source, which rp2 has and esp32-s2 does not.
_impl_name = sys.implementation.name

if _impl_name == "circuitpython":
    import board
    import microcontroller
    import pwmio

    def read_celsius():
        return microcontroller.cpu.temperature

    SENSOR_SOURCE = "real"

    _motor_pwm = pwmio.PWMOut(
        getattr(microcontroller.pin, f"GPIO{_MOTOR_GPIO}"),
        frequency=_PWM_FREQUENCY_HZ,
        duty_cycle=0,
    )

    def set_motor_duty(fraction):
        _motor_pwm.duty_cycle = int(fraction * _U16_FULL_SCALE)

    try:
        _led_pwm = pwmio.PWMOut(
            board.LED, frequency=_PWM_FREQUENCY_HZ, duty_cycle=0,
        )

        def set_led(fraction):
            _led_pwm.duty_cycle = int(fraction * _U16_FULL_SCALE)

        LED_MODE = "pwm"
    except (TypeError, ValueError, RuntimeError):
        # Pico W's LED hangs off the wifi coprocessor (a CywPin, which
        # pwmio rejects with TypeError; other non-PWM pins raise
        # ValueError/RuntimeError).  Digital on/off only.
        import digitalio

        _led_out = digitalio.DigitalInOut(board.LED)
        _led_out.direction = digitalio.Direction.OUTPUT

        def set_led(fraction):
            _led_out.value = fraction > 0.0

        LED_MODE = "digital"

elif _impl_name == "micropython":
    import machine

    _motor_pwm = machine.PWM(
        machine.Pin(_MOTOR_GPIO), freq=_PWM_FREQUENCY_HZ, duty_u16=0,
    )

    def set_motor_duty(fraction):
        _motor_pwm.duty_u16(int(fraction * _U16_FULL_SCALE))

    if sys.platform == "rp2":
        _temperature_adc = machine.ADC(4)

        def read_celsius():
            volts = _temperature_adc.read_u16() * (3.3 / _U16_FULL_SCALE)
            return 27.0 - (volts - 0.706) / 0.001721

        SENSOR_SOURCE = "real"
        # Pico W's LED is on the CYW43 chip: digital only.
        _led_pin = machine.Pin("LED", machine.Pin.OUT)

        def set_led(fraction):
            _led_pin.value(1 if fraction > 0.0 else 0)

        LED_MODE = "digital"
    else:
        # esp32-s2 (Lolin S2 mini) has no CPU temperature sensor.
        read_celsius = _synthetic_celsius
        SENSOR_SOURCE = "synthetic"
        _led_pwm = machine.PWM(
            machine.Pin(15), freq=_PWM_FREQUENCY_HZ, duty_u16=0,
        )

        def set_led(fraction):
            _led_pwm.duty_u16(int(fraction * _U16_FULL_SCALE))

        LED_MODE = "pwm"
else:
    # CPython / unknown host: software-only fallback keeps the app
    # importable off-board (verify-demos compiles it under CPython).
    read_celsius = _synthetic_celsius
    SENSOR_SOURCE = "synthetic"

    def set_motor_duty(fraction):
        pass

    def set_led(fraction):
        pass

    LED_MODE = "none"


config = load_runtime_config()
client_id = config.get("mqtt.client_id", "chumicro-sensor-motor-board")
broker = f"{config['mqtt.broker.host']}:{config['mqtt.broker.port']}"
availability_topic = f"demo/{client_id}/availability"
telemetry_topic = f"demo/{client_id}/telemetry"
command_topic = f"demo/{client_id}/motor/set"
state_topic = f"demo/{client_id}/motor/state"

marker("SENSOR_SOURCE", source=SENSOR_SOURCE)
marker("MOTOR_READY", gpio=_MOTOR_GPIO, led=LED_MODE)

wifi = WifiService(WifiConfig.from_config(config))
mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)

# Availability via Last Will: the broker publishes this retained
# "offline" if the board drops without a clean DISCONNECT.  on_connect
# publishes the matching retained "online".
mqtt.set_will(availability_topic, b"offline", qos=1, retain=True)

# Declarative subscription: subscribe() before connect() records the
# command topic in the client's desired set.  The first CONNACK puts it
# on the wire, and every self-heal reconnect replays it, so the app
# declares its inbound shape once here, with no on_connect bookkeeping.
mqtt.subscribe(command_topic, qos=1)

# Progress state at module scope so the callbacks read and write it
# without ceremony.  Small enough that a class would only add noise.
telemetry_sent = 0
commands_applied = 0
current_speed = 0


def on_connect():
    """Connect-time setup, fired once the broker session is up.

    Announces presence with a retained "online", a genuinely
    connect-time publish (it pairs with the Last Will).  The command
    subscription is declared once at startup, not here; the client
    replays it on every reconnect on its own.
    """
    marker("MQTT_CONNECTED", broker=broker, client_id=client_id)
    mqtt.publish(availability_topic, b"online", qos=1, retain=True)


def on_motor_command(topic, payload):
    """Apply an inbound 0-100 speed and echo the applied value retained."""
    global commands_applied, current_speed
    text = (
        payload.decode("utf-8", "replace")
        if isinstance(payload, (bytes, bytearray)) else str(payload)
    )
    try:
        requested = int(text)
    except ValueError:
        marker("MOTOR_REJECTED", payload_hex=text.encode())
        return
    speed = max(0, min(100, requested))
    current_speed = speed
    set_motor_duty(speed / 100.0)
    set_led(speed / 100.0)
    commands_applied += 1
    # State echo closes the loop: a retained value so a late subscriber
    # learns the current speed on its first SUBACK.
    mqtt.publish(state_topic, str(speed).encode(), qos=1, retain=True)
    marker("MOTOR_APPLIED", speed=speed)


def publish_telemetry(now_ms):
    """Publish one QoS-1 JSON sample per call.

    No CONNECTED guard: a sample produced before the broker session is
    up buffers in the client's pre-connect queue and flushes on CONNACK.
    """
    global telemetry_sent
    telemetry_sent += 1
    payload = json.dumps({
        "celsius": round(read_celsius(), 1),
        "speed": current_speed,
        "seq": telemetry_sent,
    }).encode()
    mqtt.publish(telemetry_topic, payload, qos=1)
    marker("TELEMETRY_SENT", seq=telemetry_sent)


def on_wifi_state(_old_state, new_state):
    if new_state == WifiState.CONNECTED:
        marker("WIFI_OK", ip=wifi.ip)
        mqtt.connect()  # link is back: reconnect now (also clears the hold)
    else:
        # WifiService reports link loss as RECONNECTING / FAILED, so any
        # state but CONNECTED means: stop dialing a dead radio.
        mqtt.hold()


mqtt.on_connect = on_connect
mqtt.on_message = on_motor_command
wifi.on_state_change(on_wifi_state)

runner = Runner(
    on_handler_error=lambda entry, error: print(
        "SERVICE_FAULT", entry.service, repr(error),
    ),
)
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_telemetry, period_ms=_TELEMETRY_INTERVAL_MS)


def _demo_complete():
    return (
        telemetry_sent >= _TELEMETRY_TARGET
        and commands_applied >= _COMMAND_TARGET
    )


if not runner.run_until(_demo_complete, timeout_ms=_DEMO_DEADLINE_MS):
    print(
        f"STATUS: FAIL_DEMO_DEADLINE "
        f"telemetry_sent={telemetry_sent} "
        f"commands_applied={commands_applied}",
    )
    raise SystemExit(1)

# Graceful shutdown: a clean disconnect suppresses the Last Will, so
# stop the motor and announce "offline" ourselves, then drain so the
# QoS-1 acks land before the socket closes.
set_motor_duty(0.0)
set_led(0.0)
mqtt.publish(availability_topic, b"offline", qos=1, retain=True)
runner.run_until(timeout_ms=_FLUSH_DRAIN_MS)
mqtt.disconnect()
marker("DEMO_COMPLETE")
