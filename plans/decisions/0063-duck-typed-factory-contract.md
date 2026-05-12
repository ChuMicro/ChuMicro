# Decision 0063: Duck-typed factory contract for transport-injecting libraries

Status: `accepted`
Date: `2026-05-12`
Related: [Decision 0010](0010-library-testability.md) (constructor injection), [Decision 0042](0042-library-dependency-policy.md) (factory-helper sub-rule), [Decision 0062](0062-entrypoint-factory-skip.md) (deploy-time skip), [Decision 0021](0021-docstring-type-policy.md) (type-policy precedent).

## Context

Five libraries today take a transport-producing factory through their constructor: `chumicro_mqtt.MQTTClient(socket_factory=...)`, `chumicro_requests.HttpClient(connection_factory=...)`, `chumicro_websockets.WebSocketClient(connection_factory=...)`, `chumicro_ntp.NTPClient(socket=...)`, `chumicro_http_server.HttpServer(listener_factory=...)`.

The parameter is already duck-typed in code — annotated as `object | None` everywhere, matched against runtime attributes (`.recv_into`, `.send`, `.close`) without isinstance checks.  Docstrings, however, hand-type the contract as `"TCPClientSocket"` or `"TCPListeningSocket"` and example snippets reach for `chumicro_sockets.tcp_client_socket` as if it were the required producer.  The result misleads cold readers: they infer that bringing their own transport requires reverse-engineering `chumicro_sockets`'s API surface, when in fact the contract is much narrower.

Adafruit's `socket_source` parameter on `adafruit_httpserver.Server` is the closest prior art for memory-constrained boards.  It accepts `socketpool.SocketPool` on CircuitPython, the stdlib `socket` module on CPython, or any object matching the same shape — no PyPI dep declared, no `typing.Protocol`, no inheritance contract.  The library never imports a transport-specific package; the user supplies whatever quacks correctly.

Decision 0062 makes the skip mechanism real (users can omit `chumicro_sockets` from a deploy via `__chumicro_skip_factories__`).  But the inverse — what does the user pass *instead* — is undocumented today.  This decision closes that gap.

## Decision

### The factory parameter is the contract; the producer is not

For each transport-injecting library, the constructor parameter accepts any callable whose return value matches the documented shape.  `chumicro_sockets` is **one** valid producer.  Other valid producers include stdlib `socket`, `socketpool.SocketPool`, user-written wrappers around an upstream library, or hand-rolled fakes.

Docstrings document the shape as a structural contract — what methods the returned object must expose, what each call's contract is — not as a type name imported from `chumicro_sockets`.

```python
class MQTTClient:
    def __init__(
        self,
        socket: object | None = None,
        *,
        socket_factory: object | None = None,
        ...,
    ) -> None:
        """
        Args:
            socket: An already-connected, non-blocking TCP-shaped object.
                Must expose:
                    - .recv_into(buffer: memoryview, nbytes: int) -> int
                      (raises OSError(EAGAIN | EWOULDBLOCK) on no-data;
                       returns 0 on peer-close; otherwise bytes written)
                    - .send(payload: bytes) -> int
                      (raises OSError(EAGAIN | EWOULDBLOCK) when buffer full;
                       otherwise bytes sent, may be partial)
                    - .close() -> None
                    - .setblocking(flag: bool) -> None  (best-effort; absence tolerated)
                ``chumicro_sockets.tcp_client_socket(...)`` is one valid
                producer.  Stdlib ``socket.socket(...)`` (after
                ``setblocking(False)``) is another.  Anything matching
                the shape works.
            socket_factory: Zero-arg callable returning an object of
                the same shape.  Invoked once at construction time and
                again on self-heal after a connection drop.
        """
```

### No `typing.Protocol`, no abstract base class

Both add either runtime overhead (`Protocol` requires `typing` on MicroPython, which doesn't exist there — `from __future__ import annotations` is also unavailable per Decision 0021) or inheritance scaffolding (ABC adds vtable cost on every concrete class).  The contract is the docstring.  Runtime errors surface at first call, which is acceptable for a contract this narrow.

### Naming: the chumicro helper stays named

`chumicro_<lib>.sockets_factory.chumicro_sockets_factory` keeps its name — it's still the convenience helper, and users opting in want a discoverable, namespace-friendly identifier.  The docstring positions it as one producer among others, not the canonical one.

### What this changes about library examples + READMEs

Examples and quick-start snippets continue to use `chumicro_sockets` as the example transport — it's the cheapest path to working code, and most users will land there.  But each library's `docs/guide.md` gains a "Bring your own transport" section naming the duck-typed contract and showing a non-chumicro example (typically stdlib `socket` for tests / CPython demos, or a sketch of a user-wrapper around an upstream library).

### What this does not require

- **No code changes to library implementations.** The duck-typing already exists; this ADR documents it.
- **No removal of `chumicro_sockets` from `[project].dependencies`.** Decision 0042's hard-dep rule is independent; the dep stays for the host-venv ergonomic, the on-device opt-out happens through Decision 0062.

## Consequences

### Positive

- **Custom-transport users get a real path forward.** The "I don't want chumicro_sockets on my device" audience can pair Decision 0062's skip mechanism with a documented contract for what to supply instead.  Today they have to read source.
- **Adafruit / stdlib interop becomes a documented feature.** Users coming from `adafruit_httpserver` find a familiar pattern (`socket_source`-style duck typing).  Users coming from CPython tests can pass stdlib `socket` without indirection.
- **Reduces conceptual surface.** The contract is "object with three methods" instead of "TCPClientSocket from chumicro_sockets."  Cold-reader load drops.
- **Test ergonomics.** Hand-rolled fakes already work (the testing submodules in chumicro_mqtt / requests / etc. demonstrate this); the contract documentation makes that explicit rather than implicit.

### Negative

- **Runtime-error feedback at first call.** A factory returning a mis-shaped object only fails when the library invokes the missing method.  Acceptable for a narrow contract; would not be acceptable for a wide one (the OG argument for `Protocol`).  Mitigated by every library's testing submodule providing fakes that exercise the call shape during construction-time setup.
- **Docstring contracts can drift from code.** If `MQTTClient` grows to require a new method on its socket, the docstring must be updated in lockstep.  Same risk as any docstring contract; same mitigation (PR review + linter checks for missing docstring updates when method signatures change).

### Alternatives considered

- **`typing.Protocol` class** — `class TCPClientSocketProtocol(Protocol): ...`.  Rejected: `typing` is unavailable on MicroPython, `from __future__ import annotations` is also unavailable, and the runtime overhead of `runtime_checkable` Protocol classes is non-trivial on a 256 KB board.  Decision 0021 already rules out `typing` imports in library code.
- **Abstract base class** (`class TCPClientSocket(abc.ABC): ...`).  Rejected: forces inheritance, adds vtable weight to every concrete socket class, makes stdlib `socket` and `socketpool` ineligible without a wrapper.  Defeats the duck-typing purpose.
- **Status quo (docstrings type as `TCPClientSocket`).**  Rejected: misleads cold readers into thinking `chumicro_sockets` is required when it isn't.  Direct cause of Tier 2's "DI isn't real" concern, which was the originating frame for this ADR thread.
- **Centralized contract doc** (one page documenting all five factory contracts).  Considered.  Rejected: makes the contract physically separated from the library that owns it, increases drift risk.  Each library's `docs/guide.md` is the right home — close to the API it documents.

The implementation punch-list (per-library docstring rewrites + new `## Bring your own transport` section in each `docs/guide.md`) lives in `plans/next-up.md`, not here.
