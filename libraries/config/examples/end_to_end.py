"""End-to-end demo of ``chumicro-config`` — both library-author and user-app patterns.

Runs on CPython, MicroPython, and CircuitPython.  Self-contained:
constructs an in-memory config, exercises the section loader, then
shows how a real user app would wire everything once
``/runtime_config.msgpack`` is on device.

Example output::

    Library-author pattern: WifiConfig.from_dict(...) → ssid='HomeNet', timeout=15000
    User-app pattern: 3 sections wired (wifi, mqtt, app)
    Missing-key error caught: required config key 'password' is missing
    Wrong-type error caught: config section must be a dict, got int
"""

from chumicro_config import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    load_section,
)

# ---------------------------------------------------------------------------
# Library-author pattern — every consumer library defines a typed Config
# class with a `from_dict` classmethod that calls `load_section`.
# ---------------------------------------------------------------------------


class WifiConfig:
    """Stand-in for what `chumicro-wifi` will ship."""

    def __init__(self, ssid, password, hostname=None, connect_timeout_ms=15_000):
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms

    @classmethod
    def from_dict(cls, data):
        return load_section(
            cls,
            data,
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )


class MqttConfig:
    """Stand-in for what `chumicro-mqtt` will ship."""

    def __init__(self, broker, port=1883, client_id=None):
        self.broker = broker
        self.port = port
        self.client_id = client_id

    @classmethod
    def from_dict(cls, data):
        return load_section(
            cls,
            data,
            required=("broker",),
            optional={"port": 1883, "client_id": None},
        )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


# A typical merged runtime config — what the deployer would write to
# /runtime_config.msgpack at deploy time.  In production:
#
#     from chumicro_config import load_runtime_config
#     config = load_runtime_config()
#
# but for this self-contained demo we just inline the dict.
config = {
    "wifi": {"ssid": "HomeNet", "password": "secret"},
    "mqtt": {"broker": "mqtt.local", "client_id": "back-porch"},
    "app": {"sample_period_ms": 5000},
}


# 1. Library-author pattern: the library wraps load_section so users
#    don't think about required/optional themselves.
wifi = WifiConfig.from_dict(config["wifi"])
print(
    f"Library-author pattern: WifiConfig.from_dict(...) → "
    f"ssid={wifi.ssid!r}, timeout={wifi.connect_timeout_ms}"
)


# 2. User-app pattern: explicitly wire each section to its library.
mqtt = MqttConfig.from_dict(config["mqtt"])
app_sample_period_ms = config["app"]["sample_period_ms"]
print("User-app pattern: 3 sections wired (wifi, mqtt, app)")


# 3. Missing required key → MissingConfigKey (subclass of ConfigError).
try:
    WifiConfig.from_dict({"ssid": "incomplete"})  # missing password
except MissingConfigKey as error:
    print(f"Missing-key error caught: {error}")


# 4. Section value of the wrong type → InvalidConfigType.
try:
    WifiConfig.from_dict(42)  # not a dict
except InvalidConfigType as error:
    print(f"Wrong-type error caught: {error}")


# 5. Both targeted exceptions also subclass ConfigError, so a single
#    catch-all works for callers that don't need to discriminate.
try:
    WifiConfig.from_dict({})
except ConfigError:
    pass  # caller handles either failure mode uniformly
