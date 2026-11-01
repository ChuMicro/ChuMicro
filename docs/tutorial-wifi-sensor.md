---
title: "Build a WiFi temperature sensor on CircuitPython or MicroPython, one step at a time"
---

# Build a WiFi temperature sensor

The finished board reads its own temperature every five seconds and publishes each reading over WiFi to an MQTT broker on your laptop.  A button pauses and resumes the readings.  The onboard LED blinks the whole time.  Each message carries a count of how many times the board has started.

Each step below is a complete program.  Save it as `code.py` on the CIRCUITPY drive.  The board runs it until you unplug it.  Each step adds one idea to the program before it, so the program that publishes over MQTT in step 5 still blinks the LED from step 1.

The code is CircuitPython.  Each step ends with the lines that change on MicroPython.

## What you need

- A Raspberry Pi Pico W, or an ESP32-S2 board such as the Lolin S2 Mini, running CircuitPython 10.1 or newer.  MicroPython 1.27 or newer works too.
- A momentary push button and two jumper wires, from step 3 on.
- A laptop on the same WiFi network as the board, with [circup](install.md#circuitpython-circup-and-the-chumicro-bundle) installed and the ChuMicro bundle registered:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
```

Another board works when CircuitPython names its LED `board.LED` and reads its chip's temperature.  CircuitPython reads the sensor on RP2040, RP2350, ESP32-S2, ESP32-S3, ESP32-C3, and ESP32-C6 chips.  On the original ESP32, `microcontroller.cpu.temperature` reads `None`.

## Step 1: Blink without sleeping

Install the timing library:

```bash
circup install chumicro_timing
```

Save this as `code.py`:

```python
import board
import digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

blink = Rate(500, ticks_ms())   # comes due every 500 ms, counting from now

print("Blinking.")

while True:
    now = ticks_ms()
    if blink.due(now):          # True once every 500 ms, False on every other pass
        led.value = not led.value
```

The LED switches on or off every half second.  The console prints one line:

```text
Blinking.
```

`ticks_ms()` reads the board's millisecond clock, like Arduino's `millis()`.  `Rate(500, ticks_ms())` is a timer that comes due every 500 ms, counting from the moment it is made.  `blink.due(now)` answers `True` on the pass where the timer comes due and `False` on every other pass, so the loop never stops to wait.  [Coming from Arduino](coming-from-arduino.md#blink-timesleep-becomes-rate) sets this loop beside `time.sleep()` and Arduino's BlinkWithoutDelay.

**On MicroPython**, build the LED from `machine.Pin` in place of the `board` and `digitalio` lines, and flip it with `led.value(not led.value())`.  Install with mip.  Copy the program to the board as `main.py`, the file MicroPython runs at startup:

```python
from machine import Pin

led = Pin("LED", Pin.OUT)       # Pin(15, Pin.OUT) on a Lolin S2 Mini
```

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
mpremote cp code.py :main.py
```

## Step 2: Read the chip's temperature

`microcontroller` is built into CircuitPython, so this step installs nothing.

```python
import board
import digitalio
import microcontroller
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def read_temperature():
    return microcontroller.cpu.temperature   # the chip's own sensor, in degrees Celsius


blink = Rate(500, ticks_ms())
report = Rate(5000, ticks_ms())   # comes due every 5 seconds

print("Blinking, and reporting every 5 seconds.")

while True:
    now = ticks_ms()
    if blink.due(now):
        led.value = not led.value
    if report.due(now):
        print(f"temperature: {read_temperature():.1f} C")
```

The LED keeps blinking.  A reading prints every five seconds:

```text
Blinking, and reporting every 5 seconds.
temperature: 27.4 C
temperature: 27.6 C
temperature: 27.4 C
```

`microcontroller.cpu.temperature` reads a sensor inside the chip, in degrees Celsius.  The sensor measures the chip, which runs warmer than the room around it.  `read_temperature()` holds the read in one function, so the MicroPython version changes only that function.

`report` is a second `Rate` with its own period.  The loop checks both timers on every pass: the LED changes every 500 ms, and a reading prints every 5000 ms.

**On MicroPython**, drop `import microcontroller` and replace `read_temperature()`.  On a Pi Pico W the sensor sits on an ADC channel.  The conversion below is the RP2040 datasheet's formula, the same formula CircuitPython applies inside `cpu.temperature`:

```python
from machine import ADC

sensor = ADC(ADC.CORE_TEMP)


def read_temperature():
    volts = sensor.read_u16() * 3.3 / 65535
    return 27 - (volts - 0.706) / 0.001721
```

On an ESP32-S2, S3, C3, or C6, `esp32.mcu_temperature()` returns whole degrees Celsius.  The original ESP32 has `esp32.raw_temperature()` in its place, which returns degrees Fahrenheit.

```python
import esp32


def read_temperature():
    return esp32.mcu_temperature()
```

## Step 3: Pause the readings with a button

On a Pico W, wire a momentary button between GP14 and GND, physical pins 19 and 18, side by side.  On a Lolin S2 Mini, wire it between GPIO 14 and a GND pin.  The button library switches on the pin's internal pull-up, so the button is the only part.

```bash
circup install chumicro_buttons
```

```python
import board
import digitalio
import microcontroller
from chumicro_buttons import Button
from chumicro_timing import Rate, ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)   # board.IO14 on a Lolin S2 Mini
reporting = True


def read_temperature():
    return microcontroller.cpu.temperature


blink = Rate(500, ticks_ms())
report = Rate(5000, ticks_ms())

print("Press the button to pause or resume the readings.")

while True:
    now = ticks_ms()
    button.check(now)                # collect what the button did since the last pass
    if button.just_pressed:          # True on one pass per press
        reporting = not reporting
        print("reporting resumed" if reporting else "reporting paused")
    if blink.due(now):
        led.value = not led.value
    if report.due(now) and reporting:
        print(f"temperature: {read_temperature():.1f} C")
```

One press stops the readings.  The next press brings them back.  The LED blinks throughout:

```text
Press the button to pause or resume the readings.
temperature: 27.4 C
reporting paused
reporting resumed
temperature: 26.9 C
```

`Button(pin=board.GP14, ticks=ticks)` watches the pin.  `ticks=ticks` hands it the clock from `chumicro_timing`, which it times presses with.  `button.check(now)` collects what the button did since the last pass and never waits.  `button.just_pressed` is `True` on exactly one pass per press, however long the button is held.  On CircuitPython the firmware's `keypad` module watches the pin in the background, so a tap that starts and ends between two passes still counts.  The [buttons guide](https://chumicro.com/ChuMicro/buttons/stable/guide/) covers long presses, double clicks, and several buttons.

**On MicroPython**, pass a `machine.Pin`.  `Pin(14)` is GP14 on a Pico W and GPIO 14 on a Lolin S2 Mini:

```python
button = Button(pin=Pin(14), ticks=ticks)
```

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_buttons
```

## Step 4: Join WiFi on a Runner

WiFi takes seconds to join and can drop at any moment, so it needs a turn on every pass, forever.  A `Runner` from `chumicro_runner` holds every job in the program and gives each one its turn: the blink, the report, the button, and now WiFi.

```bash
circup install chumicro_runner chumicro_wifi
```

Type your network's name and password into `WIFI_SSID` and `WIFI_PASSWORD`.  Delete any `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD` lines from the board's `settings.toml`.  Those lines make CircuitPython join WiFi on its own.  CircuitPython then [fights the WiFi library for the radio](troubleshooting/wifi-wont-connect.md#wifi-drops-or-fights-itself-on-circuitpython).

```python
import board
import digitalio
import microcontroller
from chumicro_buttons import Button
from chumicro_runner import Runner
from chumicro_timing import ticks
from chumicro_wifi import WifiConfig, WifiService

WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)   # board.IO14 on a Lolin S2 Mini
wifi = WifiService(WifiConfig(ssid=WIFI_SSID, password=WIFI_PASSWORD))
reporting = True


