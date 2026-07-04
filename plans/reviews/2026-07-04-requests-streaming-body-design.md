# requests streaming-body API — design (D2 follow-through)

Date: 2026-07-04
Scope: `libraries/requests/src/chumicro_requests/{client.py,_wire.py,generators.py,testing.py}`.
Commissioned by the 2026-07-03 hot-path buffer audit §4 (⚑ D2): the geometric-growth
interim (shipped, `_wire.py` `_absorb_body_chunk` doubling branch) removed the O(n²)
copy churn but still buffers the whole body; "streaming-body API is an open design."
Read for this design: the audit, Decision 0089 (which work earns a generator surface),
the 2026-07-04 check/handle re-pose (§6 KEEP verdict — the polled object is the floor;
§3b/§ (c) — `generators.fetch` is the fleet's one genuine parallel drive, reopening
criterion 2 forbids a third), and the full requests source + test suite.

## 1. Problem

A response body materializes fully in RAM. `max_body_bytes` (default 64 KB) is the
only bound; on a 264 KB board an 8 KB body is a real heap event and anything over
`max_body_bytes` is impossible — while firmware-download, log-pull, and large-JSON
are exactly the workloads a device HTTP client meets. The Content-Length path
pre-allocates `bytearray(content_length)` (one peer-sized allocation, capped);
chunked / length-unknown grow geometrically. Both shapes hold the whole body until
`Response.body` snapshots one more `bytes()` copy.

The fix is incremental consumption bounded by a caller-supplied buffer: the client
holds at most a small fixed staging window; the caller drains it tick by tick into
their own buffer and the socket recv pauses (backpressure) while staging is full.

## 2. The shipped design

### 2a. Base surface — the check/handle floor (client.py)

Streaming is a per-request opt-in kwarg, named after the CPython `requests` spelling
this library already borrows:

```python
handle = client.get(url, stream=True)          # every verb + client.request()
```

New / changed public surface:

| Symbol | Signature / behavior |
|---|---|
| `HttpClient.get/post/put/patch/delete(..., stream=False)` | opt-in per request |
| `HttpClient.request(method, url, *, body=None, json=None, headers=None, timeout_ms=None, max_redirects=None, on_done=None, stream=False)` | generic verb entry (new; the generator layer rides it) |
| `HttpClient(..., stream_buffer_size=DEFAULT_STREAM_BUFFER_SIZE)` | staging capacity for streamed requests (default 1024 B) |
| `HttpClient.cancel()` | abort the in-flight request: socket/connector closed, handle fails with `HttpError("request … cancelled")`, `on_done` fires; no-op when idle. Fills the `cancel()` slot of the 0097 optional service vocabulary the client previously left empty, and gives a stalled stream consumer an exit that doesn't wait for the timeout |
| `RequestHandle.read_body_into(buffer) -> int` | copy decoded-but-unread body bytes into a caller-owned buffer/memoryview; `0` = none available this tick; after `handle.done` (no error), `0` = end of body. Raises `HttpError` on a request not issued with `stream=True` |
| `RequestHandle.response` | for streamed requests, populated at final-hop headers-complete — *before* `done` — so the consumer can branch on status/headers while the body trickles |
| `Response.streamed` | `True` on a streamed response; `body` is `b""`, `.text` / `.json()` raise `HttpError` instead of silently decoding an empty body |

Consumer-service loop (the polled floor everything else layers on):

```python
def handle(self, now_ms):                      # any check/handle service
    request = self._request
    if request.done and request.error is not None:
        self._fail(request.error); return
    if request.response is None:
        return                                  # headers not in yet
    count = request.read_body_into(self._view)  # caller-owned buffer
    if count:
        self._sink(self._view[:count])
    elif request.done:
        self._finish()                          # 0 after done == EOF
```

Runner composition: the client's `io_interest` returns `0` (instead of `IO_READ`)
while streaming staging is full, so `Runner.wait` does not spin on a readable socket
nobody will drain; `next_deadline` still returns the request deadline, so the timeout
fires even against a stalled consumer. The consumer service's own `check()` keeps
the runner ticking while it drains. When staging has room again the interest returns
to `IO_READ` and the poll set re-registers — no new runner vocabulary needed.

### 2b. Wire layer (_wire.py)

`ResponseParser(stream_body=True, body_buffer=...)` turns the body buffer into a
fixed-capacity staging window with a read cursor instead of an accumulator:

- `headers_complete` — set once the final (non-1xx) header block is parsed.
- `body_free() -> int` — writable staging space; the client bounds **every** recv by
  it (`min(scratch, budget-consumed, body_free())`), which is what guarantees a feed
  can never overflow staging (decoded bytes ≤ wire bytes for all three framings).
- `read_body_into(buffer) -> int` — slice-assign out of the staging memoryview into
  the caller's buffer; cursors reset to 0 on full drain (allocation-free; no
  compaction copy — the producer simply stalls until the consumer drains).
