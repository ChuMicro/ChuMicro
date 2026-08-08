# Pure-passthrough `@property` sweep across device libraries — DONE

Per [Decision 0065](../../decisions/0065-device-library-scaffolding-cost.md), pure-passthrough `@property` declarations (`def state(self): return self._state`) are banned in `libraries/*/src/`.  Replaced with direct public attributes (`self.state = ...` in `__init__`).  Computed properties (real work — `bytes(view[:offset])`, `len(self._queue)`, `self._state in (DONE, ERROR)`) kept.

**Status (2026-05-14):** all `src/` passthroughs dropped.  10 libraries swept in order — chumicro_timing → chumicro_mqtt → chumicro_events → chumicro_kvstore → chumicro_logging → chumicro_wifi → chumicro_ntp → chumicro_requests → chumicro_websockets (chumicro_http_server already done 2026-05-12).  Each library landed as one commit + a patch `VERSION` bump (check-api confirmed patch is sufficient for the 0.x pre-1.0 SemVer semantics).  See `git log --grep "Decision 0065"` for the full series.

`testing.py` passthroughs remain — `("cpython",)`-marked, the flash-cost argument doesn't apply, and the per-access cost on MP/CP unix-port test runs is the only remaining lever.  Inventory preserved below for a future pass.

## Per-library findings

### chumicro_websockets

**`src/chumicro_websockets/_wire.py`** — 17 properties; 15 drop, 2 keep.

Drop (pure passthroughs):

| Line | Property | Class |
|---|---|---|
| 518 | `state` | `HandshakeRequestParser` |
| 523 | `http_version` | `HandshakeRequestParser` |
| 528 | `headers` | `HandshakeRequestParser` |
| 533 | `error` | `HandshakeRequestParser` |
| 538 | `leftover` | `HandshakeRequestParser` |
| 675 | `status_code` | `HandshakeResponseParser` |
| 680 | `reason` | `HandshakeResponseParser` |
| 738 | `method` | `HandshakeServerRequestParser` |
| 743 | `path` | `HandshakeServerRequestParser` |
| 893 | `state` | `FrameParser` |
| 898 | `fin` | `FrameParser` |
| 903 | `rsv` | `FrameParser` |
| 908 | `opcode` | `FrameParser` |
| 913 | `had_mask` | `FrameParser` |
| 929 | `error` | `FrameParser` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 748 | `client_key` | `self._headers.get("Sec-WebSocket-Key", "")` |
| 918 | `payload` | Snapshots bytes from internal buffer |

**`src/chumicro_websockets/server.py`** — 5 properties; 3 drop, 2 keep.

Drop:

| Line | Property | Class |
|---|---|---|
| 135 | `request_path` | `Connection` |
| 140 | `request_headers` | `Connection` |
| 447 | `closed` | `WebSocketServer` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 437 | `connections` | `tuple(self._connections)` |
| 442 | `connection_count` | `len(self._connections)` |

**`src/chumicro_websockets/_session.py`** — 4 properties; 4 drop, 0 keep.

| Line | Property |
|---|---|
| 212 | `state` |
| 217 | `last_close_code` |
| 222 | `last_close_reason` |
| 227 | `last_error` |

**`src/chumicro_websockets/client.py`** — 1 property; 1 drop.

| Line | Property |
|---|---|
| 262 | `url` |

### chumicro_requests

**`src/chumicro_requests/client.py`** — 8 properties; 4 drop, 4 keep.

Drop:

| Line | Property | Class |
|---|---|---|
| 259 | `url` | `RequestHandle` |
| 264 | `done` | `RequestHandle` |
| 269 | `response` | `RequestHandle` |
| 274 | `error` | `RequestHandle` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 203 | `encoding` | Lazy Content-Type sniff, cached |
| 220 | `text` | `body.decode(encoding)` |
| 279 | `result` | Raises if error, else returns response |
| 524 | `busy` | `self._state != _RequestState.IDLE` |

**`src/chumicro_requests/_wire.py`** — 7 properties; 6 drop, 1 keep.

Drop:

| Line | Property |
|---|---|
| 641 | `state` |
| 646 | `status_code` |
| 651 | `reason` |
| 656 | `http_version` |
| 661 | `headers` |
| 677 | `error` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 666 | `body` | `bytes(self._body_view[:self._body_write_offset])` |

### chumicro_http_server — DONE (2026-05-12, audit-embedded pass)

All 7 pure-passthrough properties dropped (6 in `_wire.py`, 1 in `server.py`); 4 computed properties kept (`RequestParser.body`, `_Connection.is_done`, `HttpServer.listening`, `HttpServer.in_flight`).  Public API stays — callers still write `parser.state` / `connection.state`; backing field is now a direct public attribute.

**`src/chumicro_http_server/server.py`** — 4 properties; 1 drop, 3 keep.

Drop:

| Line | Property | Class |
|---|---|---|
| 226 | `state` | `_Connection` (module-private — pure scaffolding) |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 230 | `is_done` | `self._state in (_ConnState.DONE, _ConnState.ERROR)` |
| 801 | `listening` | `self._listener is not None` |
| 806 | `in_flight` | `len(self._connections)` |

### chumicro_logging

