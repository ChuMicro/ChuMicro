"""Look up settings by name, build a settings object from them, and use it.

A ChuMicro project keeps its settings (the wifi network, the broker address,
how often to take a reading) in one file on the board,
``/runtime_config.msgpack``.  Every setting has a dotted name such as
``wifi.ssid`` or ``sensor.period_ms``.  This example builds the same lookup
object from a dict written in this file, so it runs without that file, and:

1. reads single settings with ``config.get``,
2. builds a ``SensorConfig`` object from every ``sensor.*`` setting with
   ``load_section``,
3. shows the error you get when a required setting is missing,
4. takes a pretend reading every ``sensor.period_ms`` milliseconds, forever.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_config``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config``.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output::

    wifi.ssid = HomeNet
    mqtt.broker.host = not set
    sensor: name=back-porch period_ms=2000 units=C
    Missing setting: required config key 'sensor.name' is missing
    back-porch reading 1 (C)
    back-porch reading 2 (C)
    back-porch reading 3 (C)

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_config import MissingConfigKey, RuntimeConfig, load_section

# On a board deployed with chumicro-workspace, read the real settings file:
#
#     from chumicro_config import load_runtime_config
#     config = load_runtime_config()
#
# This example builds the same kind of object from a dict instead.
config = RuntimeConfig({
    "wifi.ssid": "HomeNet",
    "sensor.name": "back-porch",
    "sensor.period_ms": 2000,
})


class SensorConfig:
    """Settings for one sensor, built from the ``sensor.*`` keys."""

    def __init__(self, name, period_ms=5000, units="C"):
        self.name = name
        self.period_ms = period_ms
        self.units = units

    @classmethod
    def from_config(cls, config):
        # load_section reads sensor.name, sensor.period_ms, and sensor.units,
        # then calls SensorConfig(name=..., period_ms=..., units=...).
        return load_section(
            cls,
            config,
            prefix="sensor",
            required=("name",),
            optional={"period_ms": 5000, "units": "C"},
        )


# 1. Read single settings.  get() returns the default when a key is absent.
print(f"wifi.ssid = {config.get('wifi.ssid')}")
print(f"mqtt.broker.host = {config.get('mqtt.broker.host', 'not set')}")

# 2. Build one object from every sensor.* setting.  units was not set,
#    so it takes the default "C".
sensor = SensorConfig.from_config(config)
print(f"sensor: name={sensor.name} period_ms={sensor.period_ms} units={sensor.units}")

# 3. A required setting that is missing raises MissingConfigKey.
try:
    SensorConfig.from_config(RuntimeConfig({"sensor.period_ms": 1000}))
except MissingConfigKey as error:
    print(f"Missing setting: {error}")

# 4. Use the settings: take a pretend reading every period_ms, forever.
reading_number = 0
while True:
    reading_number += 1
    print(f"{sensor.name} reading {reading_number} ({sensor.units})")
    time.sleep(sensor.period_ms / 1000)
