"""Runner-shaped pub/sub event bus for chumicro libraries.

A small in-process event bus with topic strings, bounded queueing, and
a runner-shaped ``check`` / ``handle`` contract.  Publishers enqueue
``(topic, payload)`` records; subscribers register handlers per
topic; the bus dispatches everything in batches when the runner ticks
the bus's ``handle``.

This package has no chumicro dependencies and **no chumicro library
imports it** — by policy, decoration / observability libraries don't
appear in another library's dependency graph; apps that want service
state changes to reach a single place wire it themselves::

    from chumicro_events import EventBus

    bus = EventBus()
    wifi.on_state_change = bus.publisher("wifi.state")
    mqtt.on_state_change = bus.publisher("mqtt.state")
    bus.subscribe("wifi.state", on_wifi_state)
    bus.subscribe("mqtt.state", on_mqtt_state)

Public API
----------
- ``EventBus(capacity)`` — the bus
- ``Subscription`` — opaque token returned by ``subscribe``
"""

from chumicro_events.core import EventBus, Subscription

__all__ = ["EventBus", "Subscription"]
