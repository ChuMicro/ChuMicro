"""Real-board bake for chumicro-requests streamed response bodies.

Category 2 — device-as-client against a host-side HTTP server.

The point of ``stream=True`` is that a body larger than the heap costs
a *fixed* few KB of RAM, not its own size.  A unit lane can assert the
staging/backpressure contract but cannot prove the heap claim on real
silicon; this is the hot-path bake AGENTS asks for: a 256 KiB download
onto a 264 KB-class board, drained a slice at a time, with ``gc.mem_free``
sampled before / during / after to show the body never resides.

What it verifies, over BOTH framings (``Content-Length`` and
``Transfer-Encoding: chunked``) against the host fixture in
``_host_large_body_server.py``:

* Exact byte count — every requested byte arrives.
* Zero integrity mismatches — the body value at offset *i* is ``i % 256``,
  checked incrementally against a 256-byte reference so nothing but the
  512-byte caller buffer is held.
* Heap stays flat — free heap mid-transfer and after are both within a
  small tolerance of the pre-request baseline, while the body (256 KiB)
  dwarfs both the tolerance and the board's free heap.  A body that
  buffered whole could not even fit.

Size / timeout rationale:

* ``_BODY_SIZE`` is 256 KiB — comfortably over the >150 KB floor, over
  4x ``max_body_bytes`` (64 KB), and larger than a minimum-class board's
  post-wifi free heap, so buffering the body whole is provably
  impossible.  256 KiB (over ~300 KB) keeps the two-framing suite inside
  per-board time budgets; at board wifi speeds each framing moves in a
  handful of seconds, well under the 60 s per-request timeout.
* The transfer is driven in a tight loop (no per-tick sleep) for
  throughput; ``led_ticks`` still proves each ``handle()`` returned
  promptly rather than block-calling — a blocked tick would stop the
  loop advancing.

No rp2 skip: this dials the HOST fixture, not the board's own loopback,
so the lwIP self-loopback / CP-USB limits that gate the websockets
single-device loopback test do not apply here (same as ``test_real_get``,
which also has no rp2 skip).

Skipped at collection time when wifi credentials are missing; skipped in
the body when the host fixture didn't spawn (no LAN IP detected).
"""

import gc

from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_test_harness import skip
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

#: Body size, in bytes.  256 KiB — see the module docstring for why this
#: value (heap-exceeding, multiple of the 256-byte pattern period, time-
#: budget-friendly across two framings).
_BODY_SIZE = 262_144

#: Caller-owned drain buffer — small and fixed, the whole RAM story.
_CALLER_BUFFER_SIZE = 512

#: Per-request staging window.  Bigger than the 1 KB default so more
#: body moves per tick (throughput on a large transfer); still a fixed,
#: tiny fraction of the body, and counted into the heap tolerance below.
_STREAM_BUFFER_SIZE = 4096

#: Soft cap on bytes drained from the socket per ``handle()`` tick.
_RECV_BUDGET_PER_TICK = 8192

#: Whole-transfer timeout (covers consumption too, per the stream
#: contract).  Generous — a slow board at ~10 KB/s still finishes 256 KiB
#: in ~26 s.
_REQUEST_TIMEOUT_MS = 60_000

#: Extra wall-clock slack over the request timeout before the drive loop
#: gives up, so a genuine ``HttpTimeoutError`` surfaces as itself rather
#: than as this loop's AssertionError.
_DEADLINE_SLACK_MS = 15_000

#: Free-heap drift tolerance, baseline vs mid-transfer and vs after.
#: The fixed cost of an in-flight streamed request (staging window +
#: parser + socket + handle + caller buffer) is ~7 KB; 32 KiB leaves
#: headroom for allocator entropy while staying 8x under the body size —
#: so passing proves the 256 KiB body never resided in the heap.  The
#: printed ``retained`` / ``mid_drop`` are the real data.
_HEAP_TOLERANCE_BYTES = 32_768

#: Floor on drive iterations, proving the transfer interleaved with the
#: caller's loop (each ``handle()`` returned control).  The 4 KB staging
#: window caps body movement to <=4 KB/tick, so 256 KiB needs >=64 ticks;
#: >10 is a safe, non-flaky floor.
_MIN_LED_TICKS = 10

#: Two periods of the ramp, tripled — a rotation-free reference window.
#: Expected bytes for a <=512-byte read at phase ``p`` (0..255) are
#: ``_REFERENCE[p:p + count]``; ``p + count`` <= 255 + 512 = 767 < 768,
#: so one flat slice covers any read without wrapping.
_REFERENCE = bytes(range(256)) * 3


def _count_mismatches(view, count, absolute_offset):
    """Return how many of the *count* bytes in *view* break the ramp.

    Expected byte *k* is ``(absolute_offset + k) % 256``.  The fast path
    is a single C-level compare against the precomputed reference window;
    only a corrupt read pays the per-byte tally.
    """
    phase = absolute_offset % 256
    expected = _REFERENCE[phase:phase + count]
    got = bytes(view[:count])
    if got == expected:
        return 0
    return sum(1 for k in range(count) if got[k] != expected[k])


