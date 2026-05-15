# Decision 0067: MicroPython TLS default trust — chumicro_sockets ships a CA bundle

Status: `accepted`
Date: `2026-05-14`
Related: [Decision 0031](0031-chumicro-sockets.md) (chumicro-sockets charter — the substrate this decision modifies), [Decision 0042](0042-library-dependency-policy.md) (every consumer of TLS routes through chumicro_sockets), [Decision 0015](0015-board-architecture-support.md) (256 KB RAM / 4 MB flash minimum — informs the bundle's flash-cost ceiling).

## Context

The 2026-05-11 README TLS-claim audit found that `tls_client_socket(host, port)` on MicroPython silently accepts any certificate, including the expired one at `expired.badssl.com`.  The bug lives at `libraries/sockets/src/chumicro_sockets/_adapters/mp.py:161` — when `context=None`, the adapter calls bare `ssl.wrap_socket(sock, server_hostname=host)`, which on MicroPython leaves `verify_mode = CERT_NONE` (MP's own `ssl` default).  CircuitPython on the same boards correctly rejects expired certificates against the firmware-bundled mbedTLS CA store; CPython routes through `ssl.create_default_context()` and rejects against the host OS trust store.  Three docs claimed otherwise (the `tls_client_socket` docstring, the MP adapter docstring, the user-guide TLS section, and the README quick example); commit `fb37cf0e` rewrites those to describe what each runtime actually does today.

The blast radius is every TLS consumer in the workspace.  `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server` (client side), and `chumicro-websockets` all expose `from_config(...)` paths that bottom out at `tls_client_socket(host, port, context=ssl_context, radio=radio)` with `ssl_context=None` when the user didn't supply one.  Every default-config TLS connection on MP is silently insecure today.

The substrate already has the right primitive: `ssl_context_with_ca(ca_pem)` exists on all three adapters (`libraries/sockets/src/chumicro_sockets/_adapters/{cp,mp,cpython}.py`), the MP version sets `verify_mode = CERT_REQUIRED` and handles the rp2 PEM-vs-DER build quirk via `_pem_to_der`.  The missing piece is what `context=None` means on MP when the user doesn't pass a CA — MP ships no system trust store and no equivalent of CP's firmware-bundled `x509-crt-bundle`.

Three platform constraints inform the shape of any fix:

- **CircuitPython exposes no settable `verify_mode`**.  CP's `SSLContext` bindings (`.tools/circuitpython-10.2.0/shared-bindings/ssl/SSLContext.c`) surface only `check_hostname`, `load_cert_chain`, `load_verify_locations`, `set_default_verify_paths`, and `wrap_socket`.  The authmode is decided at handshake time based on whether CAs were loaded (`.tools/circuitpython-10.2.0/shared-module/ssl/SSLSocket.c:262-274`): firmware bundle present → `VERIFY_REQUIRED`, user CA loaded → `VERIFY_REQUIRED`, neither → `VERIFY_NONE`.  Insecure TLS on CP is reachable but requires the empty-string `load_verify_locations("")` trick (`cacert_bytes = 0` falls through the third branch), not a property flip.
- **CircuitPython's `SSLContext()` constructor is secure by default** — `common_hal_ssl_sslcontext_construct` calls `set_default_verify_paths()` which attaches `crt_bundle_attach`.  `ssl.create_default_context()` and `ssl.SSLContext()` produce equivalent contexts on CP.  CP's `context=None` path is already correct; the decision only changes MP.
- **MicroPython has a settable `verify_mode` and the standard `load_verify_locations(cadata=...)` shape**, with the rp2 caveat that `MBEDTLS_PEM_PARSE_C` is omitted from the port build to save flash — `ssl_context_with_ca` already converts PEM to DER for that reason.

## Decision

`chumicro_sockets.tls_client_socket(host, port)` becomes secure-by-default on every supported runtime.  The library ships a curated CA bundle for MicroPython's use, sourced from CircuitPython's `x509-crt-bundle`.  Insecure TLS requires an explicit, audit-greppable opt-in.

### API surface

| Call | Behavior |
|---|---|
| `tls_client_socket(host, port)` | Verifies against the runtime's default trust roots.  CP uses the firmware-bundled mbedTLS store; CPython uses `ssl.create_default_context()`; MP uses the bundled CA set this library ships. |
| `tls_client_socket(host, port, context=ssl_context_with_ca(pem))` | Verifies against the caller-supplied CA(s) only.  Unchanged from today. |
| `tls_client_socket(host, port, context=ssl_context_no_verify())` | Skips certificate verification entirely.  New helper — explicit, named, easy to grep for in code review. |

The `ssl_context_no_verify()` helper does the runtime-appropriate thing without leaking platform quirks to callers:

- **MicroPython** — returns `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` with default `verify_mode = CERT_NONE`.
- **CircuitPython** — returns `ssl.SSLContext()` followed by `load_verify_locations("")` (the empty-string idiom that resolves to `MBEDTLS_SSL_VERIFY_NONE` at handshake; the same technique already used in `tests/test_cp_adapter.py:663` for negative-path coverage).
- **CPython** — returns `ssl.create_default_context()` with `check_hostname = False` and `verify_mode = CERT_NONE`.

### CA bundle source and shape

The MP adapter's `context=None` path lazy-loads a module-level cached `ssl.SSLContext` built from `chumicro_sockets._ca_bundle.PEM_BYTES`, a curated payload sourced from CircuitPython's `x509-crt-bundle` (the same set CP attaches via `crt_bundle_attach` on every supported board).  Using the same source set means *"secure default on MP"* trusts the same roots as *"secure default on CP"* on the same board — no per-runtime divergence in which CAs are honored.

Generation is build-time, not runtime — a `scripts/regen_ca_bundle.py` task pulls the upstream bundle, filters it (drop test / legacy roots if any), and writes `libraries/sockets/src/chumicro_sockets/_ca_bundle.py` with `PEM_BYTES = b"""..."""`.  Bundle regeneration is a release-prep step; bundles do not auto-update at runtime.

Lazy load + module cache means the bundle payload is parsed into an `SSLContext` on first `tls_client_socket(context=None)` call and reused for every subsequent call in the same process.  Plain-TCP-only consumers never trigger the parse and never pay the RAM cost; the flash cost is paid by anyone with `chumicro_sockets` installed on MP whether they use TLS or not.

### Override knob

`chumicro_sockets.set_default_ca_bundle(pem_bytes)` lets a project replace the shipped trust set without waiting for a release.  Useful when the user's deployment uses a private internal CA in addition to public roots, or when a CA we don't ship rotates and the user needs to ship faster than our release cadence.  Calling `set_default_ca_bundle(None)` reverts to the library-shipped bundle.  The override targets only the MP-default context — CP keeps its firmware bundle, CPython keeps its OS trust store.

### Consumers unaffected

Every TLS consumer in the workspace already routes through `tls_client_socket(host, port, context=ssl_context, radio=radio)` with `ssl_context=None` when the user didn't supply one.  See `libraries/{requests,mqtt,http_server,websockets}/src/chumicro_*/sockets_factory.py`.  No consumer imports `ssl`, parses PEMs, or knows what a CA bundle is.  Shape Y inverts MP's `context=None` behavior in `chumicro_sockets` only; every downstream `HttpClient.from_config({}, radio=...)` / `MQTTClient.from_config({}, radio=...)` becomes secure on MP automatically, zero consumer changes.

### What does not change

- **CircuitPython path** — `cp.connect_tls(context=None)` continues to call `ssl.create_default_context()` → firmware `crt_bundle_attach` → `VERIFY_REQUIRED`.  No bundle payload ships for CP; the firmware already has one.
- **CPython path** — `cpython.connect_tls(context=None)` continues to call `ssl.create_default_context()`.  No change.
- **`ssl_context_with_ca` semantics** — caller-supplied CA contexts on all three adapters keep their current behavior, including the rp2 PEM-to-DER conversion in the MP adapter.
- **Server-side TLS** — `tls_listening_socket` and `ssl_context_with_cert_and_key{,_paths}` are unaffected; this decision concerns *client* trust roots only.

## Consequences

### Positive

- Every `tls_client_socket(host, port)` call in the workspace becomes secure-by-default on every supported runtime.  The `from_config({}, radio=...)` flows in chumicro-mqtt / chumicro-requests / chumicro-http-server / chumicro-websockets stop being silent footguns on MP.
- "Secure on MP" trusts the same roots as "secure on CP" on the same board.  No surprise where a connection succeeds on one runtime and fails on another because of trust-store divergence.
- Insecure TLS is named and greppable.  A code reviewer can `grep ssl_context_no_verify` to find every callsite that has opted out of verification; a `tls_client_socket(host, port)` with no context kwarg is unambiguously secure.
- Consumers don't pay the cognitive cost.  `chumicro-mqtt`'s `MQTTClient.from_config` and friends keep passing `ssl_context=None` through; the substrate does the right thing under them.

### Negative / tradeoffs

- **MP flash cost** — the bundled PEM payload adds bytes to every MP deployment that installs chumicro_sockets, whether the user uses TLS or not.  Estimated 15-25 KB PEM (~10-18 KB DER after the existing `_pem_to_der` conversion, parsed at first use), on top of the existing ~3 KB sockets package size.  Concrete measurement is part of acceptance verification.  At a 4 MB flash floor (Pi Pico W), this is < 1 % of total flash; on tighter boards the user can `set_default_ca_bundle(b"")` to recover the RAM cost (flash cost persists but the user trades for explicit-CA-only mode).
- **Bundle staleness** — Certificate Authorities rotate roots on multi-year cycles; a stale bundle means a TLS handshake against a server whose chain depends on a not-yet-bundled root will fail with `MBEDTLS_ERR_X509_*` until the user upgrades chumicro_sockets or calls `set_default_ca_bundle`.  Acceptable tradeoff vs. the alternative (silently accepting any cert).  Regeneration cadence: re-bake from upstream during each chumicro_sockets release pass.
- **Maintenance burden** — `scripts/regen_ca_bundle.py` is a new script that has to keep working against CP's `x509-crt-bundle` source layout.  Upstream source-layout changes will break us until we adapt.  Mitigation: keep the script small and fail loudly when the source path moves.

### Neutral

- The `ssl_context_no_verify()` helper exists in part because some legitimate use cases (dev against self-signed brokers, captive-portal probes, ESP32-S2 MP without `MBEDTLS_PEM_PARSE_C` against a self-signed dev cert) need an opt-out.  Naming it instead of leaving `context=None` as the opt-out makes the cost visible: every reviewer can see the call site.
- CP's empty-string `load_verify_locations("")` idiom is a real CP technique already used in negative-path tests (`tests/test_cp_adapter.py:663`).  We're not inventing a hack; we're reusing one.
- The decision does not address `chumicro-config` extending to support a per-project `tls.ca_pem` field.  That's a natural follow-up — once the override knob exists in the library, plumbing it from config takes ~5 LOC in each consumer's `from_config` — but it's out of scope here.
