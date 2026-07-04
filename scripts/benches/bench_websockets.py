"""Benches for the websockets frame parser (``chumicro_websockets._wire``).

Measures one inbound-frame decode cycle — ``feed(wire)`` a complete
client-masked binary frame, snapshot ``.payload``, ``reset()`` for the
next frame — at a small and a medium payload size.  Client→server frames
are masked, so this exercises the hot unmask loop (every inbound byte a
browser sends is masked).

Two sizes straddle the parser's steady-state buffer boundary
(``DEFAULT_PAYLOAD_BUFFER_SIZE`` = 256 B):

* **small** (64 B) — tier 1: fits the pre-allocated steady buffer, so
  the only per-frame allocations are the transients (the payload ``bytes``
  snapshot the caller reads, the input memoryview).
* **medium** (1024 B) — tier 2: a one-shot ``bytearray(payload_length)``
  is allocated per frame on top of the snapshot, so per-frame churn and
  wall-time both jump.  ``run.py bench`` derives a bytes/sec throughput
  from the CPU number for these payload benches.
"""

import sys

sys.path.insert(0, "scripts/benches")

from _harness import register  # noqa: E402
from chumicro_websockets._wire import (  # noqa: E402
    OPCODE_BINARY,
    FrameParser,
    encode_frame,
    make_mask_key,
)


def _make_setup(payload_size):
    def setup():
        payload = bytes((i & 0xFF) for i in range(payload_size))
        # A complete client-masked binary frame, prebuilt once: the bench
        # measures the decode, not the encode.  ``bytes(...)`` so ``feed``
        # sees an immutable wire buffer (its own memoryview path), the
        # real inbound shape.
        wire = bytes(encode_frame(OPCODE_BINARY, payload, mask=make_mask_key()))
        return (FrameParser(), wire)

    return setup


def _decode_cycle(state):
    parser, wire = state
    parser.feed(wire)
    _data = parser.payload
    parser.reset()


for _label, _size in (("small", 64), ("medium", 1024)):
    register(
        f"ws_frame_decode_{_label}",
        setup=_make_setup(_size),
        op=_decode_cycle,
        # medium frames allocate a per-frame bytearray; keep the disabled-
        # collector heap window bounded well under the port's native heap.
        heap_batch=128 if _size > 256 else 256,
        cpu_batch=1000 if _size > 256 else 2000,
        payload_bytes=_size,
        note=f"feed+reset one {_size}-byte masked binary frame",
    )
