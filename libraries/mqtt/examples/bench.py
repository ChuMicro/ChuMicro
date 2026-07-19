"""Self-driving on-device bench for :mod:`chumicro_mqtt`.

Walks both inbound-handling tiers (steady / oversized) plus QoS-1
round-trip, keepalive, and a sustained burst, all against a real
broker, all from the device alone.  Subscribes to a private topic and
publishes-to-itself for every inbound test, so no host script is
required.  Watch the serial output for the per-scenario progress lines
and the final summary table.

The library's design promises two things this bench verifies live:

* an inbound PUBLISH whose total wire size is ≤ ``rx_buffer_size``
  parses inline and is delivered intact with no per-message heap
  allocation — so a consumer that needs a larger payload intact sizes
  ``rx_buffer_size`` up to cover it,
* a PUBLISH above ``rx_buffer_size`` (and a topic above
  ``rx_buffer_size``) drain via rolling discard, with no payload-sized
  allocation regardless of how big the inbound message is.

This bench keeps ``rx_buffer_size`` at the 256 B default so a small
payload delivers intact from the steady buffer, while a 4 KB inbound
payload (and a 300-char topic) trip the oversized tier without needing
a payload-sized allocation on either side of the wire.

Configuration
=============

Read from the deployed ``runtime_config.msgpack``:

* WiFi: ``wifi.ssid`` / ``wifi.password`` (read by ``helpers.wifi_up``).
* MQTT: ``mqtt.broker.host`` / ``mqtt.broker.port`` (set by
  ``secrets.toml`` ``[mqtt.broker]``).  Override with the
  ``BROKER_HOST`` / ``BROKER_PORT`` constants below for ad-hoc runs.

Deploying
=========

::

    chumicro-workspace deploy-example mqtt bench --device <id>

Then watch serial output (``chumicro-repl --device <id>``).  The
device drives every scenario itself.  No host script needed.

What you should see
===================

Per scenario, one progress line.  After all scenarios, a summary
table.  Healthy output ends with::

    ALL SCENARIOS PASSED

If the bench can't reach the broker, you'll see ``FAIL_MQTT_CONNECT``
plus the underlying error.
"""

__chumicro_runtimes__ = ("circuitpython", "micropython")

import gc
import time

from chumicro_mqtt import MQTTClient, ProtocolState, WhenOversized
from helpers import runtime_config, ticks_add, ticks_diff, ticks_ms, wifi_up

# Edit these for a single-file deploy without runtime_config.  The
# deployed runtime_config.msgpack overrides them when present.
WIFI_SSID = "your-wifi-ssid"          # noqa: S105
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105
BROKER_HOST = ""                       # e.g. "10.0.0.5" or "test.mosquitto.org"
BROKER_PORT = 1883

# Bench knobs, kept small so a 256 KB-RAM minimum-tier board still has
# headroom.  rx_buffer_size=256 means:
#   steady:    ≤ 256 B (inline parse, delivered intact, no per-msg alloc)
#   oversized: > 256 B (rolling discard, no payload-sized alloc)
RX_BUFFER_SIZE = 256
CLIENT_ID = "chumicro-mqtt-bench"


def banner(text):
    print(f"\n=== {text} ===")


def line(text):
    print(f"  {text}")


# ---------------------------------------------------------------------------
# Boot: wifi, broker, subscriptions.
# ---------------------------------------------------------------------------

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

if "mqtt.broker.host" not in config:
    if not BROKER_HOST:
        print("STATUS: FAIL_MQTT_BROKER_NOT_CONFIGURED")
        print("ERROR: set mqtt.broker.host in runtime_config.msgpack "
              "or BROKER_HOST in this file before deploying.")
        raise SystemExit(1)
    config["mqtt.broker.host"] = BROKER_HOST
    config["mqtt.broker.port"] = BROKER_PORT
config["mqtt.client_id"] = CLIENT_ID

# Build the connector factory ourselves so we can pass the buffer-tuning
# kwargs the bench needs.  from_config doesn't expose them.
from chumicro_sockets.sockets_factory import fixed_connector_factory  # noqa: E402

mqtt = MQTTClient(
    transport_factory=fixed_connector_factory(
        config["mqtt.broker.host"], config["mqtt.broker.port"], radio=radio,
    ),
    client_id=CLIENT_ID,
    keep_alive_seconds=30,
    rx_buffer_size=RX_BUFFER_SIZE,
    when_oversized=WhenOversized.DROP_WITH_EVENT,
)

# Inbound state: every scenario zeros this and the matching helpers
# wait for the expected count.
inbound_topic_count = 0
inbound_last_size = 0
oversize_events = []


def on_message(topic, payload):
    global inbound_topic_count, inbound_last_size
    inbound_topic_count += 1
    inbound_last_size = len(payload)


def on_oversized(reported_length, topic):
    oversize_events.append((reported_length, topic))


mqtt.on_message = on_message
mqtt.on_oversized = on_oversized


def drive_for(milliseconds):
    """Run handle() in a tick loop for *milliseconds*."""
    deadline = ticks_add(ticks_ms(), milliseconds)
    while ticks_diff(deadline, ticks_ms()) > 0:
        if mqtt.check(ticks_ms()):
            mqtt.handle(ticks_ms())
        time.sleep(0.005)


