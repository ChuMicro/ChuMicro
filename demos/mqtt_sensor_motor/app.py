"""A temperature-controlled fan, driven over MQTT.

This is the file that runs on the board.  Every two seconds it reads the
chip's own temperature and publishes it to an MQTT broker on your
laptop.  When a speed from 0 to 100 arrives on its command topic, it
sets the motor to that speed, lights the onboard LED while the motor
runs, and publishes the speed back so the sender can see it took effect.

No motor is needed on the bench.  The motor is a PWM signal on GPIO16,
the pin a fan or pump driver's signal wire plugs into, and the LED shows
whether it is running.

Two things worth noticing:

* **The subscription is declared once, at startup.**  The client sends
  it when it connects and sends it again after any reconnect, so
  nothing below has to keep track of that.
* **The board says whether it is alive.**  ``set_will(...)`` leaves a
  retained ``offline`` with the broker, published if this board falls
  off the network, and ``on_connect`` publishes the matching ``online``.

What the board prints::

      waiting for the broker...
    WIFI_OK ip=10.0.0.42
    MQTT_CONNECTED broker=10.0.0.5:1883 client_id=chumicro-sensor-motor-board
      reading 1: 23.4 C, fan at 0%
      reading 2: 23.5 C, fan at 0%
      reading 3: 23.4 C, fan at 0%
    MOTOR_APPLIED speed=75
      reading 4: 23.6 C, fan at 75%
    MOTOR_APPLIED speed=0
    DEMO_COMPLETE
      reading 5: 23.5 C, fan at 0%
      reading 6: 23.4 C, fan at 0%

The UPPERCASE lines are for the script on your laptop, which reads them
to follow how far the board got.  They are ordinary ``print`` calls in a
``NAME key=value`` shape, and a value may not contain a space or an
``=``.  The indented lines are for you.

Try it: change ``READING_EVERY_MS`` and run the demo again, or wire a
real fan through a motor driver board to GPIO16.
"""

import json
import math
import sys

from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

READING_EVERY_MS = 2_000
PWM_FREQUENCY_HZ = 1_000

# The board-specific part: the temperature sensor, the motor pin, and the
# LED.  The motor is on GPIO16, labelled GP16 on a Pico W and IO16 on a
# Lolin S2 mini.  Everything after this block is the same on every board.
if sys.implementation.name == "circuitpython":
    import board
    import digitalio
    import microcontroller
    import pwmio

    motor = pwmio.PWMOut(microcontroller.pin.GPIO16, frequency=PWM_FREQUENCY_HZ)
    led = digitalio.DigitalInOut(board.LED)
    led.switch_to_output()

    def read_celsius():
        return microcontroller.cpu.temperature

    def set_speed(percent):
        motor.duty_cycle = percent * 65535 // 100
        led.value = percent > 0

else:  # MicroPython
    import machine

    motor = machine.PWM(machine.Pin(16), freq=PWM_FREQUENCY_HZ, duty_u16=0)

    if sys.platform == "rp2":
        # Pico W: the chip's temperature sensor is ADC channel 4.
        led = machine.Pin("LED", machine.Pin.OUT)
        sensor = machine.ADC(4)

        def read_celsius():
            volts = sensor.read_u16() * 3.3 / 65535
            return 27 - (volts - 0.706) / 0.001721

    else:
        # Lolin S2 mini: this demo makes up a reading here instead, a slow
        # wave between 17 and 33 C.
        led = machine.Pin(15, machine.Pin.OUT)

        def read_celsius():
            return 25 + 8 * math.sin(ticks_ms() / 5000)

    def set_speed(percent):
        motor.duty_u16(percent * 65535 // 100)
        led.value(percent > 0)


config = load_runtime_config()
client_id = config.get("mqtt.client_id", "chumicro-sensor-motor-board")
broker = f"{config['mqtt.broker.host']}:{config['mqtt.broker.port']}"
availability_topic = f"demo/{client_id}/availability"
telemetry_topic = f"demo/{client_id}/telemetry"
command_topic = f"demo/{client_id}/motor/set"
state_topic = f"demo/{client_id}/motor/state"

wifi = WifiService(WifiConfig.from_config(config))
mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)

# If this board drops off the network, the broker publishes this retained
# "offline" for it.  on_connect publishes the matching "online".
mqtt.set_will(availability_topic, b"offline", qos=1, retain=True)

# Declared once.  The client subscribes on every connect by itself.
mqtt.subscribe(command_topic, qos=1)

speed = 0
readings_sent = 0
commands_applied = 0


def on_connect():
    """Runs each time the broker session comes up: tell everyone the board is online."""
    print(f"MQTT_CONNECTED broker={broker} client_id={client_id}")
    mqtt.publish(availability_topic, b"online", qos=1, retain=True)


def on_motor_command(_topic, payload):
    """Runs when a speed arrives: apply it, then publish it back."""
    global speed, commands_applied
    text = payload.decode("utf-8", "replace")
    try:
        requested = int(text)
    except ValueError:
        print(f"  ignored {text!r}: send a whole number from 0 to 100")
        return
    speed = max(0, min(100, requested))
    set_speed(speed)
    # Retained, so anything that subscribes later still learns the speed.
    mqtt.publish(state_topic, str(speed), qos=1, retain=True)
    print(f"MOTOR_APPLIED speed={speed}")
    commands_applied += 1
    if commands_applied == 2:  # the laptop script sends 75, then 0
        print("DEMO_COMPLETE")


def publish_reading(now_ms):
    """Runs every two seconds: publish the temperature while the broker is connected."""
    global readings_sent
    if mqtt.state != ProtocolState.CONNECTED:
        print("  waiting for the broker...")
        return
    readings_sent += 1
    celsius = round(read_celsius(), 1)
    payload = json.dumps({"celsius": celsius, "speed": speed, "seq": readings_sent})
    mqtt.publish(telemetry_topic, payload, qos=1)
    print(f"  reading {readings_sent}: {celsius} C, fan at {speed}%")


def on_wifi_state(_old, new):
    """Connect to the broker whenever wifi comes up; stop dialing while it is down."""
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        mqtt.connect()
    else:
        mqtt.hold()


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


mqtt.on_connect = on_connect
mqtt.on_message = on_motor_command
wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(publish_reading, period_ms=READING_EVERY_MS)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