def read_temperature():
    return microcontroller.cpu.temperature


def blink(now_ms):
    led.value = not led.value


def report(now_ms):
    if reporting:
        print(f"temperature: {read_temperature():.1f} C")


def toggle_reporting():
    global reporting
    reporting = not reporting
    print("reporting resumed" if reporting else "reporting paused")


def show_wifi(old_state, new_state):
    print("wifi:", old_state, "->", new_state)


def show_error(task, error):
    print("job failed:", repr(error))


button.on_press = toggle_reporting
wifi.on_state_change(show_wifi)

runner = Runner(on_handler_error=show_error)
runner.add(wifi)                              # joins, and rejoins after a drop
runner.add(button, period_ms=20)              # looks at the button every 20 ms
runner.add_periodic(blink, period_ms=500)
runner.add_periodic(report, period_ms=5000)

while True:
    now_ms = runner.tick()    # run every job that is due
    runner.wait(now_ms)       # sleep until the next one is due
```

The board joins your network, then carries on as before:

```text
wifi: disconnected -> connecting
wifi: connecting -> connected
temperature: 27.4 C
reporting paused
reporting resumed
temperature: 26.9 C
```

The loop at the bottom is now two lines.  `runner.tick()` runs every job that is due and returns the time it used.  `runner.wait(now_ms)` sleeps until the next job is due, so the board rests between blinks.

Each `if` from step 3 is now a function.  Each `Rate` is now an `add_periodic` line that calls its function on time: `blink` every 500 ms and `report` every 5000 ms.  `runner.add(button, period_ms=20)` has the runner look at the button every 20 ms.  `button.on_press = toggle_reporting` names the function to call for each press.  `toggle_reporting` changes `reporting`, a variable from the top of the file, so it says `global reporting` first.

`runner.add(wifi)` adds the WiFi service.  It joins your network and rejoins after a drop.  The wait between failed tries starts at 1 second and doubles up to a minute.  `wifi.on_state_change(show_wifi)` calls `show_wifi` on each change of state.

`Runner(on_handler_error=show_error)` calls `show_error` with any exception a job raises.  The runner catches the exception and keeps the other jobs running.  Without this callback it prints nothing.

On CircuitPython each join attempt holds the whole loop for up to 15 seconds, because the firmware's connect call waits until the board joins or gives up.  The LED pauses during an attempt and blinks again between attempts.  [Everything freezes while a CircuitPython board connects](troubleshooting/wifi-wont-connect.md#everything-freezes-for-up-to-15-seconds-while-a-circuitpython-board-connects) explains the wait and how to shorten it.

**On MicroPython**, keep the MicroPython lines from steps 1 to 3, and flip the LED in `blink` with `led.value(not led.value())`.  The join runs in the background there, so the LED blinks straight through it.  Install with mip:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner github:ChuMicro/ChuMicro-Bundle/chumicro_wifi
```