- `discard_body()` — used for redirect-hop bodies.
- Stream mode skips the Content-Length pre-allocation (the peer-sized `bytearray(N)`
  the audit's D2 note calls out), skips the `max_body_bytes` checks (see 2d), and the
  grow branch of `_absorb_body_chunk` becomes a latched `HttpError` (staging is a
  hard bound; the client never trips it — only a standalone misuse can).

All three framings stream through the same absorb path the buffered mode uses:
Content-Length clamps and finishes at `remaining == 0`, chunked decodes frame-by-frame
out of the header staging buffer, length-unknown ends at `feed_eof`. No second parser,
no second state machine.

### 2c. Redirects, errors, lifecycle

- A 3xx hop with budget + `Location` is never published: its body bytes are discarded
  from staging as they arrive and the hop follows at `DONE` exactly as buffered mode
  does. Budget exhaustion publishes the 3xx as the final streamed response (buffered
  parity).
- Errors (timeout, protocol, socket, cancel) fail the handle as today; `done=True` +
  `error` set. `read_body_into` stays mechanical (staged bytes remain readable);
  the generator reader raises the error instead of handing out more bytes.
- After `DONE` the client resets to idle; the handle keeps the parser (and its
  staging) alive until the caller drops it. Staging is a **per-request** allocation
  (1 KB default) precisely so a finished-but-undrained handle can never alias the
  next request's buffer; buffered requests keep the client's shared long-lived
  body buffer exactly as before.

### 2d. `max_body_bytes` and `WhenOversized` do not apply to streamed bodies

The cap exists as a heap bound; a streamed body's heap bound is `stream_buffer_size`
plus the caller's own buffer (AGENTS "pre-allocated steady-state buffer as a rolling
sink" arm of the heap-DoS rule). Enforcing the 64 KB default against the exact
workload streaming exists for (multi-hundred-KB firmware) would make every stream
call carry a `max_body_bytes=` override. A caller that wants a byte ceiling counts
what it reads and calls `client.cancel()` (or `BodyReader.cancel()`). Documented in
the guide.

The per-request `timeout_ms` still bounds the **whole** transfer, consumption
included — a streamed download must be issued with a timeout sized for the transfer.

### 2e. Generator surface (generators.py) — thin adapter, and the parallel drive removed

Per 0089, one-shot waits and receive streams earn `yield from`. Both now ride the
`HttpClient` itself as the wait token (a check/handle object already satisfies the
duck-typed wait protocol — same trick `sockets.generators.connect` uses with the
connector), with the runner-sent `now_ms` threading into `client.handle(now_ms)`:

```python
# one-shot (existing surface, same signature, new plumbing)
response = yield from fetch(transport_factory, "GET", url)

# streaming (new)
reader = yield from stream(transport_factory, "GET", url, timeout_ms=120_000)
print(reader.response.status_code)
while True:
    count = yield from reader.read_into(view)   # caller-owned buffer
    if count == 0:
        break                                   # end of body
    consume(view[:count])
```

`stream(...)` drives the client until `handle.response` publishes, then returns a
`BodyReader` (`.response`, `.read_into(buffer)` generator method, `.cancel()`).
`read_into` reads from the handle, yields the client on empty, resumes with the
runner's `now_ms`, and raises `handle.error` on failure — ~25 lines over the base
machinery.

**What shrank:** `fetch` no longer re-drives `_wire` (URL parse, request encode,
`connect`/`send_all`, recv loop, redirect loop, oversize/timeout enforcement — the
parallel drive the re-pose census flagged). It now issues
`client.request(...)` with `when_oversized=DISCONNECT` and yields the client until
done. `generators.py` drops its `chumicro_sockets.generators` / `waits` imports
entirely; the only machinery left in the module is wait-token plumbing. Measured
with the real minifier (`chumicro_deploy.source_minify.strip_source`): 5,252 B
stripped before (fetch only) → 4,215 B after (fetch **plus** the whole new
`stream`/`BodyReader` surface) — 20 % smaller while gaining a capability.
Reopening criterion 2 of the re-pose (a third parallel surface) is not just
avoided — the count went from one parallel drive to zero.

Behavioral deltas from the fetch rewrite (0092: break and migrate in the same
commit): non-EAGAIN socket errors now surface as `HttpError("socket error: …")`
(matching `fetch`'s documented raise list, which never included raw `OSError`), and
the wait yielded is the client token rather than connector-then-`ReadWait`. One test
asserted each; both updated.

### 2f. Default / opt-in decision

Buffered stays the default; `stream=True` is the opt-in, per-request. Rationale:
the fleet's dominant traffic is small JSON (the 1 KB steady body buffer was sized
for it); buffered `Response.body/.text/.json()` is the ergonomic contract every
existing consumer uses (43 sister-repo registrations, demos, examples); and
streaming demands an active consumer — making it a default would turn every
unmodified caller into a stalled request. A kwarg (not a separate client, not a
separate method-set) keeps one client, one pipeline, one parser.

## 3. Rejected alternatives

- **Callback-per-chunk** (`on_body_chunk=`) — inverts control on the hot path: the
  chunk arrives inside `HttpClient.handle`'s tick, so consumer work (flash write,
  hash update) lands inside the client's ≤5 ms tick budget and a raising callback
  lands inside the pipeline's error handling (the exact misattribution bug
  `_fire_completion` exists to prevent). It also hands the consumer a
  parser-lifetime memoryview or forces a per-chunk copy — either a sharp lifetime
  contract or the allocation we're removing. Callbacks are the fleet's *lifecycle*
  vocabulary, not its data-plane (0089's invariant; 0099 deleted mqtt's
  pattern-router for the same reason).
