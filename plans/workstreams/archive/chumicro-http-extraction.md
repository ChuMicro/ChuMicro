# Workstream: Extract `chumicro-http` (shared HTTP/1.1 primitives)

Status: **archived — not planned (2026-05-12).**  Surfaced by `/audit-workspace` on 2026-05-11 (Claim E2) and re-flagged on 2026-05-12 by `/audit-integration`.  Re-evaluated 2026-05-12 against actual cost/benefit and the standing position reversed: the duplication is small (~150 LOC, ~5 % of the three `_wire.py` files), most boards deploy only one of the three consumers, the only primitive-level divergence to date (commit `63774d72`) was caught by `/audit-integration` ~13 days after it landed with no user-visible impact, and the RFCs the primitives encode (RFC 7230 §3.2, RFC 7231 §3.1.1.5) are stable.  Audit-integration is the working safety net; a new package adds version coupling + bundle surface + a new dep-graph node for benefit that already exists.

## Outcome — why not planned

- **Duplication is bounded.**  ~150 LOC of byte-equivalent code across three `_wire.py` files totalling ~3,110 LOC.  The other ~95 % (`RequestParser` / `ResponseParser` / `FrameParser` / encoders / state machines) is genuinely per-protocol and doesn't share.
- **Deployment overlap is rare.**  256 KB / 4 MB-class boards typically run one of {`chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`} at a time.  When two land together, the redundant ~80 LOC compiles to ~1.5 KB of `.mpy`.  Trivial.
- **Trigger evidence was a near-miss, not a defect.**  The `_order` insertion-order tracking divergence on websockets (`4115e2d4` slimmed the dict, `bcc3219e` added the fix to the other two, `63774d72` backfilled WS) was caught by the next `/audit-integration` pass, ~13 days after the divergence landed.  Nobody shipped against the bad state — the audit caught it.  That's the safety net working, not failing.
- **Primitive churn is low.**  In the library's lifetime (since `chumicro-requests` shipped) we've seen one primitive-level change that needed propagation across the three consumers.  RFCs are stable, the docstrings already say "matches requests's implementation," and audit-integration runs as a periodic pass against this exact boundary.
- **Extraction cost is real and standing.**  New package on PyPI + circup + mip; version-coupling (bump `chumicro-http` → re-validate three consumers); one more node future contributors have to learn about + reach for when touching HTTP primitives.  These are mild individually and compounding over time.
- **The `CaseInsensitiveDict` shape question doesn't bite in practice.**  Each library imports its own copy; `isinstance(headers, CaseInsensitiveDict)` resolves against the local class.  Shape only goes wrong if two consumers tried to pass headers *between each other* (e.g. a websocket handler receiving a `requests.Response` and inspecting headers) — not in any current code path.

## Follow-ups arising from this decision

- ADR language in [Decision 0041](../../decisions/0041-chumicro-http-server.md) §118 / §210 / §5 and [Decision 0045](../../decisions/0045-chumicro-websockets.md) §117 currently frames the deferral around a "third HTTP/1.1 consumer" trigger that has since fired without extraction.  Left as-is, the next `/audit-workspace` pass will re-propose this workstream.  Those paragraphs need rewriting so the standing position reads: "duplicated by design — `/audit-integration` keeps the three copies in sync; revisit if primitives start changing faster than the audit cadence catches, or if a fourth HTTP/1.1 consumer arrives."

## Purpose (original framing — preserved for context)

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
