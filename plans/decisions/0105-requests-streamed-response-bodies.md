# Decision 0105: Streamed response bodies in chumicro-requests

Status: `accepted`
Date: `2026-07-04`
Summary: Streamed response bodies via stream=True: fixed staging window with recv backpressure; RequestHandle.read_body_into is the polled floor, generators.stream a thin adapter; fetch now rides HttpClient.
Related: Decision 0089 (generator surfaces), Decision 0097 (service io contract), Decision 0087 (generator substrate), Decision 0094 (board-shaped heap budgets)

## Context

chumicro-requests buffered every response body in RAM, bounded only by
`max_body_bytes` (default 64 KB). The 2026-07-03 hot-path buffer audit (D2) fixed
the chunked O(n²) grow internally but flagged the deeper contract question: a
device HTTP client meets firmware downloads, log pulls, and large JSON that must
not — or cannot — fit the heap of a 256 KB-class board. The 2026-07-04 check/handle
re-pose (KEEP) fixed the layering constraint: any streaming surface must work from
the polled-object floor, with the generator form a thin adapter, and
`requests/generators.fetch` was already the fleet's only parallel drive of shared
machinery — a design that added a second one would trip that report's reopening
criterion 2.

## Decision

**Streaming is a per-request opt-in on the existing client** — `stream=True` on
every verb and on the new generic `HttpClient.request(method, url, ...)`; buffered
stays the default.

**The base surface is polled, on the objects that already exist.** For a streamed
request, `RequestHandle.response` publishes at final-hop headers-complete (before
`done`); `RequestHandle.read_body_into(buffer) -> int` copies decoded body bytes
into a caller-owned buffer, `0` meaning "none this tick" and, once `done`,
"end of body". `Response.streamed` is `True`, `body` is `b""`, and `.text` /
`.json()` refuse. `HttpClient.cancel()` (new) aborts an in-flight request.

**Bounded by a fixed staging window with structural backpressure.**
`ResponseParser(stream_body=True)` turns its body buffer (per-request,
`HttpClient(stream_buffer_size=...)`, default 1024 B) into a read-cursor staging
window; the client bounds every `recv_into` by `parser.body_free()`, so staging can
never overflow, and `io_interest` reports `0` while it is full so the runner parks
instead of spinning. Chunked, Content-Length, and read-until-close framings all
stream through the one absorb path; redirect-hop bodies are discarded from staging
and never published.

**`max_body_bytes` / `WhenOversized` do not apply to streamed bodies.** The cap is
a heap bound and the stream's heap bound is the staging window (the rolling-sink
arm of the heap-DoS rule); a byte-ceiling caller counts and cancels. `timeout_ms`
bounds the whole transfer including consumption.

**The generator layer is an adapter over the same machinery.** A check/handle
service is already a valid generator wait token, so
`chumicro_requests.generators.stream(...)` drives a per-call `HttpClient` and
returns a `BodyReader` (`response`, `read_into(buffer)`, `cancel()`);
`generators.fetch` was rewritten onto the same drive, deleting its parallel
implementation of URL parsing, request encoding, socket I/O, redirect following,
and parser feeding. `chumicro_requests.generators` no longer imports
`chumicro_sockets` at all.

## Consequences

- Bodies of any size are consumable on a 264 KB board at a fixed
  ~1 KB + caller-buffer RAM cost; the Content-Length peer-sized pre-allocation is
  skipped in stream mode.
- New public surface: `stream=` kwarg, `HttpClient.request`, `HttpClient.cancel`,
  `stream_buffer_size=`, `RequestHandle.read_body_into`, `Response.streamed`,
  `generators.stream` + `BodyReader`. VERSION minor bump (0.18.0).
- `fetch` behavior deltas: non-EAGAIN socket errors surface as `HttpError`
  (its documented raise list), and it yields the client as its wait token.
  Per Decision 0092, consumers/tests migrated in the same commit.
- The re-pose census's "one genuine parallel drive" is now zero; the generator
  lane's translation weight in requests shrank instead of growing.
- A streamed handle keeps its (per-request) staging alive until dropped; issuing
  the next request never aliases it.

## Rejected

- **Callback-per-chunk** — puts consumer work and consumer exceptions inside the
  client's tick; per-chunk copy or lifetime-bounded view contract; callbacks are
  the fleet's lifecycle vocabulary, not its data plane.
- **File-like `.read(n)`** — per-call `bytes` allocation on the hot path and a
  `None`/`0` EOF convention foreign to the fleet's `recv_into`-style
  fill-a-buffer idiom.
- **Asyncio-style stream object** — `async` is banned (Decision 0087 / CHU033);
  an awaitable stream would be a second base contract, exactly what the
  check/handle re-pose's reopening criteria forbid.
- **Caller-pre-allocated whole-body buffer** (`body_into=`) — removes the
  allocation, not the RAM ceiling; useless for the firmware-download case.
- **Streaming as the default** — every existing caller polls `handle.done` only;
  defaulting to a surface that requires an active drain would stall them all.
