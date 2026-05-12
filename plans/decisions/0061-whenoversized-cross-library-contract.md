# Decision 0061: `WhenOversized` cross-library contract

Status: `accepted`
Date: `2026-05-12`
Related: Decision [0040](0040-chumicro-requests.md) (`chumicro-requests`), Decision [0045](0045-chumicro-websockets.md) (`chumicro-websockets`).

## Context

Three libraries — `chumicro-mqtt`, `chumicro-requests`, `chumicro-websockets` — each ship a `WhenOversized` policy class with the same three string values (`drop_silent` / `drop_with_event` / `disconnect`).  `mqtt` was first; `requests` and `websockets` copied the shape.  Decision 0040 line 138 explicitly named the extraction trigger — *"copy first, abstract on the third user"* — and `websockets` is the third user.

An integration audit found that the **values** converged but the **contracts** didn't:

- **`on_oversized` callback signature has three shapes.**  `mqtt` fires `(topic, reported_length)`; `requests` fires `(url, error)` (an `HttpOversizedError` object, not a length); `websockets` fires `(reported_length,)`.  No two are interchangeable.
- **`DROP_WITH_EVENT` means three different things.**  `mqtt` drops the payload, fires the event, and stays connected (PUBACK to the broker).  `requests` drops the body and completes the request as `oversized_dropped=True`.  `websockets` fires the event *and then closes the connection with `CLOSE_TOO_BIG`* — effectively "DISCONNECT-with-event", not "drop and continue".
- **Cap attribute names diverge.**  `mqtt` uses `max_message_size`; `requests` uses `max_body_bytes`; `websockets` uses `max_message_bytes`.  The `_bytes` suffix is the recent convention; `mqtt` is the outlier.

A shared symbol (e.g. a `chumicro-policies` micro-library or extending `chumicro-compat`) would force convergence at the type level but adds a dependency three libraries share for one three-element enum.  This ADR resolves the divergence *without* introducing a new package.

## Decision

The three libraries keep their own `WhenOversized` classes (values copy-pasted) but conform to a shared contract for **callback signature**, **policy semantics**, and **cap attribute naming**.

### 1. Values copy-pasted; no shared module

`chumicro_mqtt.WhenOversized`, `chumicro_requests.WhenOversized`, and `chumicro_websockets.WhenOversized` each define `DROP_SILENT = "drop_silent"`, `DROP_WITH_EVENT = "drop_with_event"`, `DISCONNECT = "disconnect"` as plain string constants on a class.  No shared parent class, no shared module, no cross-library import.

