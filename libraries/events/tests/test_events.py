"""Tests for chumicro_events.

Pure-Python, no third-party deps, no hardware.  Runs on CPython under
pytest and on the chumicro-test-harness on MicroPython / CircuitPython
unix ports.
"""

import chumicro_events
from chumicro_events import EventBus, Subscription
from chumicro_events.testing import RecordingSubscriber
from chumicro_test_harness.assertions import raises

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_exports_present() -> None:
    for name in ("EventBus", "Subscription"):
        assert hasattr(chumicro_events, name), f"missing export: {name}"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_capacity() -> None:
    bus = EventBus()
    assert bus.capacity == 64


def test_custom_capacity() -> None:
    bus = EventBus(capacity=8)
    assert bus.capacity == 8


def test_capacity_must_be_positive() -> None:
    with raises(ValueError):
        EventBus(capacity=0)


def test_starts_empty() -> None:
    bus = EventBus()
    assert bus.buffered == 0
    assert bus.dropped == 0
    assert bus.handler_errors == 0
    assert bus.drained == 0
    assert bus.delivered == 0
    assert bus.topics() == ()
    assert bus.check(now_ms=0) is False


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


def test_subscribe_returns_subscription() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    sub = bus.subscribe("wifi.state", recorder)
    assert isinstance(sub, Subscription)
    assert sub.topic == "wifi.state"


def test_subscribe_tracks_topic() -> None:
    bus = EventBus()
    bus.subscribe("wifi.state", RecordingSubscriber())
    assert bus.topics() == ("wifi.state",)
    assert bus.subscriber_count("wifi.state") == 1
    assert bus.subscriber_count("absent.topic") == 0


def test_subscribe_multiple_handlers_same_topic() -> None:
    bus = EventBus()
    bus.subscribe("wifi.state", RecordingSubscriber())
    bus.subscribe("wifi.state", RecordingSubscriber())
    assert bus.subscriber_count("wifi.state") == 2


def test_subscribe_same_handler_twice_yields_distinct_subscriptions() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    sub_a = bus.subscribe("wifi.state", recorder)
    sub_b = bus.subscribe("wifi.state", recorder)
    assert sub_a.token != sub_b.token
    assert bus.subscriber_count("wifi.state") == 2


def test_unsubscribe_removes_handler() -> None:
    bus = EventBus()
    sub = bus.subscribe("wifi.state", RecordingSubscriber())
    assert bus.unsubscribe(sub) is True
    assert bus.subscriber_count("wifi.state") == 0


def test_unsubscribe_drops_topic_when_last_handler_removed() -> None:
    bus = EventBus()
    sub = bus.subscribe("wifi.state", RecordingSubscriber())
    bus.unsubscribe(sub)
    assert bus.topics() == ()


def test_unsubscribe_only_drops_one_of_many() -> None:
    bus = EventBus()
    sub_a = bus.subscribe("wifi.state", RecordingSubscriber())
    bus.subscribe("wifi.state", RecordingSubscriber())
    assert bus.unsubscribe(sub_a) is True
    assert bus.subscriber_count("wifi.state") == 1


def test_unsubscribe_returns_false_when_already_gone() -> None:
    bus = EventBus()
    sub = bus.subscribe("wifi.state", RecordingSubscriber())
    bus.unsubscribe(sub)
    assert bus.unsubscribe(sub) is False


def test_unsubscribe_returns_false_when_topic_unknown() -> None:
    bus = EventBus()
    sub = bus.subscribe("wifi.state", RecordingSubscriber())
    bus.unsubscribe(sub)
    bus.subscribe("mqtt.state", RecordingSubscriber())
    other = Subscription(bus_id=id(bus), token=sub.token, topic="mqtt.state")
    assert bus.unsubscribe(other) is False


def test_unsubscribe_rejects_other_bus() -> None:
    bus_a = EventBus()
    bus_b = EventBus()
    sub = bus_a.subscribe("wifi.state", RecordingSubscriber())
    assert bus_b.unsubscribe(sub) is False


# ---------------------------------------------------------------------------
# publish / handle
# ---------------------------------------------------------------------------


