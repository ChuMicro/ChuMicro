# Workstream: Extract `chumicro-http` (shared HTTP/1.1 primitives)

Status: `proposed` — surfaced by `/audit-workspace` on 2026-05-11 (Claim E2); not yet started.  Trigger condition documented in three ADRs is met; deferral text is now stale.

## Purpose

Three libraries each ship a private copy of the same four HTTP/1.1 primitives.  Extract them into a small shared library so future fixes land once and stay in sync.

| Primitive | requests | http_server | websockets |
|---|---|---|---|
| `CRLF = b"\r\n"`, `CRLF_CRLF = b"\r\n\r\n"` | `_wire.py:119` | `_wire.py:56` | `_wire.py:112` |
| `CaseInsensitiveDict` (full surface) | `_wire.py:305` (~70 LOC) | `_wire.py:86` (~70 LOC, comment "matches requests") | — |
| `CaseInsensitiveDict` (slim — no `__iter__`/`__len__`/`__eq__`/`__repr__`/`add()`) | — | — | `_wire.py:213` |
| `parse_charset(content_type) -> str` | `_wire.py:135` | `_wire.py:188` (comment "matches requests") | — |
| `parse_url(url) -> (scheme, host, port, path)` | `_wire.py:175` | — | — |

## Why now

The deferral text in Decision 0041 §210 / Decision 0045 §117 said extraction should wait for the next wire-format-adjacent change across these libraries.  Two such changes have shipped in the 2026-05 audit-integration sweep:

- `32079acd` — in-place memmove compaction across requests + http_server + websockets parsers (one fix landed three times).
- `63774d72` — `CaseInsensitiveDict` insertion-order tracking landed in requests + http_server commit `bcc3219e`, **missed websockets**, only caught when audit-integration re-walked the boundary.  That's the exact failure mode the trigger was meant to prevent.

The third HTTP/1.1 consumer (chumicro-http-server) has been present since Decision 0041; the websockets order-fix-divergence is direct evidence that "duplicated primitives cost less than one extra package" no longer holds.

## Scope

### Phase 1 — scaffold `chumicro-http`

- New library at `libraries/http/`.  Cross-runtime (CPython + MicroPython + CircuitPython).
- Public surface: `CRLF`, `CRLF_CRLF`, `CaseInsensitiveDict`, `parse_charset`, `parse_url`.
- Take requests's `CaseInsensitiveDict` as canonical (it has the `_order` insertion-order tracking + full method surface).  Websockets's slim variant is just a subset that doesn't call the extra methods; no behavior change for WS callers.
- Dependencies: none beyond stdlib.  Sits at the same dependency-stack tier as `chumicro-msgpack` / `chumicro-config`.

### Phase 2 — flip consumers

For each of `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`:

- Replace the inlined primitive copies with `from chumicro_http import …`.
- Drop the now-dead code from each `_wire.py`.
- Add `chumicro-http` to the library's `pyproject.toml` `dependencies`.
- Update test imports (any test that reaches into the library's own `_wire.py` for these primitives now imports from `chumicro_http`).
- Bump VERSION (minor — internal _wire restructure, but pyproject deps change is observable to bundle / mip consumers).

### Phase 3 — ADR cleanup

Three accepted ADRs carry stale "deferred until X" or "duplicated by design" text.  Edit in place:

- **Decision 0041 §118** (`chumicro-http-server`) — currently says "if a third HTTP-aware library appears … extracting becomes the right move."  Replace with the past tense: extraction shipped as Decision NNNN (the new ADR), pointer inline.
- **Decision 0041 §210** — currently says "until a fourth, the duplicated primitives cost less than one extra package."  Contradicts §118.  Rewrite to match the new state.
- **Decision 0041 §5** — designates dependency direction `chumicro-http-server → chumicro-requests` for `CaseInsensitiveDict` reuse but implementation inlined a copy instead.  Replace with the dependency direction onto `chumicro-http`.
- **Decision 0045 §117** (`chumicro-websockets`) — currently says "now triggerable … defer until either chumicro-http-server or chumicro-requests next needs a wire-format change."  Trigger fired (see Why now); rewrite to point at the new ADR.

### Phase 4 — new ADR

Write `plans/decisions/NNNN-chumicro-http.md` (next free number at execution time).  Captures: why the shared package now, what's in it, what's *not* (per-library wire framing stays per-library), the dependency direction (three consumers → `chumicro-http`), and the link back to the trigger condition in 0041 / 0045.

### Phase 5 — bundle config

- circup bundle JSON: add `chumicro-http`.
- mip bundle JSON: add `chumicro-http`.
- Run `python scripts/run.py validate-mip` against the staged bundle.

### Phase 6 — verify

- `python scripts/run.py preflight --coverage-threshold 94` green.
- Spot-check on the canonical four-board matrix (Pico W CP + MP, Lolin S2 CP + MP) for the websockets case specifically — its prior order-fix divergence is the bug class this workstream is preventing.

## Out of scope

- Migrating per-library wire framing (`RequestParser`, `ResponseParser`, `FrameParser`, MQTT's `PacketDecoder`).  Those are framers, not primitives, and each library's framer carries protocol-specific state machines.  This workstream extracts only the primitives that are byte-identical (or byte-identical-modulo-method-subset) across the three HTTP/1.1 consumers.
- MQTT's `_wire.py` primitives.  MQTT is its own protocol, doesn't share HTTP/1.1 framing.

## Estimated size

**Medium.**  Comparable to the `chumicro-config` extraction (Decision 0036) — small new library (~150 LOC), three consumer migrations, ADR cleanup, bundle config.  No new logic; pure relocation.  One commit per phase.

## Anti-patterns to avoid

- **Don't ship phases as one mega-commit.**  Each phase commits separately so any phase is rollback-able.
- **Don't fold framer cleanup into this workstream.**  The framers stay per-library; mixing framer refactors in muddies the diff and inflates rollback cost.
- **Don't bend `CaseInsensitiveDict` shape to satisfy a future protocol that hasn't arrived.**  The slim WS variant is just an unused-method subset; no need to design a layered class hierarchy for hypothetical fourth consumers.