Reason: the string-equality dispatch already crosses libraries cleanly (any of the three enums' values compare equal across libraries).  A shared class would couple three libraries to a fourth for one three-element enum; the cost outweighs the win until a fourth user materializes with a meaningfully different policy set.

### 2. Cap attribute name: `max_<protocol-noun>_bytes`

The constructor kwarg and internal attribute use `max_<noun>_bytes` where `<noun>` names the protocol's unit of oversize:

| Library    | Attribute            |
|------------|----------------------|
| `mqtt`     | `max_message_bytes`  |
| `requests` | `max_body_bytes`     |
| `websockets` | `max_message_bytes` |

`chumicro-mqtt` renames `max_message_size` → `max_message_bytes` to match.  `_bytes` is the suffix because every protocol's oversize check is byte-counted; `_size` is ambiguous (bytes? items?).

### 3. `on_oversized` callback signature

The callback receives `reported_length: int` as its **first positional argument**, always.  Library-specific context follows as additional positional args.

| Library      | Signature                                          |
|--------------|----------------------------------------------------|
| `mqtt`       | `on_oversized(reported_length: int, topic: str)`   |
| `requests`   | `on_oversized(reported_length: int, url: str)`     |
| `websockets` | `on_oversized(reported_length: int)`               |

User code that only cares about size works across all three: `lambda reported_length, *_: record(reported_length)`.  User code that wants library-specific context unpacks the second positional.

`requests` passes `url` (not the `HttpOversizedError` object) — the error is internal to the failure path; the url is what the caller asked for.  `HttpOversizedError` gains a `reported_length: int` attribute populated at construction so the value is recoverable from the error in the `DISCONNECT` path.

### 4. Policy semantics

The three policies have the same observable effect across libraries:

| Policy             | Behavior                                                                                                |
|--------------------|---------------------------------------------------------------------------------------------------------|
| `DROP_SILENT`      | Drop the oversized payload; do not fire `on_oversized`; **stay connected / continue normally**.         |
| `DROP_WITH_EVENT`  | Drop the oversized payload; fire `on_oversized(reported_length, ...)`; **stay connected / continue normally**.  |
| `DISCONNECT`       | Terminate the in-flight unit (mqtt: raise `MQTTProtocolError`; requests: fail the request with `HttpOversizedError`; websockets: close with `CLOSE_TOO_BIG`).  Do not fire `on_oversized`. |

`websockets` was the divergent case before this decision — its `DROP_WITH_EVENT` branch sent `CLOSE_TOO_BIG` after firing the callback.  That close is removed; `DROP_WITH_EVENT` in `websockets` now drops the message and leaves the session in `OPEN` state for the next inbound message, matching `mqtt` and `requests`.

### 5. `DISCONNECT` name is honored across libraries despite shape mismatch

In `requests`, `DISCONNECT` doesn't terminate a persistent connection — each HTTP request owns its socket — it fails the in-flight request with `HttpOversizedError` and the next request opens a fresh socket.  The name is kept anyway because the user-facing intent (*"oversize is fatal to the in-flight unit"*) matches across libraries, and renaming it (`FAIL` / `RAISE`) would create three different policy names for one shared semantic.

If a future fourth user has a meaningfully different policy set (e.g. an HTTP server wanting `RESPOND_413` for oversize), revisit the shared-module question then.

## Rejected

**Shared `chumicro-policies` micro-library.**  Rejected for now: three libraries depending on a fourth for a three-element enum is more coupling than the win.  The audit found that user-visible divergence is in *contract* (callback shape, policy semantics, cap name), not in *values* — a shared symbol fixes the value duplication that wasn't causing pain.

**Extend `chumicro-compat` to host `WhenOversized`.**  Rejected: `chumicro-compat` exists for runtime-shim helpers (`functools`).  Adding a policy enum widens its remit and forces three libraries to depend on it.

**Shared `OversizedEvent` dataclass crossing the boundary.**  Rejected: adds a chumicro-defined type to the public callback API of three libraries.  Convergence on positional-arg order (`reported_length` first) gets the cross-library reuse win without the type-coupling cost.

**Rename `DISCONNECT` → `FAIL` in `requests`.**  Rejected: see §5 above.  Keep one name across three libraries for one shared user intent.

## Consequences

- `chumicro-mqtt` gets a breaking constructor change (`max_message_size` → `max_message_bytes`) and a breaking callback signature (`on_oversized(topic, length)` → `on_oversized(reported_length, topic)`).  Minor-version bump.
- `chumicro-requests` gets a breaking callback signature (`on_oversized(url, error)` → `on_oversized(reported_length, url)`).  `HttpOversizedError.reported_length` is a new public attribute.  Minor-version bump.
- `chumicro-websockets` gets a breaking `DROP_WITH_EVENT` semantic change (stays open instead of closing).  Callback signature unchanged but documented to receive `reported_length` as the first positional arg (was already the only arg).  Minor-version bump.
- Tests in all three libraries update to the new shapes.  `test_drop_with_event_fires_callback_and_closes` (websockets) becomes `test_drop_with_event_fires_callback_and_stays_open`.
- README + `docs/guide.md` for each library document the converged contract and cross-link this ADR.
- No new package; no new dependency; no new shared type.  Each library's `WhenOversized` class is local to its concerns and the contract is durable across libraries via this ADR + matching docstrings.
- Decision 0040 line 138 ("abstract on the third user") is resolved: convergence happened at the contract level, not the symbol level.  Both Decision 0040 and Decision 0045 update their `when_oversized` rows in place to cite this ADR.