def test_publish_buffers_without_dispatch() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)
    bus.publish("wifi.state", "connected")
    assert bus.buffered == 1
    assert recorder.events == []


def test_handle_dispatches_to_subscribers() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)
    bus.publish("wifi.state", "connected")
    drained = bus.handle(now_ms=0)
    assert drained == 1
    assert recorder.events == [("wifi.state", "connected")]
    assert bus.buffered == 0
    assert bus.check(now_ms=0) is False
    assert bus.drained == 1
    assert bus.delivered == 1


def test_handle_routes_to_correct_topic_only() -> None:
    bus = EventBus()
    wifi_recorder = RecordingSubscriber()
    mqtt_recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", wifi_recorder)
    bus.subscribe("mqtt.state", mqtt_recorder)
    bus.publish("wifi.state", "connected")
    bus.publish("mqtt.state", "connected")
    bus.handle(now_ms=0)
    assert wifi_recorder.events == [("wifi.state", "connected")]
    assert mqtt_recorder.events == [("mqtt.state", "connected")]


def test_handle_with_no_subscribers_consumes_event() -> None:
    bus = EventBus()
    bus.publish("orphan.topic", "lonely")
    drained = bus.handle(now_ms=0)
    assert drained == 1
    assert bus.buffered == 0
    assert bus.delivered == 0


def test_handle_dispatches_to_multiple_handlers_on_same_topic() -> None:
    bus = EventBus()
    one = RecordingSubscriber()
    two = RecordingSubscriber()
    bus.subscribe("wifi.state", one)
    bus.subscribe("wifi.state", two)
    bus.publish("wifi.state", "connected")
    bus.handle(now_ms=0)
    assert one.events == [("wifi.state", "connected")]
    assert two.events == [("wifi.state", "connected")]


def test_handle_preserves_publish_order() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("topic", recorder)
    for index in range(5):
        bus.publish("topic", index)
    bus.handle(now_ms=0)
    payloads = [payload for _, payload in recorder.events]
    assert payloads == [0, 1, 2, 3, 4]


def test_publish_default_payload_is_none() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("ping", recorder)
    bus.publish("ping")
    bus.handle(now_ms=0)
    assert recorder.events == [("ping", None)]


def test_handle_on_empty_queue_returns_zero() -> None:
    bus = EventBus()
    assert bus.handle(now_ms=0) == 0


def test_handle_swallows_subscriber_exceptions() -> None:
    bus = EventBus()

    def boom(topic, payload):
        raise RuntimeError("subscriber boom")

    recorder = RecordingSubscriber()
    bus.subscribe("topic", boom)
    bus.subscribe("topic", recorder)
    bus.publish("topic", "x")
    bus.handle(now_ms=0)
    assert bus.handler_errors == 1
    assert recorder.events == [("topic", "x")]


def test_drained_counter_accumulates_across_calls() -> None:
    bus = EventBus()
    bus.publish("topic", 1)
    bus.handle(now_ms=0)
    bus.publish("topic", 2)
    bus.handle(now_ms=0)
    assert bus.drained == 2


def test_delivered_counts_handler_invocations_not_records() -> None:
    bus = EventBus()
    bus.subscribe("topic", RecordingSubscriber())
    bus.subscribe("topic", RecordingSubscriber())
    bus.subscribe("topic", RecordingSubscriber())
    bus.publish("topic", "x")
    bus.publish("topic", "y")
    bus.handle(now_ms=0)
    assert bus.drained == 2
    assert bus.delivered == 6  # 2 records × 3 subscribers


def test_handle_dispatch_snapshots_subscribers() -> None:
    """Subscribers added mid-dispatch don't see the in-flight event."""
    bus = EventBus()
    late_recorder = RecordingSubscriber()

    def adopter(topic: str, payload: object) -> None:
        bus.subscribe(topic, late_recorder)

    bus.subscribe("topic", adopter)
    bus.publish("topic", "first")
    bus.handle(now_ms=0)
    assert late_recorder.events == []
    bus.publish("topic", "second")
    bus.handle(now_ms=0)
    assert late_recorder.events == [("topic", "second")]


