"""Compare msgpack and JSON size for the same data.

Shows why msgpack is a better fit than JSON for storing settings in
constrained byte buffers like NVM or sleep memory.  Integer keys and
binary encoding produce significantly smaller output.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    msgpack with int keys : 46 bytes
    JSON with int keys    : 82 bytes
    JSON with string keys : 109 bytes
    msgpack is 44% smaller than JSON (int keys)
    msgpack is 58% smaller than JSON (string keys)
"""

import json

from chumicro_msgpack import packb

# Typical device settings stored in NVM or sleep memory.
settings_int_keys = {
    0: "MyNetwork",
    1: "secret123",
    2: "lamp",
    3: "192.168.1.100",
    4: True,
}

# The same data with human-readable string keys.
settings_str_keys = {
    "ssid": "MyNetwork",
    "password": "secret123",
    "name": "lamp",
    "broker": "192.168.1.100",
    "configured": True,
}

msgpack_size = len(packb(settings_int_keys))
json_int_size = len(json.dumps(settings_int_keys))
json_str_size = len(json.dumps(settings_str_keys))

print(f"msgpack with int keys : {msgpack_size} bytes")
print(f"JSON with int keys    : {json_int_size} bytes")
print(f"JSON with string keys : {json_str_size} bytes")

# Show the percentage savings.
savings_int = (1 - msgpack_size / json_int_size) * 100
savings_str = (1 - msgpack_size / json_str_size) * 100
print(f"msgpack is {savings_int:.0f}% smaller than JSON (int keys)")
print(f"msgpack is {savings_str:.0f}% smaller than JSON (string keys)")

