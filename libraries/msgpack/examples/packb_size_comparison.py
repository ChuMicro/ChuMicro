"""Compare msgpack and JSON size for the same data.

Shows the size advantage of binary msgpack encoding over JSON text
for the same dictionary.  Both use identical string keys.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    msgpack: 78 bytes
    JSON:    109 bytes
    msgpack is 28% smaller than JSON
"""

import json

from chumicro_msgpack import packb

# Typical device settings.
settings = {
    "ssid": "MyNetwork",
    "password": "secret123",
    "name": "lamp",
    "broker": "192.168.1.100",
    "configured": True,
}

msgpack_size = len(packb(settings))
json_size = len(json.dumps(settings))

print(f"msgpack: {msgpack_size} bytes")
print(f"JSON:    {json_size} bytes")

savings = (1 - msgpack_size / json_size) * 100
print(f"msgpack is {savings:.0f}% smaller than JSON")
