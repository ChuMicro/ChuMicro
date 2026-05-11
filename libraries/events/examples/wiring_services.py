"""Wiring service callbacks into a single EventBus.

Two service shapes coexist in this family:

- **Registration method** like ``chumicro-wifi``'s
  ``on_state_change(callback)``, where the service invokes
  ``callback(old_state, new_state)``.
- **Replaceable attribute** like ``chumicro-mqtt``'s
  ``on_connect = callback``, where the service invokes the callback
  with whatever args it documents.

``bus.publisher(topic)`` returns a ``*args``-accepting callable that
adapts to either shape without an inline adapter.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    [audit] wifi.state -> ('idle', 'connecting')
    [audit] wifi.state -> ('connecting', 'connected')
    [audit] mqtt.connected -> None
"""

from chumicro_events import EventBus


class FakeWifi:
    """Stand-in for chumicro-wifi.  Registration-method shape."""

    def __init__(self) -> None:
        self._callbacks: list = []

    def on_state_change(self, callback) -> None:
        self._callbacks.append(callback)

    def simulate(self, old_state: str, new_state: str) -> None:
        for callback in self._callbacks:
            callback(old_state, new_state)


class FakeMqtt:
    """Stand-in for chumicro-mqtt.  Replaceable-attribute shape."""

    def __init__(self) -> None:
        self.on_connect = lambda: None

    def simulate_connected(self) -> None:
        self.on_connect()


bus = EventBus()
wifi = FakeWifi()
mqtt = FakeMqtt()

# Wiring: same publisher() helper covers both service shapes.
wifi.on_state_change(bus.publisher("wifi.state"))
mqtt.on_connect = bus.publisher("mqtt.connected")


def audit(topic: str, payload: object) -> None:
    print(f"[audit] {topic} -> {payload}")


bus.subscribe("wifi.state", audit)
bus.subscribe("mqtt.connected", audit)

# Simulate state transitions.
wifi.simulate("idle", "connecting")
wifi.simulate("connecting", "connected")
mqtt.simulate_connected()

# Drain — runner would do this once per tick.
bus.handle(now_ms=0)