**`src/chumicro_logging/core.py`** — 9 properties; 7 drop, 2 keep.

Drop:

| Line | Property | Class |
|---|---|---|
| 81 | `name` | `Logger` |
| 86 | `level` | `Logger` |
| 100 | `handler_errors` | `Logger` |
| 192 | `level` | (handler class) |
| 253 | `level` | `BufferedHandler` |
| 262 | `capacity` | `BufferedHandler` |
| 272 | `dropped` | `BufferedHandler` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 95 | `handlers` | `tuple(self._handlers)` |
| 267 | `buffered` | `len(self._buffer)` |

### chumicro_ntp

**`src/chumicro_ntp/core.py`** — 8 properties; 5 drop, 3 keep.

Drop:

| Line | Property | Class |
|---|---|---|
| 117 | `done` | `NTPResult` |
| 137 | `error` | `NTPResult` |
| 299 | `server` | `NTPClient` |
| 304 | `port` | `NTPClient` |
| 309 | `timeout_ms` | `NTPClient` |
| 319 | `socket` | `NTPClient` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 122 | `unix_seconds` | Raises if not done; computed validation |
| 314 | `busy` | `self._result is not None and not self._result.done` |

### chumicro_events

**`src/chumicro_events/core.py`** — 6 properties; 5 drop, 1 keep.

Drop:

| Line | Property |
|---|---|
| 82 | `capacity` |
| 92 | `dropped` |
| 97 | `handler_errors` |
| 102 | `drained` |
| 112 | `delivered` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 87 | `buffered` | `len(self._queue)` |

### chumicro_wifi

**`src/chumicro_wifi/service.py`** — 5 properties; 3 drop, 2 keep.

Drop:

| Line | Property |
|---|---|
| 110 | `state` |
| 135 | `last_error` |
| 140 | `adapter` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 115 | `connected` | `self._state == WifiState.CONNECTED` |
| 120 | `ip` | Stringifies per-runtime, allocates intentionally |

**`src/chumicro_wifi/_adapters/cp.py`** — 1 property; 1 drop.

| Line | Property |
|---|---|
| 38 | `radio` |

### chumicro_kvstore

**`src/chumicro_kvstore/core.py`** — 4 properties; 3 drop, 1 keep.

Drop:

| Line | Property |
|---|---|
| 266 | `capacity` |
| 275 | `is_corrupt` |
| 283 | `backend_name` |

Keep (computed):

| Line | Property | Why keep |
|---|---|---|
| 270 | `bytes_used` | `len(packb(self._data))` — encodes on every read |

### chumicro_mqtt

**`src/chumicro_mqtt/client.py`** — 2 properties; 2 drop, 0 keep.

| Line | Property |
|---|---|
| 565 | `state` |
| 570 | `last_error` |

### chumicro_timing

**`src/chumicro_timing/heartbeat.py`** — 1 property; 1 drop.

| Line | Property |
|---|---|
| 37 | `period_ms` |

## `testing.py` properties — lower priority

`testing.py` is `("cpython",)`-marked; the flash-cost argument doesn't apply but Decision 0065 still names them.  Per-access cost on MP/CP unix-port test runs is the only remaining consideration; do these last or skip entirely if test-suite ergonomics suffer.

| File | Count |
|---|---|
| `libraries/wifi/src/chumicro_wifi/testing.py` | 3 |
| `libraries/sockets/src/chumicro_sockets/testing.py` | 8 |
| `libraries/requests/src/chumicro_requests/testing.py` | 1 |
| `libraries/kvstore/src/chumicro_kvstore/testing.py` | 1 |
| `libraries/events/src/chumicro_events/testing.py` | 2 |
| `libraries/logging/src/chumicro_logging/testing.py` | 3 |

## Suggested execution order

1. **Small libs first** — `chumicro_timing` (1), `chumicro_mqtt` (2), `chumicro_wifi/_adapters/cp.py` (1), `chumicro_websockets/client.py` (1).  Mechanical confidence-building.
2. **Mid-size libs** — `chumicro_events`, `chumicro_kvstore`, `chumicro_logging`, `chumicro_wifi/service.py`.
3. **HTTP-shape libs** — `chumicro_ntp`, `chumicro_requests`, `chumicro_http_server`.  Same pattern across all four `_wire.py` files; can run as a batch with consistent diffs.
4. **`chumicro_websockets` last** — biggest single library, most properties, most parsers; run after the smaller libs have settled the pattern.

VERSION bump per the audit-library skill rule: most are patch-level (the public attribute name stays the same, so `from chumicro_X import C; c.state` works identically before and after); `check-api` will confirm.  If a library's property had a docstring describing read-only-via-property semantics, the rewrite is the bump driver — minor.

Each library's commit also drops the now-redundant `_underscored` field name (rename `self._state` → `self.state` in `__init__` and all internal references).  Lint passes for the no-leading-underscore convention come along for free.

## Skill cross-references

* `/audit-library` §7 (Decision 0065 bullet) — surfaces this finding mechanically on any future audit pass.
* `plans/patterns.md` "Device-library scaffolding cost" — the durable how-to with worked examples.
* Decision 0065 — the rule itself + alternatives considered.