- **File-like `.read(n)` object** — `read(n)` returning `bytes` allocates per call
  (the hot-path rule bans per-chunk `bytes()`); a non-blocking `readinto` needs the
  CPython `None`/`0` EOF convention, which inverts this fleet's "0 = not yet"
  polling idiom and would be the only file-object in a fleet that speaks
  check/handle + `recv_into` everywhere else. The chosen `read_body_into` keeps the
  fill-a-caller-buffer shape (`recv_into`, `readinto` on the adapters) with
  EOF = `0 after done`, which needs no sentinel object.
- **Full asyncio-style stream** (`StreamReader` / `async for chunk`) — `async` is
  banned in library code (CHU033, 0087); and per the 0089/0097/re-pose line, any
  streaming surface must work from the polled-object floor with the generator layer
  as a thin adapter. An awaitable-stream abstraction would *be* the parallel
  contract the re-pose's reopening criterion 2 forbids, and its buffering model
  (unbounded feed queue) is exactly the heap shape a 264 KB board can't carry.
- **Whole-body `bytearray` handoff** (`body_into=bytearray`) — caller pre-allocates
  the full body; removes the parser's allocation but not the RAM ceiling, so it
  solves none of the firmware-download cases. Also considered and dropped: keeping
  a *client-level* shared staging buffer for streams (aliases with a
  finished-but-undrained handle; the 1 KB per-request allocation is the cheaper
  correctness).
- **Streaming `max_body_bytes` enforcement by default** — see 2d; enforcement would
  default-break the target workload. The bound streaming actually guarantees is the
  staging capacity, which is enforced structurally (recv bounded by `body_free()`).

## 4. Test and validation shape

- `tests/test_wire_stream.py` — parser staging: fixed capacity, cursor reset,
  `body_free` accounting, chunked + Content-Length + length-unknown decode into
  staging, redirect-body discard, staging-overflow latch, 1xx handling,
  `headers_complete`.
- `tests/test_client_stream.py` — Content-Length streaming end-to-end on
  `FakeSocket`: headers-early publish, drain-across-ticks, EOF contract,
  body > `max_body_bytes` streams, backpressure (recv stalls at full staging,
  `io_interest` drops to 0, resumes after drain), redirect hop, `.text` guard,
  non-streamed `read_body_into` raises, `cancel()`.
- `tests/test_client_stream_chunked.py` — chunked + length-unknown streaming,
  slow-trickle byte-at-a-time across ticks with EAGAIN interleave, oversize-cap
  bypass, mid-stream peer-close error.
- `tests/test_generators_stream.py` — `stream()`/`BodyReader` happy path, error
  propagation, reader cancel, GeneratorExit-closes-socket for both `stream` and
  `fetch`.
- `tests/test_client_fake_stream.py` — `FakeHttpClient` streamed scripting +
  `cancel` parity.
- Existing suites updated where the fetch rewrite changed contracts (§2e):
  `test_generators_errors.py` (HttpError instead of raw OSError; client wait-token
  shape instead of `ReadWait`), `test_generators_fetch.py` unchanged and green.
- Suites are split per file to stay inside the 224K/224K unix-lane overrides
  (bodies ≤ 3 KB); no override raise.
- Validation: `preflight --coverage-threshold 94` green end to end — lint, build,
  docs, CPython suite (requests package 97.6 % branch coverage), MicroPython +
  CircuitPython unix-port lanes (all five new/updated stream suites ran on both),
  verify-examples/demos, check-version/api.

## 5. Draft ADR (numbering assigned at integration)

```markdown
# Decision NNNN: Streamed response bodies in chumicro-requests

Status: `proposed`
Date: `2026-07-04`
Summary: `Response bodies stream on opt-in (stream=True): the parser stages decoded bytes in a fixed caller-drained window with recv backpressure; RequestHandle.read_body_into is the polled floor, generators.stream/BodyReader the thin generator adapter; generators.fetch now rides HttpClient, deleting the fleet's one parallel wire drive.`
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
```

## 6. Follow-ups (not in this change)

- Real-board bake (Pico W minimum) of a streamed multi-hundred-KB download per
  AGENTS' hot-path rule — flagged for the next hardware session; unit lanes (CPython
  + MP/CP unix ports) cover the logic.
- An idle-progress timeout (reset-on-bytes) as a friendlier alternative to sizing
  `timeout_ms` for whole-transfer duration — deferred until a consumer asks.
- `chumicro_http_server` streamed *response* bodies (0089 flagged this as that
  library's only generator-shaped want) can now copy this staging pattern.