## Step 5: Publish each reading over MQTT

MQTT is a publish and subscribe protocol.  The board sends each reading to a broker, a small server on your laptop, under a topic name, `tutorial/temperature`.  Every program subscribed to that topic gets a copy.

### Run a broker on your laptop

1. Install Mosquitto: `brew install mosquitto` on a Mac, or `sudo apt install mosquitto mosquitto-clients` on Debian or Ubuntu.  The Linux package starts a broker that answers only the laptop itself.  Stop it with `sudo systemctl stop mosquitto`.
2. Save these two lines as `mosquitto.conf`.  They let the board connect without a password:

    ```text
    listener 1883
    allow_anonymous true
    ```

3. Start the broker and leave it running.  `-v` prints each connection and message:

    ```bash
    mosquitto -c mosquitto.conf -v
    ```

4. In a second terminal, print every message under `tutorial/`:

    ```bash
    mosquitto_sub -h localhost -t 'tutorial/#' -v
    ```

5. Find your laptop's IP address on the WiFi network.  `ipconfig getifaddr en0` prints it on a Mac, and `hostname -I` on Linux.

### Publish from the board

```bash
circup install chumicro_mqtt
```

Set `BROKER_HOST` to your laptop's IP address:

```python
import board
import digitalio
import microcontroller
from chumicro_buttons import Button
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_timing import ticks
from chumicro_wifi import WifiConfig, WifiService, WifiState

WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"
BROKER_HOST = "192.168.1.20"   # your laptop's IP address
TOPIC = "tutorial/temperature"

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)   # board.IO14 on a Lolin S2 Mini
wifi = WifiService(WifiConfig(ssid=WIFI_SSID, password=WIFI_PASSWORD))
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": BROKER_HOST, "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)
reporting = True


def read_temperature():
    return microcontroller.cpu.temperature


def blink(now_ms):
    led.value = not led.value


def report(now_ms):
    if not reporting:
        return
    reading = f"{read_temperature():.1f}"
    if mqtt.state == ProtocolState.CONNECTED:
        mqtt.publish(TOPIC, reading)
        print("published", reading)
    else:
        print("skipped", reading, "(mqtt " + mqtt.state + ")")


def toggle_reporting():
    global reporting
    reporting = not reporting
    print("reporting resumed" if reporting else "reporting paused")


def show_wifi(old_state, new_state):
    print("wifi:", old_state, "->", new_state)
    if new_state == WifiState.CONNECTED:
        mqtt.connect()    # WiFi is up: dial the broker
    else:
        mqtt.hold()       # WiFi is down: stop dialing until it comes back


def show_mqtt_connected():
    print("mqtt: connected to", BROKER_HOST)


def show_mqtt_lost():
    print("mqtt: lost the broker:", mqtt.last_error)


def show_error(task, error):
    print("job failed:", repr(error))


button.on_press = toggle_reporting
wifi.on_state_change(show_wifi)
mqtt.on_connect = show_mqtt_connected
mqtt.on_disconnect = show_mqtt_lost

runner = Runner(on_handler_error=show_error)
runner.add(wifi)
runner.add(mqtt)                              # dials, sends, and keeps the connection alive
runner.add(button, period_ms=20)
runner.add_periodic(blink, period_ms=500)
runner.add_periodic(report, period_ms=5000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

The board prints each reading as it publishes it:

```text
wifi: disconnected -> connecting
wifi: connecting -> connected
mqtt: connected to 192.168.1.20
published 27.4
published 27.6
published 27.4
```

`mosquitto_sub` prints the same readings on the laptop:

```text
tutorial/temperature 27.4
tutorial/temperature 27.6
tutorial/temperature 27.4
```

`MQTTClient.from_config(...)` builds a client from a dict holding the broker's address and port.  `radio=wifi.adapter.radio` hands it the radio the WiFi service drives, which CircuitPython needs to open a connection.

`show_wifi` now steers the client too.  When WiFi connects, `mqtt.connect()` starts dialing the broker.  When WiFi drops, `mqtt.hold()` stops the client dialing through a dead radio until WiFi is back.

`runner.add(mqtt)` gives the client its turn on each pass.  Each turn does one small step, such as dialing, sending a message, or keeping the connection alive, and returns.  The LED and the button keep working while a message is on its way.  `report` publishes only while `mqtt.state` is `ProtocolState.CONNECTED`.  A reading taken while the broker is away prints as `skipped`.

Stop the broker with Ctrl-C while the board runs.  The board prints `mqtt: lost the broker`, keeps blinking, and skips readings.  Start the broker again, and the client reconnects by itself.  The wait between its attempts starts at 1 second and doubles up to a minute, so after a short outage the client is back within seconds:

```text
published 27.4
mqtt: lost the broker: broker closed connection
skipped 26.9 (mqtt failed)
mqtt: connected to 192.168.1.20
published 26.5
```

**On MicroPython**, the program takes the changes from steps 1 to 4 and nothing more.  `wifi.adapter.radio` is `None` there, because MicroPython opens connections without a radio object.  Install with mip:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
```

