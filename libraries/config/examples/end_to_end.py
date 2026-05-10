"""End-to-end demo of ``chumicro-config`` — both library-author and user-app patterns.

Runs on CPython, MicroPython, and CircuitPython.  Self-contained:
constructs an in-memory flat-key config, exercises the section
loader, then shows how a real user app would wire everything once
``/runtime_config.msgpack`` is on device.

Example output::

    Library-author pattern: WifiConfig.from_config(...) → ssid='HomeNet', timeout=15000
    User-app pattern: 3 sections wired (wifi, mqtt, app)
    Missing-key error caught: required config key 'wifi.password' is missing
    Wrong-type error caught: load_section requires a RuntimeConfig or dict, got int
"""

from chumicro_config import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    load_section,
)

# Library-author pattern — every consumer library defines a typed
# Config class with a `from_config` classmethod that calls
# `load_section` against the deployer's flat-key RuntimeConfig.


class WifiConfig:
    """Stand-in for what `chumicro-wifi` ships."""

    def __init__(self, ssid, password, hostname=None, connect_timeout_ms=15_000):
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms

    @classmethod
    def from_config(cls, config):
        return load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )


class MqttConfig:
    """Stand-in for what `chumicro-mqtt` ships."""

    def __init__(self, broker, port=1883, client_id=None):
        self.broker = broker
        self.port = port
        self.client_id = client_id

    @classmethod
    def from_config(cls, config):
        return load_section(
            cls,
            config,
            prefix="mqtt",
            required=("broker",),
            optional={"port": 1883, "client_id": None},
        )


# A typical merged runtime config — what the deployer writes to
# /runtime_config.msgpack at deploy time.  Flat dotted keys are the
# wire shape every consumer library reads from.  In production:
#
#     from chumicro_config import load_runtime_config
#     config = load_runtime_config()
#
# but for this self-contained demo we just inline the dict.
config = {
    "wifi.ssid": "HomeNet",
    "wifi.password": "secret",
    "mqtt.broker": "mqtt.local",
    "mqtt.client_id": "back-porch",
    "app.sample_period_ms": 5000,
}


# 1. Library-author pattern: the library wraps load_section so users
#    don't think about prefix / required / optional themselves.
wifi = WifiConfig.from_config(config)
print(
    f"Library-author pattern: WifiConfig.from_config(...) → "
    f"ssid={wifi.ssid!r}, timeout={wifi.connect_timeout_ms}"
)


# 2. User-app pattern: explicitly wire each section to its library.
mqtt = MqttConfig.from_config(config)
app_sample_period_ms = config["app.sample_period_ms"]
print("User-app pattern: 3 sections wired (wifi, mqtt, app)")


# 3. Missing required key → MissingConfigKey (subclass of ConfigError).
try:
    WifiConfig.from_config({"wifi.ssid": "incomplete"})  # missing wifi.password
except MissingConfigKey as error:
    print(f"Missing-key error caught: {error}")


# 4. Config of the wrong type → InvalidConfigType.
try:
    WifiConfig.from_config(42)  # not a RuntimeConfig / dict
except InvalidConfigType as error:
    print(f"Wrong-type error caught: {error}")


# 5. Both targeted exceptions also subclass ConfigError, so a single
#    catch-all works for callers that don't need to discriminate.
try:
    WifiConfig.from_config({})  # missing both required keys
except ConfigError:
    pass
