# Workstream: chumicro-http-server deferred features

Status: `parked` — no active driver.  Filed 2026-05-12 during the `/audit-library` pass on `chumicro_http_server`; previously sprinkled "v2 ask" / "(v2)" / "lands in v2" notes in publishable `src/`+`docs/` were removed so the cold reader gets accurate state.  This file is where the bucket lives until a real workload reopens one.

## Purpose

Four out-of-current-scope features for `chumicro_http_server`.  None block on each other; reopen individually when a workload needs them.

## Deferred features

### 1. Multi-parameter routes

`/users/<uid>/posts/<pid>` — current router supports a single trailing parameter only.

### 2. Chunked request bodies

`Transfer-Encoding: chunked` — current parser requires `Content-Length`.

### 3. Streaming body delivery

Streaming-via-chunk-callback body delivery instead of buffering the body up to `max_request_body_bytes`.

### 4. HTTP/1.1 keep-alive / connection pooling

Every response currently emits `Connection: close` and the socket closes after drain.

## Trigger to reopen

Any real workload that hits one of these limits.  When that happens, promote the relevant feature into `plans/next-up.md` as a `## Next` entry pointing back at this file, then design + implement.
