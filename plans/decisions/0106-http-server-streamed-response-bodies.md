# Decision 0106: Streamed response bodies in chumicro-http-server

Status: `accepted`
Date: `2026-07-04`
Summary: Server bodies stream via a handler byte source (0=dry, -1=EOF); framing chosen by known-total; fixed per-stream staging window; opt-in streaming submodule so non-streaming servers pay nothing.
Related: Decision 0105 (requests streamed response bodies), Decision 0089 (generator surfaces), Decision 0094 (board-shaped heap budgets), Decision 0092 (pre-publication API churn)

## Context

`chumicro_http_server` buffered every response body in RAM (`Response.body`),
so a handler serving a sensor-log dump or a file off storage had to
materialize the whole body first — impossible past the heap of a 256 KB-class
board. Decision 0089 flagged this as http_server's one generator-shaped want
("only streaming response bodies would use generators, a separate future
capability"); Decision 0105 shipped the client-side mirror (streamed *reads*
out of a fixed staging window) and explicitly unlocked the server-side
inversion. This decision ships it: the handler PUSHES a body larger than the
heap, and the server drains it to the socket across ticks.

## Decision

**The handler supplies a byte SOURCE, the server drains it.** A handler returns
a `StreamingResponse` (built with `build_streaming_response(status, *, source,
content_length=None, headers=None)`) carrying `source(buffer) -> int` — the
fleet fill-a-buffer idiom. Each tick the server hands the source the staging
window; the source returns `n > 0` (wrote `buffer[:n]`), `0` (no bytes ready
this tick, body not finished — re-poll later), or `SOURCE_EOF` (`-1`, end of
body). The server recognizes a streaming response by duck type (its `source`
attribute), not `isinstance`, so the buffered path is unchanged.

**EOF vs dry: a distinguished sentinel, not a second oracle.** `requests`'
`read_body_into` distinguishes 0-before-`done` from 0-after-`done` by consulting
the response parser, which learns EOF from the wire framing. A server source has
no external oracle — it IS the authority on end-of-body — so it must signal EOF
itself. A negative sentinel (`SOURCE_EOF = -1`) carries EOF in the single `int`
return, leaving `0` to mean "dry this tick"; no per-call tuple, no second
property, and a log/file generator that has bytes until it ends never returns
`0` (it returns counts then `SOURCE_EOF`).

**Framing chosen by whether the total is known.** `content_length=` given →
`Content-Length` header, body framed raw (the source must produce exactly that
many bytes before `SOURCE_EOF`; a mismatch breaks framing and closes).
`content_length=None` (default) → `Transfer-Encoding: chunked`. Chunked framing
allocates nothing per chunk beyond the reused staging buffer: the chunk-size
line is written in place into a reserved head region of the buffer and the
trailing CRLF into a reserved tail, so a whole chunk is one contiguous send.

**Bounded by a fixed per-stream staging window with the existing send
discipline.** `stream_buffer_size` (constructor knob, default 1024 B, mirroring
0105) is the whole per-stream heap cost: minted lazily (only a connection that
streams allocates one), reused for the transfer, and never grown by a stalled
client — the source is re-polled only after the current fill fully drains to the
socket. The streamed send reuses `send_budget_per_tick` (not a parallel bound),
so one stream can't starve other connections. `request_timeout_ms` bounds the
whole streamed send and closes a stalled client, mirroring 0105's `timeout_ms`
bounding the whole transfer — size it for the download.

**Streaming is an opt-in submodule, so a non-streaming server pays nothing.**
`StreamingResponse` / `build_streaming_response` / `encode_streaming_headers`
live in `chumicro_http_server.streaming` (imported explicitly, like
`chumicro_requests.generators`), NOT the base package. `HttpServer`
duck-recognizes and lazy-loads the framing machine only to drive a streaming
response, so a buffered-only server never loads its ~10 KB of bytecode — the
structural pay-for-what-you-use split that keeps the base import cost flat and
the 208 K / 192 K unix heap lanes green.

**Handler failures mid-stream close the connection.** Once the first body byte
is on the wire the response is committed — an error page can't be spliced in. A
source that raises, or under-/over-runs a declared `Content-Length`, closes the
connection (the client sees a truncated body) through the connection's existing
`except (OSError, ServerError)` fail-and-close path. Work that can fail (opening
the file, the first query) belongs before the `StreamingResponse` is returned,
where it can still become a clean 500.

## Consequences

- New public surface: the `chumicro_http_server.streaming` submodule
  (`StreamingResponse`, `build_streaming_response`, `encode_streaming_headers`,
  `SOURCE_EOF`, `DEFAULT_STREAM_BUFFER_SIZE`); `stream_buffer_size=` constructor
  knob + `http_server.stream_buffer_size` config key; `WANT_SEND_BODY`
  connection state. VERSION minor bump (0.18.0).
- Bodies of any size are servable on a 264 KB board at a fixed
  ~`stream_buffer_size` + framing RAM cost; the base import cost is flat
  (+~1 KB for the duck check + two constants), the framing bytecode loading
  only on the first stream.
- The buffered response path is byte-identical (bake-validated; 155 pre-existing
  tests unchanged).
- Decision 0089's "streaming response bodies, a separate future capability" is
  trued in place: the capability shipped as a byte source, not a `yield from`
  surface, so the generator-surface rejection still stands.

## Rejected

- **A `yield from` / generator source.** The server DRIVES the source one window
  per tick; a generator would invert control and still need the same dry-vs-EOF
  sentinel. The fill-a-buffer source is the fleet idiom and a 5-line generator
  implements it. (This is why 0089's generator-surface rejection is unchanged.)
- **`0`-means-EOF (the Unix `read` / `recv_into` convention).** It collides with
  "dry this tick". `recv_into` uses 0=EOF but raises EAGAIN for dry; a handler
  source raising EAGAIN would be un-idiomatic, so a negative EOF sentinel keeps
  the source a plain int-returning function.
- **A separate `done` flag alongside the source** (mirroring `read_body_into`).
  That reader has a parser that independently knows EOF; a server source does
  not, so a second signal is redundant surface. A 2-tuple `(n, done)` return
  allocates per call.
- **Refreshing the deadline on send progress (idle-timeout semantics).**
  Rejected for `request_timeout_ms` bounding the whole transfer, mirroring
  0105's `timeout_ms`; simpler, documented as "size the timeout for the
  download."
- **Keeping streaming in the base module.** ~10 KB of always-loaded bytecode
  tips pre-existing edge tests over the 192 K CP heap lane; the opt-in submodule
  is both the heap fix and the fleet idiom.
- **Callback-per-chunk, whole-body buffer, streaming-as-default** — same
  rejections as Decision 0105 (consumer work inside the tick, no RAM ceiling,
  stalls existing pollers).