def drive_until(predicate, milliseconds):
    """Run handle() until *predicate()* is true or *milliseconds* elapse.
    Returns True if predicate fired, False on timeout."""
    deadline = ticks_add(ticks_ms(), milliseconds)
    while not predicate():
        if ticks_diff(deadline, ticks_ms()) <= 0:
            return False
        if mqtt.check(ticks_ms()):
            mqtt.handle(ticks_ms())
        time.sleep(0.005)
    return True


banner(f"Connecting to {config['mqtt.broker.host']}:{config['mqtt.broker.port']}")
mqtt.connect()
if not drive_until(lambda: mqtt.state == ProtocolState.CONNECTED, 15_000):
    print(f"STATUS: FAIL_MQTT_CONNECT state={mqtt.state} last_error={mqtt.last_error}")
    raise SystemExit(1)
line(f"CONNECTED state={mqtt.state}")

# Subscribe to two topics:
#   * One we publish small/medium/large payloads to.
#   * A wildcard for the oversize-topic test (a 300-char topic blows
#     rx_buffer_size, the wildcard lets the broker deliver it back).
INBOUND_TOPIC = f"{CLIENT_ID}/inbound"
INBOUND_WILDCARD = f"{CLIENT_ID}/inbound/+"
SUMMARY_TOPIC = f"{CLIENT_ID}/bench-summary"
mqtt.subscribe(INBOUND_TOPIC, qos=0)
mqtt.subscribe(INBOUND_WILDCARD, qos=0)
# Drive ticks so SUBACKs come back before scenarios start.
drive_for(500)
line(f"subscribed to {INBOUND_TOPIC} and {INBOUND_WILDCARD}")

# ---------------------------------------------------------------------------
# Scenarios.  Each captures heap before/after and a max tick latency.
# ---------------------------------------------------------------------------


class Scenario:
    """One bench scenario's pre-/post-heap snapshot and per-tick latency."""

    def __init__(self, name):
        self.name = name
        gc.collect()
        self.alloc_start = gc.mem_alloc()
        self.free_start = gc.mem_free()
        self.max_tick_ms = 0
        self.tick_count = 0

    def tick(self):
        start = ticks_ms()
        if mqtt.check(start):
            mqtt.handle(start)
        delta = ticks_diff(ticks_ms(), start)
        if delta > self.max_tick_ms:
            self.max_tick_ms = delta
        self.tick_count += 1

    def finish(self):
        gc.collect()
        alloc_delta = gc.mem_alloc() - self.alloc_start
        free_delta = self.free_start - gc.mem_free()
        return (self.name, alloc_delta, free_delta, self.max_tick_ms, self.tick_count)


results = []


def _reset_inbound():
    global inbound_topic_count, inbound_last_size
    inbound_topic_count = 0
    inbound_last_size = 0


def scenario_tier1():
    banner("STEADY (small) — inline parse (32-byte payload)")
    scenario = Scenario("steady_32b")
    _reset_inbound()
    payload = b"x" * 32
    mqtt.publish(INBOUND_TOPIC, payload, qos=0)
    deadline = ticks_add(ticks_ms(), 5000)
    while inbound_topic_count == 0 and ticks_diff(deadline, ticks_ms()) > 0:
        scenario.tick()
        time.sleep(0.005)
    ok = inbound_topic_count == 1 and inbound_last_size == 32
    verdict = "OK" if ok else "FAIL"
    line(f"received={inbound_topic_count} size={inbound_last_size} expect=32 -> {verdict}")
    results.append(scenario.finish() + (ok,))


def scenario_tier3():
    banner(f"OVERSIZED — rolling drain (4096 B above {RX_BUFFER_SIZE} B rx buffer)")
    scenario = Scenario("oversize_4kb")
    seen = len(oversize_events)
    payload = b"z" * 4096
    mqtt.publish(INBOUND_TOPIC, payload, qos=0)
    deadline = ticks_add(ticks_ms(), 15_000)
    while len(oversize_events) == seen and ticks_diff(deadline, ticks_ms()) > 0:
        scenario.tick()
        time.sleep(0.005)
    fired = len(oversize_events) > seen
    if fired:
        reported = oversize_events[-1][0]
        topic_seen = oversize_events[-1][1]
        ok = topic_seen == INBOUND_TOPIC and reported > 4000
        verdict = "OK" if ok else "FAIL"
        line(f"on_oversized: reported_length={reported} topic={topic_seen!r} -> {verdict}")
    else:
        ok = False
        line("on_oversized never fired -> FAIL")
    results.append(scenario.finish() + (ok,))