## Step 6: Count how many times the board has started

Each message now carries a count of how many times the board has started, kept in storage that survives a power cut.

```bash
circup install chumicro_kvstore
```

```python
import board
import digitalio
import microcontroller
from chumicro_buttons import Button
from chumicro_kvstore import KVStore
from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_runner import Runner
from chumicro_timing import ticks
from chumicro_wifi import WifiConfig, WifiService, WifiState

WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"
BROKER_HOST = "192.168.1.20"   # your laptop's IP address
TOPIC = "tutorial/temperature"

store = KVStore()                                # a dict the board keeps through a reset
boot_count = store.get("boot_count", 0) + 1
store["boot_count"] = boot_count
store.commit()                                   # write the new count to the board
print("boot", boot_count)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)   # board.IO14 on a Lolin S2 Mini
wifi = WifiService(WifiConfig(ssid=WIFI_SSID, password=WIFI_PASSWORD))
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": BROKER_HOST, "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)
reporting = True


def read_temperature():
    return microcontroller.cpu.temperature


def blink(now_ms):
    led.value = not led.value


def report(now_ms):
    if not reporting:
        return
    message = f"boot={boot_count} temperature={read_temperature():.1f}"
    if mqtt.state == ProtocolState.CONNECTED:
        mqtt.publish(TOPIC, message)
        print("published", message)
    else:
        print("skipped", message, "(mqtt " + mqtt.state + ")")


def toggle_reporting():
    global reporting
    reporting = not reporting
    print("reporting resumed" if reporting else "reporting paused")


def show_wifi(old_state, new_state):
    print("wifi:", old_state, "->", new_state)
    if new_state == WifiState.CONNECTED:
        mqtt.connect()
    else:
        mqtt.hold()


def show_mqtt_connected():
    print("mqtt: connected to", BROKER_HOST)


def show_mqtt_lost():
    print("mqtt: lost the broker:", mqtt.last_error)


def show_error(task, error):
    print("job failed:", repr(error))


button.on_press = toggle_reporting
wifi.on_state_change(show_wifi)
mqtt.on_connect = show_mqtt_connected
mqtt.on_disconnect = show_mqtt_lost

runner = Runner(on_handler_error=show_error)
runner.add(wifi)
runner.add(mqtt)
runner.add(button, period_ms=20)
runner.add_periodic(blink, period_ms=500)
runner.add_periodic(report, period_ms=5000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Start the board two more times, by unplugging it and plugging it back in or by saving `code.py` again.  The third start prints:

```text
boot 3
wifi: disconnected -> connecting
wifi: connecting -> connected
mqtt: connected to 192.168.1.20
published boot=3 temperature=27.4
published boot=3 temperature=27.6
```

`mosquitto_sub` prints the messages from all three starts:

```text
tutorial/temperature boot=1 temperature=27.4
tutorial/temperature boot=1 temperature=27.6
tutorial/temperature boot=2 temperature=27.4
tutorial/temperature boot=2 temperature=27.6
tutorial/temperature boot=3 temperature=27.4
tutorial/temperature boot=3 temperature=27.6
```

`KVStore()` opens a small dict that the board keeps through a reset or a power cut.  On CircuitPython the dict lives in `microcontroller.nvm`, a few kilobytes of memory set apart from the CIRCUITPY drive.  `store.get("boot_count", 0)` reads the saved count, or 0 on the very first start.  Assigning to `store["boot_count"]` changes the copy in memory.  `store.commit()` writes that copy to the board.

The count goes up each time `code.py` starts: a power cycle, a press of the reset button on a board that has one, or a saved file on CIRCUITPY, which restarts the program.  Each `commit()` writes flash, which wears out after many writes, so this program commits once per start and never per reading.  [Saving](https://chumicro.com/ChuMicro/kvstore/stable/guide/#saving-commit-and-commit_if_changed) in the kvstore guide covers saving on a timer.

**On MicroPython**, the store code is the same.  It saves to the file `/_chu_kv.msgpack` on a Pico W, and to the ESP32's built-in NVS storage on an ESP32 board.  Install with mip:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore
```

## Where to go next

- [Wiring WiFi credentials](wiring-wifi-credentials.md) moves the WiFi password and the broker address out of `code.py` into a `secrets.toml` that git ignores.
- [Start here](start-here.md) sets up a workspace whose `deploy` command copies a project and the libraries it imports onto the board in one step.
- The [MQTT guide](https://chumicro.com/ChuMicro/mqtt/stable/guide/) adds `subscribe()` and `on_message`, so the board can take commands from `mosquitto_pub` on the laptop.
- The [runner guide](https://chumicro.com/ChuMicro/runner/stable/guide/) goes further into `tick()` and `wait()`.
- [`mqtt_sensor_motor`](https://github.com/ChuMicro/ChuMicro/tree/main/demos/mqtt_sensor_motor) is a larger project on the same loop: a sensor and a fan, talking MQTT.
