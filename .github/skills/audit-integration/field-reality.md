# Audit-integration field reality

Incidents and worked examples that shaped the audit dimensions in [SKILL.md](SKILL.md).  Each section is referenced from a bullet there.  Consult an entry when the *how this came up* context behind a rule is useful; the rule itself stays in SKILL.md.

## Contents

- [Streaming-parser conformance — shape, compaction, zero-copy hand-off](#streaming-parser-conformance--shape-compaction-zero-copy-hand-off)

## Streaming-parser conformance — shape, compaction, zero-copy hand-off

When two or more libraries each ship a streaming wire parser fed by `recv_into` on a shared scratch buffer, three sub-shapes diverge silently.  Surfaced first during the 2026-05-11 wire.py audit across `chumicro_mqtt`, `chumicro_requests`, `chumicro_http_server`, `chumicro_websockets`.

### Push vs pull API

Pull-style (mqtt `PacketDecoder`: parser owns the buffer + exposes `fill_buffer()` / `advance()` / `read_next()`, recv writes directly into it — zero-copy at the recv boundary) vs push-style (HTTP-shaped parsers in requests / http_server / websockets: client/connection owns the buffer + calls `parser.feed(view[:n])` — extra layer but more flexible when one recv may straddle multiple parser states).  Both are defensible; flag *unintentional* divergence within a library family.

### Compaction strategy on read-cursor parsers

Realloc-and-rebind (`self._buffer = bytearray(self._buffer[off:])`) vs in-place memmove.  The in-place shape is strictly better on MP/CP allocators (no per-compaction alloc).  Portable in-place patterns:

* **Fixed-size buffer + cached `memoryview`** (the mqtt `PacketDecoder` shape) — compact via `view[:live] = view[off:length]`.  Best when the buffer never grows.
* **Growing buffer** (HTTP parsers fed by `.extend()`) — compact via `self._buffer[:off] = b""` (slice-assign-empty).  Verified against `.tools/micropython-v1.26.0/py/objarray.c` + `.tools/circuitpython-10.2.0/py/objarray.c`: the non-grow path goes through `mp_seq_replace_slice_no_grow`, no `m_renew`.  `del bytearray[:n]` is NOT supported on MP/CP (returns `MP_OBJ_NULL` / "op not supported") — slice-assign-empty is the portable shape.

### CPython BufferError check before recommending in-place memmove

CPython refuses to resize a bytearray with active memoryview exports.  Before flagging "switch from realloc to in-place," grep the parser for sites that take a memoryview *on the buffer being resized* — if any caller holds the view across the resize (e.g., a `source = memoryview(self._buffer)[off:off+n]` used to hand zero-copy bytes to another method before `_consume`), the in-place change fails BufferError on CPython.  Fix: release the view (`source = None`) before the in-place op.  MP/CP don't track exports, so this is a CPython-specific concern, but it's caught by host-side tests, so the fix is mandatory.

### Zero-copy hand-off across module boundaries

When library A reads via `socket.recv_into(self._recv_view[:cap], cap)` and hands the result to a parser, the hand-off shape matters.  `parser.feed(self._recv_view[:got])` (memoryview slice) is zero-copy; `parser.feed(bytes(self._recv_buffer[:got]))` allocates a fresh bytes object per recv and defeats the recv_into win.  The parser usually accepts either via `chunk_view = chunk if isinstance(chunk, memoryview) else memoryview(chunk)`, but the upstream `bytes(...)` copy already happened — the smell is at the caller, not the parser.  Grep for `return bytes(self._recv` / `parser.feed(bytes(` patterns in recv loops.