def scenario_oversize_topic():
    banner(f"OVERSIZE TOPIC — 300-char topic blows the {RX_BUFFER_SIZE} B rx buffer")
    scenario = Scenario("oversize_topic")
    seen = len(oversize_events)
    long_topic = INBOUND_TOPIC + "/" + ("a" * 300)
    mqtt.publish(long_topic, b"hi", qos=0)
    deadline = ticks_add(ticks_ms(), 10_000)
    while len(oversize_events) == seen and ticks_diff(deadline, ticks_ms()) > 0:
        scenario.tick()
        time.sleep(0.005)
    fired = len(oversize_events) > seen
    if fired:
        reported = oversize_events[-1][0]
        topic_seen = oversize_events[-1][1]
        ok = topic_seen is None
        verdict = "OK" if ok else "FAIL"
        line(f"on_oversized: reported_length={reported} topic={topic_seen} -> {verdict}")
    else:
        ok = False
        line("on_oversized never fired -> FAIL")
    results.append(scenario.finish() + (ok,))


def scenario_qos1():
    banner("QoS 1 — 10 round-trips with PUBACK")
    scenario = Scenario("qos1_10x")
    acked = [0]
    rtts_ms = []
    last_at = [0]

    def _on_pub(topic, payload):
        acked[0] += 1
        rtts_ms.append(ticks_diff(ticks_ms(), last_at[0]))

    for index in range(10):
        last_at[0] = ticks_ms()
        mqtt.publish(f"{CLIENT_ID}/qos1-out", b"qos1-%d" % index, qos=1, on_publish=_on_pub)
        target = acked[0] + 1
        deadline = ticks_add(ticks_ms(), 5000)
        while acked[0] < target and ticks_diff(deadline, ticks_ms()) > 0:
            scenario.tick()
            time.sleep(0.005)
    ok = acked[0] == 10
    if rtts_ms:
        avg = sum(rtts_ms) // len(rtts_ms)
        worst = max(rtts_ms)
    else:
        avg = 0
        worst = 0
    line(f"acked={acked[0]}/10 avg_rtt={avg}ms worst_rtt={worst}ms -> {'OK' if ok else 'FAIL'}")
    results.append(scenario.finish() + (ok,))


def scenario_keepalive():
    banner("KEEPALIVE — idle 35 s (one PINGREQ cycle at 30 s)")
    scenario = Scenario("keepalive_35s")
    state_before = mqtt.state
    deadline = ticks_add(ticks_ms(), 35_000)
    while ticks_diff(deadline, ticks_ms()) > 0:
        scenario.tick()
        time.sleep(0.020)
    ok = mqtt.state == ProtocolState.CONNECTED and state_before == ProtocolState.CONNECTED
    line(f"state before={state_before} after={mqtt.state} -> {'OK' if ok else 'FAIL'}")
    results.append(scenario.finish() + (ok,))


def scenario_stress():
    banner("STRESS — 100 small messages back-to-back")
    scenario = Scenario("stress_100x")
    _reset_inbound()
    expected = 100
    for index in range(expected):
        mqtt.publish(INBOUND_TOPIC, b"s%03d" % index, qos=0)
        scenario.tick()  # let outbound flush between sends
    # Drain inbound: broker echoes every publish back to our subscription.
    deadline = ticks_add(ticks_ms(), 30_000)
    while inbound_topic_count < expected and ticks_diff(deadline, ticks_ms()) > 0:
        scenario.tick()
        time.sleep(0.005)
    ok = inbound_topic_count == expected
    line(f"received={inbound_topic_count}/{expected} -> {'OK' if ok else 'FAIL'}")
    results.append(scenario.finish() + (ok,))


# ---------------------------------------------------------------------------
# Run.
# ---------------------------------------------------------------------------

scenario_tier1()
scenario_tier3()
scenario_oversize_topic()
scenario_qos1()
scenario_stress()
scenario_keepalive()

# ---------------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------------

banner("SUMMARY")
gc.collect()
all_ok = all(row[5] for row in results)

# Column layout: name(18)  alloc_d(9)  free_d(9)  max_tick(10)  ticks(9)  status(9)
print(f"  {'scenario':<18}{'alloc_d':>9}{'free_d':>9}{'max_tick':>10}{'ticks':>9}{'status':>9}")
print(f"  {'-' * 18}{'-' * 9:>9}{'-' * 8:>9}{'-' * 9:>10}{'-' * 8:>9}{'-' * 8:>9}")
for name, alloc_delta, free_delta, max_tick, tick_count, ok in results:
    status = "OK" if ok else "FAIL"
    print(f"  {name:<18}{alloc_delta:>9}{free_delta:>9}{max_tick:>9}ms{tick_count:>9}{status:>9}")

print()
print(f"  device  alloc={gc.mem_alloc()}  free={gc.mem_free()}")
print(f"  client  state={mqtt.state}  oversize_events_total={len(oversize_events)}")
print()
if all_ok:
    print("ALL SCENARIOS PASSED")
else:
    print("ONE OR MORE SCENARIOS FAILED")

# Also publish the one-line verdict to the broker so an off-device watcher
# (mosquitto_sub -t '<client_id>/bench-summary') can collect results.
mqtt.publish(
    SUMMARY_TOPIC,
    ("ALL_OK" if all_ok else "FAILURES").encode() + b" alloc=" + str(gc.mem_alloc()).encode()
    + b" free=" + str(gc.mem_free()).encode(),
    qos=0,
)
drive_for(500)
mqtt.disconnect()
