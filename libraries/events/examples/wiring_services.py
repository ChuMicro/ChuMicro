"""Wiring service callbacks into a single EventBus.

Shows the canonical pattern from Decision 0042: services expose
``on_state_change`` callbacks, the application binds each one to a
publisher on a shared bus, and a single subscriber reacts to the
resulting cross-service stream.

The fake services here stand in for the real ``chumicro-wifi`` and
``chumicro-mqtt``; the wiring shape is identical.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    [audit] wifi.state -> connecting
    [audit] wifi.state -> connected
    [audit] mqtt.state -> ready
"""

from chumicro_events import EventBus


class FakeWifi:
    """Stand-in for chumicro-wifi's state-change publisher."""

    def __init__(self) -> None:
        self.on_state_change = lambda payload=None: None

    def simulate(self, state: str) -> None:
        self.on_state_change(state)


class FakeMqtt:
    """Stand-in for chumicro-mqtt's state-change publisher."""

    def __init__(self) -> None:
        self.on_state_change = lambda payload=None: None

    def simulate(self, state: str) -> None:
        self.on_state_change(state)


bus = EventBus()
wifi = FakeWifi()
mqtt = FakeMqtt()

# Wiring: each service's callback becomes a bus publisher.
wifi.on_state_change = bus.publisher("wifi.state")
mqtt.on_state_change = bus.publisher("mqtt.state")


def audit(topic: str, payload: object) -> None:
    print(f"[audit] {topic} -> {payload}")


bus.subscribe("wifi.state", audit)
bus.subscribe("mqtt.state", audit)

# Simulate state transitions.
wifi.simulate("connecting")
wifi.simulate("connected")
mqtt.simulate("ready")

# Drain — runner would do this once per tick.
bus.handle(now_ms=0)
