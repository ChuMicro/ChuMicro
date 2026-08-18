"""A temperature-controlled fan, driven over MQTT.

This is the file that runs on the board.  It reads the chip's own
temperature sensor, publishes a reading every two seconds, and spins a
motor at whatever speed the broker tells it to.  The motor is a PWM
signal on one GPIO pin, mirrored onto the onboard LED so you can see the
speed on a bench with nothing wired up.

This is the biggest demo here, and it is the one shaped most like a real
device.  Three things are worth reading for:

* **Publishing does not check whether it is connected.**  Look at
  ``publish_telemetry``: it just publishes.  If the broker session is not
  up yet, the client holds the message and sends it once it is.
* **The subscription is declared once, at startup.**  Not inside a
  connect callback.  The client remembers it, puts it on the wire when it
  connects, and puts it back after any reconnect, so nothing here has to
  keep track of that.
* **The board announces whether it is alive.**  ``set_will(...)`` leaves
  a message with the broker to publish if this board falls off the
  network, and the matching ``online`` goes out on connect.  Anything
  watching the topic knows the difference between "quiet" and "gone".

The command path is a closed loop: a speed arrives, gets clamped to
0-100, is applied to the motor, and is echoed back on a state topic so
whoever sent it can see it took effect.

What you will see::

    SENSOR_SOURCE source=rp2-onchip
    MOTOR_READY gpio=16 led=pwm
    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=10.0.0.5:1883 client_id=chumicro-sensor-motor
    TELEMETRY_SENT seq=1
    MOTOR_APPLIED speed=75
    TELEMETRY_SENT seq=2
    MOTOR_APPLIED speed=0
    TELEMETRY_SENT seq=3
    DEMO_COMPLETE

Nothing stops after that.  The loop goes on turning, the way a board
program does, and the script on your laptop closes the connection once
it has seen what it came for.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
"""

import json
import math
import sys

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

#: A general-purpose GPIO broken out on both sweep form factors and free
#: of any onboard function: Pico W ``GP16`` and Lolin S2 mini ``IO16``
#: (labelled D4).  A real fan/pump ESC's signal wire goes here.
MOTOR_GPIO = 16
PWM_FREQUENCY_HZ = 1_000
#: 16-bit full scale shared by CircuitPython ``duty_cycle``, MicroPython
#: ``duty_u16``, and the rp2 ADC's ``read_u16`` (one honest constant).
U16_FULL_SCALE = 65_535

TELEMETRY_INTERVAL_MS = 2_000
#: The host driver needs three telemetry samples and two motor commands
#: (speed 75 then 0) to see the full round trip; completion gates on both.
TELEMETRY_TARGET = 3
COMMAND_TARGET = 2

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
        getattr(microcontroller.pin, f"GPIO{MOTOR_GPIO}"),
        frequency=PWM_FREQUENCY_HZ,
        duty_cycle=0,
    )

    def set_motor_duty(fraction):
        _motor_pwm.duty_cycle = int(fraction * U16_FULL_SCALE)

    try:
        _led_pwm = pwmio.PWMOut(
            board.LED, frequency=PWM_FREQUENCY_HZ, duty_cycle=0,
        )

        def set_led(fraction):
            _led_pwm.duty_cycle = int(fraction * U16_FULL_SCALE)

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
        machine.Pin(MOTOR_GPIO), freq=PWM_FREQUENCY_HZ, duty_u16=0,
    )

    def set_motor_duty(fraction):
        _motor_pwm.duty_u16(int(fraction * U16_FULL_SCALE))

    if sys.platform == "rp2":
        _temperature_adc = machine.ADC(4)

        def read_celsius():
            volts = _temperature_adc.read_u16() * (3.3 / U16_FULL_SCALE)
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
            machine.Pin(15), freq=PWM_FREQUENCY_HZ, duty_u16=0,
        )

        def set_led(fraction):
            _led_pwm.duty_u16(int(fraction * U16_FULL_SCALE))

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

print(f"SENSOR_SOURCE source={SENSOR_SOURCE}")
print(f"MOTOR_READY gpio={MOTOR_GPIO} led={LED_MODE}")

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


def announce_if_done():
    """Say so once both halves have happened.  Either one can be last."""
    if telemetry_sent >= TELEMETRY_TARGET and commands_applied >= COMMAND_TARGET:
        print("DEMO_COMPLETE")


def on_connect():
    """Connect-time setup, fired once the broker session is up.

    Announces presence with a retained "online", a genuinely
    connect-time publish (it pairs with the Last Will).  The command
    subscription is declared once at startup, not here; the client
    replays it on every reconnect on its own.
    """
    print(f"MQTT_CONNECTED broker={broker} client_id={client_id}")
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
        print(f"MOTOR_REJECTED payload_hex={text.encode().hex()}")
        return
    speed = max(0, min(100, requested))
    current_speed = speed
    set_motor_duty(speed / 100.0)
    set_led(speed / 100.0)
    commands_applied += 1
    # State echo closes the loop: a retained value so a late subscriber
    # learns the current speed on its first SUBACK.
    mqtt.publish(state_topic, str(speed).encode(), qos=1, retain=True)
    print(f"MOTOR_APPLIED speed={speed}")
    announce_if_done()


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
    print(f"TELEMETRY_SENT seq={telemetry_sent}")
    announce_if_done()


def on_wifi_state(_old_state, new_state):
    if new_state == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        mqtt.connect()  # link is back: reconnect now (also clears the hold)
    else:
        # WifiService reports link loss as RECONNECTING / FAILED, so any
        # state but CONNECTED means: stop dialing a dead radio.
        mqtt.hold()


mqtt.on_connect = on_connect
mqtt.on_message = on_motor_command
wifi.on_state_change(on_wifi_state)

def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_telemetry, period_ms=TELEMETRY_INTERVAL_MS)


# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