# ---------------------------------------------------------------------------
# Capacity / drop-oldest
# ---------------------------------------------------------------------------


def test_drops_oldest_when_full() -> None:
    bus = EventBus(capacity=2)
    bus.publish("topic", "a")
    bus.publish("topic", "b")
    bus.publish("topic", "c")
    assert bus.dropped == 1
    recorder = RecordingSubscriber()
    bus.subscribe("topic", recorder)
    bus.handle(now_ms=0)
    assert [payload for _, payload in recorder.events] == ["b", "c"]


def test_dropped_counter_accumulates() -> None:
    bus = EventBus(capacity=1)
    for _ in range(4):
        bus.publish("topic", "x")
    assert bus.dropped == 3
    assert bus.buffered == 1


# ---------------------------------------------------------------------------
# publisher() helper
# ---------------------------------------------------------------------------


def test_publisher_helper_publishes_to_bound_topic() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)
    publish_wifi = bus.publisher("wifi.state")
    publish_wifi("connected")
    bus.handle(now_ms=0)
    assert recorder.events == [("wifi.state", "connected")]


def test_publisher_helper_default_payload_is_none() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("ping", recorder)
    publish_ping = bus.publisher("ping")
    publish_ping()
    bus.handle(now_ms=0)
    assert recorder.events == [("ping", None)]


def test_publish_multi_arg_packs_into_tuple_payload() -> None:
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)
    bus.publish("wifi.state", "connected", "disconnected")
    bus.handle(now_ms=0)
    assert recorder.events == [("wifi.state", ("connected", "disconnected"))]


def test_publisher_helper_forwards_multi_arg_calls() -> None:
    """publisher closures handle any callback arity at the wiring site."""
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)

    # Stand-in for a service that fires its callback with multiple args.
    callback = bus.publisher("wifi.state")
    callback("idle", "connecting")
    bus.handle(now_ms=0)
    assert recorder.events == [("wifi.state", ("idle", "connecting"))]


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


def test_clear_drops_queued_records() -> None:
    bus = EventBus()
    bus.publish("topic", "a")
    bus.publish("topic", "b")
    assert bus.buffered == 2
    bus.clear()
    assert bus.buffered == 0


def test_clear_does_not_reset_counters() -> None:
    bus = EventBus(capacity=1)
    bus.publish("topic", "a")
    bus.publish("topic", "b")
    bus.clear()
    assert bus.dropped == 1


# ---------------------------------------------------------------------------
# Subscription token
# ---------------------------------------------------------------------------


def test_subscription_repr_is_descriptive() -> None:
    bus = EventBus()
    sub = bus.subscribe("wifi.state", RecordingSubscriber())
    text = repr(sub)
    assert "wifi.state" in text
    assert "Subscription" in text


def test_subscription_token_increments() -> None:
    bus = EventBus()
    first = bus.subscribe("a", RecordingSubscriber())
    second = bus.subscribe("b", RecordingSubscriber())
    assert second.token == first.token + 1


# ---------------------------------------------------------------------------
# RecordingSubscriber
# ---------------------------------------------------------------------------


def test_recording_subscriber_with_topic_filter() -> None:
    recorder = RecordingSubscriber(topic_filter="wifi.state")
    assert recorder.topic_filter == "wifi.state"
    recorder("wifi.state", "x")
    recorder("mqtt.state", "y")
    assert recorder.events == [("wifi.state", "x")]


def test_recording_subscriber_clear() -> None:
    recorder = RecordingSubscriber()
    recorder("topic", "x")
    recorder.clear()
    assert recorder.events == []


def test_recording_subscriber_events_returns_copy() -> None:
    recorder = RecordingSubscriber()
    recorder("topic", "x")
    snapshot = recorder.events
    recorder("topic", "y")
    assert snapshot == [("topic", "x")]


def test_recording_subscriber_no_filter_records_everything() -> None:
    recorder = RecordingSubscriber()
    assert recorder.topic_filter is None
    recorder("a", 1)
    recorder("b", 2)
    assert recorder.events == [("a", 1), ("b", 2)]