def _drain_streamed_download(client, handle):
    """Drive *handle* to completion, verifying + counting the body.

    Returns ``(total_bytes, mismatches, led_ticks, mid_free)`` where
    ``mid_free`` is a garbage-collected ``gc.mem_free()`` sampled once at
    roughly the halfway mark (``-1`` if the transfer never reached it).
    """
    buffer = bytearray(_CALLER_BUFFER_SIZE)
    view = memoryview(buffer)
    total = 0
    mismatches = 0
    led_ticks = 0
    mid_free = -1
    half = _BODY_SIZE // 2
    deadline = ticks_ms() + _REQUEST_TIMEOUT_MS + _DEADLINE_SLACK_MS

    while not handle.done:
        now = ticks_ms()
        if now > deadline:
            raise AssertionError(
                f"streamed download stalled: got {total} of {_BODY_SIZE} "
                f"bytes before the {_REQUEST_TIMEOUT_MS} ms deadline",
            )
        if client.check(now):
            client.handle(now)
        # Drain everything staged this tick, 512 B at a time, so the
        # caller buffer stays the only body-sized RAM and backpressure
        # never stalls the next recv.
        if handle.response is not None:
            while True:
                count = handle.read_body_into(view)
                if count == 0:
                    break
                mismatches += _count_mismatches(view, count, total)
                total += count
            if mid_free < 0 and total >= half:
                gc.collect()
                mid_free = gc.mem_free()
        led_ticks += 1

    # Bytes staged in the completing tick are drained above; this final
    # pass is defensive against any residual window content.
    if handle.response is not None:
        while True:
            count = handle.read_body_into(view)
            if count == 0:
                break
            mismatches += _count_mismatches(view, count, total)
            total += count

    return total, mismatches, led_ticks, mid_free


def _run_framing(client, base_url, framing):
    """Download one framing, asserting byte count, integrity, and heap flatness."""
    url = f"{base_url}?size={_BODY_SIZE}&framing={framing}"

    gc.collect()
    baseline = gc.mem_free()

    handle = client.get(url, stream=True, timeout_ms=_REQUEST_TIMEOUT_MS)
    total, mismatches, led_ticks, mid_free = _drain_streamed_download(
        client, handle,
    )

    response = handle.result  # raises HttpError on a failed transfer
    del handle
    gc.collect()
    after = gc.mem_free()
    retained = baseline - after
    mid_drop = baseline - mid_free if mid_free >= 0 else -1

    print(
        f"STREAM_OK framing={framing} status={response.status_code} "
        f"bytes={total} mismatches={mismatches} led_ticks={led_ticks} "
        f"baseline={baseline} mid_drop={mid_drop} retained={retained}",
    )

    assert response.status_code == 200, (
        f"{framing}: expected 200, got {response.status_code}"
    )
    assert response.streamed, f"{framing}: response should be streamed"
    assert total == _BODY_SIZE, (
        f"{framing}: got {total} bytes, expected exactly {_BODY_SIZE}"
    )
    assert mismatches == 0, (
        f"{framing}: {mismatches} body bytes broke the offset ramp — "
        f"the stream corrupted or misframed the body"
    )
    assert led_ticks > _MIN_LED_TICKS, (
        f"{framing}: drive loop only iterated {led_ticks} times — a "
        f"handle() block-called instead of yielding"
    )
    # The heap proof: a {_BODY_SIZE}-byte body left the free heap within
    # a few KB of baseline both during and after the transfer.
    assert mid_free >= 0, (
        f"{framing}: never sampled mid-transfer heap — transfer too short?"
    )
    assert mid_drop < _HEAP_TOLERANCE_BYTES, (
        f"{framing}: free heap fell {mid_drop} B mid-transfer (tolerance "
        f"{_HEAP_TOLERANCE_BYTES} B) — the {_BODY_SIZE}-byte body is "
        f"accumulating in RAM instead of streaming"
    )
    assert retained < _HEAP_TOLERANCE_BYTES, (
        f"{framing}: {retained} B stayed resident after the transfer "
        f"(tolerance {_HEAP_TOLERANCE_BYTES} B) — a body-sized buffer "
        f"leaked past the streamed request"
    )


def test_real_streamed_large_download_stays_flat_on_heap() -> None:
    """Stream a heap-exceeding body under both framings at fixed RAM cost."""
    config = runtime_config()
    ssid = config.get("wifi.ssid", "")
    password = config.get("wifi.password", "")
    if not ssid:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time. Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )

    host = config["requests.large_body.server.host"]
    port = config["requests.large_body.server.port"]
    if host is None or port is None:
        # Conftest registers None for host/port when no LAN IP could be
        # detected to bind the host fixture. required_keys treats None as
        # present, so surface the skip here.
        skip(
            "host large-body HTTP fixture not available "
            "(LAN IP detection failed on the test host)",
        )

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    client = HttpClient(
        transport_factory=connector_factory(radio=radio),
        stream_buffer_size=_STREAM_BUFFER_SIZE,
        recv_budget_per_tick=_RECV_BUDGET_PER_TICK,
        default_timeout_ms=_REQUEST_TIMEOUT_MS,
    )

    base_url = f"http://{host}:{port}/stream"
    # One client, two framings in sequence (single-in-flight resets to
    # idle between requests) — one wifi bringup for both, keeping the
    # bake inside per-board time budgets.
    _run_framing(client, base_url, "length")
    _run_framing(client, base_url, "chunked")
