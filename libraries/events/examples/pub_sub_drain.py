"""EventBus publish-subscribe-drain demo.

Demonstrates the runner-shaped contract: ``publish`` enqueues,
``check`` reports pending records, ``handle`` dispatches them in
publish order to every subscriber attached at the moment of
dispatch.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    pending: True
    wifi.state -> connected
    mqtt.state -> ready
    pending: False
"""

from chumicro_events import EventBus


def show(topic: str, payload: object) -> None:
    print(f"{topic} -> {payload}")


bus = EventBus()
bus.subscribe("wifi.state", show)
bus.subscribe("mqtt.state", show)

bus.publish("wifi.state", "connected")
bus.publish("mqtt.state", "ready")

print(f"pending: {bus.check(now_ms=0)}")
bus.handle(now_ms=0)
print(f"pending: {bus.check(now_ms=0)}")
