# Hot-path allocation audit — wire-touching libraries

Date: 2026-07-03
Scope: `libraries/{sockets,websockets,mqtt,requests,http_server,msgpack,runner}/src`
Method: read-only source audit against the AGENTS.md §"Library code rules"
memory/performance rubric + `plans/patterns.md` (static recv buffer, cached
`_buf_view`, reuse-buffers, `struct.unpack`-on-memoryview). Two worst paths
quantified on the MicroPython v1.26.0 unix port
(`.tools/micropython-v1.26.0/.../micropython`), `gc.mem_alloc()` bracketed by
`gc.disable()`.

Prior point-fixes WS-1 (hand-indexed unmask) and WS-2 (cached send-view) are
verified still in place; this is the systematic sweep they anticipated.

---

## 1. The canonical "done right" pattern for this codebase

The steady-state shape every wire loop should match, with the codebase's own
reference implementations named:

1. **One persistent recv buffer + cached memoryview, `recv_into` per tick,
   feed a `view[:n]` window (never `bytes(...)`).**
   - `chumicro_mqtt.client._read_inbound` (client.py:1556-1576) — ONE
     `recv_into` into `decoder.fill_buffer()` (a `memoryview` into the
     decoder's own buffer), then `advance(got)` + drain `read_next()`.
   - `chumicro_websockets._session._recv_chunk` (_session.py:792-820) —
     `recv_into(self._recv_view, cap)` into a pre-allocated 512 B buffer,
     returns `self._recv_view[:received]` (zero-copy window).
   - `chumicro_requests.client._drive_recv` (client.py:958-987) and
     `chumicro_http_server.server._Connection._drive_recv` (server.py:345-379)
     — identical shape; `recv_into` + `parser.feed(self._recv_view[:got])`.
   - `chumicro_sockets._adapters.mp._MpSocketWrapper.recv_into` (mp.py:88-126)
     — MP polyfill forwards to `readinto(buffer, size)`, no per-recv `bytes`.

2. **Incremental parser with a three-tier size model + read-cursor + cached
   `_buffer_view`; `struct.unpack(view[a:b])` and `str(view, "utf-8")` with no
   `bytes()` wrap.**
   - `chumicro_mqtt._wire.PacketDecoder` (_wire.py:459-907) — the reference:
     tier-1 steady / tier-2 intact one-shot / tier-3 rolling-discard drain;
     `_read_offset` cursor with `_compact()` half-buffer amortization
     (_wire.py:621-638); `struct.unpack(">H", view[a:b])` (670) and
     `str(view[a:b], "utf-8")` (677) straight off the cached `_buffer_view`.
   - `chumicro_websockets._wire.FrameParser` (_wire.py:797-1117) — tier-1
     `_payload_buffer` + cached `_payload_view`, tier-2 one-shot, tier-3
     `DRAINING_PAYLOAD` sink; hand-indexed unmask keyed on absolute payload
     offset `(write_offset+index) & 3` (963-970, WS-1).
   - `chumicro_requests._wire.ResponseParser` /
     `chumicro_http_server._wire.RequestParser` — read-cursor `_consume`
     compaction via in-place `self._buffer[:offset] = b""`
     (_wire.py:658-668 / 444-454).

3. **Cached `_buf_view` + `bytes(view[:offset])` for the one mandatory payload
   snapshot.** `payload`/`body` properties (websockets _wire.py:875-886, mqtt
   _wire.py:689, requests _wire.py:679-688, http_server _wire.py:469-477) — one
   `bytes()` copy through the cached view, because the public contract is
   `bytes` (handlers `.decode()`).

4. **Send loop caches a memoryview of the outbound buffer and slices the view.**
   - `chumicro_requests.client._drive_send` (client.py:933-956) — `tx_view =
     memoryview(self._tx_buffer)` bound once, `tx_view[self._tx_offset:]` per
     iteration (WS-2 sibling).
   - `chumicro_http_server.server._Connection._drive_send` (server.py:425-444)
     — cached `self._response_view`, `view[offset:end]`.
   - `chumicro_websockets._session._drain_outbound` (_session.py:759-790) —
     `self._tx_partial = (memoryview(popleft()), 0)`, `buffer[offset:offset+budget]`
     (WS-2).

5. **Encoder appends via `struct.pack_into` against a pre-extended slice, not
   `struct.pack` per field.** `_append_packed*` helpers: msgpack _pure.py:21-30,
   websockets _wire.py:37-44, mqtt _wire.py:157-160.

6. **Scheduler dispatch reuses its scratch containers.** `Runner.tick`
   (core.py:432-547) reuses `self._pending` (cleared in `finally`), caches
   `ticks_diff`/`ticks_add` to locals before the loop.
   `Runner._sync_poll_set` (core.py:733-820) is allocation-free in steady state
   — persistent per-socket slot lists, generation-stamped, OR-ed in place; the
   only allocation (the `stale` comprehension, 805) is guarded behind
   `len(registered) > wanted_count` (a socket actually dropping out).

**Lifetime check (clean result):** no memoryview over a *mutated* buffer is
held across a generator `yield`. `_tx_partial` (websockets) and `_response_view`
(http_server) are views over immutable outbound `bytes`, not resized. The mqtt
tier-2 `_drain_payload_view` is held across ticks but over a fixed-size one-shot
bytearray that is never resized mid-drain. Inbound queue entries
(`InboundMessage`, `InboundPublish`) carry real `bytes()` copies, not views. No
`bytes(mv)` where a view would do; no `int.to_bytes`/`from_bytes` churn anywhere
in the seven libraries.

---

## 2. Deviations, ranked by hot-path impact

### D1 — MEDIUM-HIGH · websockets inbound reassembly double-copies every message
`_session.py:681-689` (`_extend_inbound_buffer` → `self._inbound_message_buffer.extend(payload)`),
`_session.py:662` (`message_payload = bytes(self._inbound_message_buffer)`),
`_session.py:715-721` (`_reset_inbound_state` allocates a fresh `bytearray()` per message).

The reassembly buffer exists for *fragmented* messages, but **every** inbound
message pays for it. For the common single-frame message the sequence is:
`FrameParser` unmasks wire→`_payload`; `.payload` property snapshots
`bytes(200)`; `_extend_inbound_buffer` grows a fresh `bytearray()` via `.extend`
(the "alloc-bigger + copy + free" anti-pattern patterns.md warns against); then
`bytes(self._inbound_message_buffer)` copies a *third* time; then
`validate_text_payload` decodes a fourth. The reassembly layer is pure overhead
whenever `fin` is true on the first frame.

Quantified (MP unix port, single 200 B masked binary frame):

| stage | bytes churned |
|---|---|
| `FrameParser.feed` + `reset`, parse only | 544 /frame |
| `.payload` snapshot (inherent, 200 B) | +288 /frame |
| session reassembly `extend`+`bytes` (D1) | **768 /msg** |
| **combined single 200 B message** | **~1.6 KB (8x payload; ~6.5x is avoidable overhead)** |

### D2 — MEDIUM-HIGH · requests chunked-body decode is O(n²) realloc/copy
`_wire.py:1097-1132` (`_absorb_body_chunk` grow path: `new_body =
bytearray(end_offset)` + full copy on every overflow) reached from
`_try_consume_chunk_data` (1010-1048) and the length-unknown path.

The Content-Length path pre-allocates `bytearray(content_length)` once
(_wire.py:929-932) and slice-assigns — clean. But **chunked** and
**length-unknown** bodies have no known total, so each chunk that overflows the
current capacity allocates a new exact-size bytearray and copies everything so
far → quadratic. Bounded only by `max_body_bytes` (default 64 KB): a 64 KB
chunked body churns ~1.2 MB of transient copies on a 264 KB board.

Quantified (MP unix port, 8 KB body, 512 B feeds, 1024 B steady buffer):

| framing | parser-attributable alloc | per body byte |
|---|---|---|
| Content-Length (pre-alloc) | 20,704 B | 2.53 |
| **chunked (grow path)** | **154,560 B** | **18.87** |
| penalty | | **7.47x** |

### D3 — MEDIUM · websockets FrameParser re-allocates its header scratch per frame
`_wire.py:1019, 1023, 1027, 1052` and `reset()` at `_wire.py:901` each do
`self._buffer = bytearray()`. The header/len16/len64/mask fields are re-scratched
into a freshly-allocated empty bytearray several times per frame (plus
`self._mask_key = bytes(self._buffer)` at 1026), instead of a fixed 8-byte
scratch with a write cursor the way `_payload_buffer` already works. Measured:
**544 bytes/frame** of small-tier churn (parse-only, 200 B frame) — precisely
the small-block fragmentation the mqtt suite's non-monotonic-across-16K-boundary
behavior is sensitive to.

### D4 — LOW-MEDIUM · mqtt allocates an empty PUBACK list every RX tick
`client.py:1582` (`pending_pubacks = []`) is allocated on every `_read_inbound`
even when no QoS-1 PUBLISH arrives (the common case for a QoS-0 subscriber).
Per-tick list literal on the recv hot path.

### D5 — LOW · mqtt partial-send resume slices `bytes` instead of a cached view
`client.py:1408` (`self._send_raw(packet[offset:])`) allocates a copy of the
unsent tail on every partial-send resume — the exact shape WS-2 fixed in
websockets/requests/http_server, not carried over to mqtt. Rare path
(only when the socket buffer fills mid-packet), so low steady-state impact, but
an inconsistency with the established pattern.

### D6 — LOW · websockets handshake send slices the buffer twice per tick
`_session.py:459` (`remaining = self._handshake_send_buffer[offset:]`) then
`_session.py:463` (`chunk = remaining[:budget]`) — two `bytes` copies per
handshake-send tick. One-shot per connection (handshake only), so low impact.

### D7 — LOW · websockets outbound mask uses `range()` in a byte loop
`_wire.py:1198` (`for index in range(payload_length): parts[...] ^= mask[...]`)
in `encode_frame`'s client-mask path allocates a `range` iterator. Client-only,
one-shot per outbound frame (the encoder already allocates `parts`), so cheap —
but it is the outbound twin of the WS-1 inbound fix and reads inconsistently.

### D8 — INFORMATIONAL · one-copy returns that are correct as-is
mqtt `_parse_suback` `granted_qos = list(view[...])` (_wire.py:720, per-SUBACK,
infrequent); msgpack `bin8`/`bin16` `bytes(data[a:b])` (_pure.py:231/238,
mandatory immutable return); every `payload`/`body` property `bytes(view[:n])`.
These are the single mandatory copy for the public bytes contract — not
deviations. msgpack `packb`/`unpackb` are one-shot APIs with no reused parser,
so the steady-buffer pattern legitimately does not apply (patterns.md "when not
to apply").

---

## 3. Fix-shape per deviation (one line each)

- **D1** — Fast-path FIN=1-on-first-fragment in `_handle_data_frame`: when no
  message is in progress and this frame is final, hand `payload` straight to
  `on_*`/queue and skip `_inbound_message_buffer` entirely; only build/extend
  the reassembly bytearray once a CONTINUATION actually arrives.
- **D2** — Grow the body buffer geometrically (double capacity) instead of
  exact-size in `_absorb_body_chunk`'s overflow branch, so a chunked body
  amortizes to O(n) copies (or pre-size to a bounded chunked cap).
- **D3** — Give `FrameParser` a fixed 8-byte header scratch + write cursor and
  slice-assign into it, replacing the per-field `self._buffer = bytearray()`
  churn (mirror the `_payload_buffer` treatment).
- **D4** — Lazily allocate `pending_pubacks` on the first QoS-1 PUBLISH (or
  reuse a cleared instance-level list) instead of per-tick.
- **D5** — Store `_partial_send = (memoryview(packet), offset)` and send
  `view[offset:]` (adopt the WS-2 cached-view shape in mqtt).
- **D6** — Cache `memoryview(self._handshake_send_buffer)` once and slice the
  view in `_send_handshake_chunk`.
- **D7** — Replace `for index in range(...)` with a hand-indexed `while` in
  `encode_frame`'s mask loop (match WS-1).

---

## 4. Fixes that need an API / contract change — FLAG FOR PARALLEL DESIGN REVIEW

Two of the findings have an internal fix (above) AND a deeper, higher-payoff
option that changes a *public contract* — surface these to the design review:

- **⚑ D2 → streaming/chunk-callback body API.** The internal geometric-growth
  fix removes the quadratic but still buffers the whole body. Chunked responses
  have no Content-Length, so the parser can never pre-size the way the
  Content-Length path does. Fully honoring the "no transient full-payload
  allocation" budget for streamed bodies requires delivering chunks as they
  arrive (a body-chunk callback / streaming `Response`) instead of the current
  buffer-then-`.body`/`.text` model. That is a public API addition, not an
  internal tweak. **Decision needed:** do we add a streaming-body surface, or
  accept whole-body buffering bounded by `max_body_bytes`?

- **⚑ D1 & the `payload`/`body` snapshot → zero-copy inbound view contract.**
  Every parser's `payload`/`body` property returns `bytes(view[:n])` — a
  mandatory copy *because the public contract promises `bytes`* (handlers
  `.decode()`, which memoryview lacks). The zero-copy ideal (hand callers a
  `memoryview` into the parser's own buffer, whose lifetime ends at the next
  `reset`) would eliminate D1's redundant copies and the snapshot copy at once,
  but changes `InboundMessage.data` / `on_binary` / `Response.body` /
  `Request.body` from an owned `bytes` to a lifetime-bounded view. **Decision
  needed:** is a lifetime-bounded zero-copy inbound view worth the sharper
  contract, or is the one-copy `bytes` snapshot the right cross-runtime default?

Everything in §3 is behavior-preserving and internal; only the two ⚑ items
touch public surface. Per AGENTS.md, any of these that land must carry a
real-board (Pico W minimum) allocation bake before "done."
