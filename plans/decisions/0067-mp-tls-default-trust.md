# Decision 0067: MicroPython TLS default trust — chumicro_sockets ships a CA bundle

Status: `accepted`
Date: `2026-05-14`
Summary: `chumicro-sockets` ships a curated DER CA bundle for MicroPython; `tls_client_socket(host, port)` is secure-by-default on every runtime; `ssl_context_no_verify()` is the explicit opt-out.
Related: [Decision 0031](0031-chumicro-sockets.md) (chumicro-sockets charter — the substrate this decision modifies), [Decision 0042](0042-library-dependency-policy.md) (every consumer of TLS routes through chumicro_sockets), [Decision 0015](0015-board-architecture-support.md) (256 KB RAM / 2 MB physical / ~800 KB usable flash minimum — informs the bundle's flash-cost ceiling).

## Context

The 2026-05-11 README TLS-claim audit found that `tls_client_socket(host, port)` on MicroPython silently accepts any certificate, including the expired one at `expired.badssl.com`.  The bug lives at `libraries/sockets/src/chumicro_sockets/_adapters/mp.py:161` — when `context=None`, the adapter calls bare `ssl.wrap_socket(sock, server_hostname=host)`, which on MicroPython leaves `verify_mode = CERT_NONE` (MP's own `ssl` default).  CircuitPython on the same boards correctly rejects expired certificates against the firmware-bundled mbedTLS CA store; CPython routes through `ssl.create_default_context()` and rejects against the host OS trust store.  Three docs claimed otherwise (the `tls_client_socket` docstring, the MP adapter docstring, the user-guide TLS section, and the README quick example); commit `fb37cf0e` rewrites those to describe what each runtime actually does today.

The blast radius is every TLS consumer in the workspace.  `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server` (client side), and `chumicro-websockets` all expose `from_config(...)` paths that bottom out at `tls_client_socket(host, port, context=ssl_context, radio=radio)` with `ssl_context=None` when the user didn't supply one.  Every default-config TLS connection on MP is silently insecure today.

The substrate already has the right primitive: `ssl_context_with_ca(ca_pem)` exists on all three adapters (`libraries/sockets/src/chumicro_sockets/_adapters/{cp,mp,cpython}.py`), the MP version sets `verify_mode = CERT_REQUIRED` and handles the rp2 PEM-vs-DER build quirk via `_pem_to_der`.  The missing piece is what `context=None` means on MP when the user doesn't pass a CA — MP ships no system trust store and no equivalent of CP's firmware-bundled `x509-crt-bundle`.

Three platform constraints inform the shape of any fix:

- **CircuitPython exposes no settable `verify_mode`**.  CP's `SSLContext` bindings (`.tools/circuitpython-10.2.0/shared-bindings/ssl/SSLContext.c`) surface only `check_hostname`, `load_cert_chain`, `load_verify_locations`, `set_default_verify_paths`, and `wrap_socket`.  The authmode is decided at handshake time based on whether CAs were loaded (`.tools/circuitpython-10.2.0/shared-module/ssl/SSLSocket.c:262-274`): firmware bundle present → `VERIFY_REQUIRED`, user CA loaded → `VERIFY_REQUIRED`, neither → `VERIFY_NONE`.  Insecure TLS on CP is reachable but requires the empty-string `load_verify_locations("")` trick (`cacert_bytes = 0` falls through the third branch), not a property flip.
- **CircuitPython's `SSLContext()` constructor is secure by default** — `common_hal_ssl_sslcontext_construct` calls `set_default_verify_paths()` which attaches `crt_bundle_attach`.  `ssl.create_default_context()` and `ssl.SSLContext()` produce equivalent contexts on CP.  CP's `context=None` path is already correct; the decision only changes MP.
- **MicroPython has a settable `verify_mode` and the standard `load_verify_locations(cadata=...)` shape**, with the rp2 caveat that `MBEDTLS_PEM_PARSE_C` is omitted from the port build to save flash — `ssl_context_with_ca` already converts PEM to DER for that reason.

## Decision

`chumicro_sockets.tls_client_socket(host, port)` becomes secure-by-default on every supported runtime.  The library ships a curated CA bundle for MicroPython's use — a hand-picked subset verified to be a strict subset of CircuitPython's firmware `x509-crt-bundle`, so a chain that validates on MP also validates against the CP firmware bundle on the same board.  Insecure TLS requires an explicit, audit-greppable opt-in.

The curated subset is **permanent architecture, not a stopgap**.  MicroPython's `ssl` module exposes only `load_verify_locations(cadata=...)` → `mbedtls_x509_crt_parse(make_copy=1)`, which copies and parses *every* root into heap for the SSLContext's lifetime.  It exposes no `mbedtls_ssl_conf_verify` hook to Python, so the flash-resident binary-search-one-key-per-handshake scheme CircuitPython's firmware `crt_bundle.c` uses is unreachable from pure Python.  Shipping all ~150 Mozilla roots would cost ~75 KB+ resident heap on a 256 KB board — not viable.  A curated subset, sized against measured per-root RAM, is the only pure-Python option; "ship more roots later" is bounded by that ceiling, not a matter of effort.

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

### CA bundle shape and loader

The bundle ships as a **DER data file** — `libraries/sockets/src/chumicro_sockets/_ca_bundle.der`, 17 roots, ~16 KB concatenated DER (ISRG X1/X2, DigiCert CA/G2/G3, Amazon Root CA 1, GTS R1/R4, GlobalSign, AAA Certificate Services + USERTrust RSA/ECC for Sectigo, Go Daddy / Starfield G2, Entrust G2, Microsoft RSA/ECC 2017).  `_ca_bundle.py` is a ~30-line loader shim co-located with the file: `read_der()` resolves the sibling via its own `__file__` (fallback `/lib/chumicro_sockets/_ca_bundle.der`).

DER, not a `PEM_BYTES` / `DER_BYTES` module constant, and a *file*, not a constant, are both deliberate:

- **DER over PEM** — concatenated DER is what `mbedtls_x509_crt_parse` walks natively and the lowest common denominator across MP ports (rp2's mbedTLS lacks `MBEDTLS_PEM_PARSE_C`).  It also deletes the runtime `_pem_to_der` base64 decode from the default path and is ~30 % smaller than the equivalent PEM.
- **File over constant** — a module constant is allocated at import and pinned in `sys.modules` for the process lifetime; evicting it after the context is built strands a multi-KB hole among the long-lived `SSLContext` / mbedTLS-chain objects (MicroPython's GC is non-compacting).  `read_der()`'s buffer is a function-scoped temporary fed straight into `ssl_context_with_ca` with no retained reference, so the GC reclaims it the moment `load_verify_locations` has copied it into mbedTLS — *before* the socket and handshake working set allocate, where the freed span is immediately reused.  Tight lifetime → minimal fragmentation; this is the property a constant cannot provide.

Because a non-`.py` data file cannot ride RAM-mode CircuitPython (raw-REPL `exec()`, no device filesystem — the file would be silently dropped), `Deployer._effective_device_for_source` switches the *whole* deploy to flash mode when any non-`.py` file is in the staged set (all-or-nothing; the explicit `force_deploy_mode='ram'` escape hatch still wins).  This makes the sibling-`__file__` path resolution reliable.

The MP adapter's `context=None` path builds the `SSLContext` from `read_der()` on first call and caches it module-level for the process; plain-TCP-only consumers never trigger the read+parse.  The ~16 KB DER flash cost is paid by every MP install of `chumicro_sockets` regardless of TLS use (no `__chumicro_runtimes__` marker mechanism for data files — it also ships, unused, to CP, ~16 KB; negligible against ~800 KB usable flash).

Generation today is manual: extract the chosen roots from a current trust store, concatenate DER, write `_ca_bundle.der`, and verify the set is a strict subset of ESP-IDF's `cacrt_all.pem` (the source of CP's firmware bundle).  Re-cut during a release pass.  No automated `regen` script exists yet; if root rotation makes this churn, a small script is the obvious follow-up.

### Override knob

`chumicro_sockets.set_default_ca_bundle(pem_bytes)` lets a project replace the shipped trust set without waiting for a release.  Useful when the user's deployment uses a private internal CA in addition to public roots, or when a CA we don't ship rotates and the user needs to ship faster than our release cadence.  Calling `set_default_ca_bundle(None)` reverts to the library-shipped bundle.  The override targets only the MP-default context — CP keeps its firmware bundle, CPython keeps its OS trust store.

### Consumers unaffected

Every TLS consumer in the workspace already routes through `tls_client_socket(host, port, context=ssl_context, radio=radio)` with `ssl_context=None` when the user didn't supply one.  See `libraries/{requests,mqtt,http_server,websockets}/src/chumicro_*/sockets_factory.py`.  No consumer imports `ssl`, parses PEMs, or knows what a CA bundle is.  Shape Y inverts MP's `context=None` behavior in `chumicro_sockets` only; every downstream `HttpClient.from_config({}, radio=...)` / `MQTTClient.from_config({}, radio=...)` becomes secure on MP automatically, zero consumer changes.

### What does not change

- **CircuitPython path** — `cp.connect_tls(context=None)` continues to call `ssl.create_default_context()` → firmware `crt_bundle_attach` → `VERIFY_REQUIRED`.  No bundle payload ships for CP; the firmware already has one.
- **CPython path** — `cpython.connect_tls(context=None)` continues to call `ssl.create_default_context()`.  No change.
- **Server-side TLS** — `tls_listening_socket` and `ssl_context_with_cert_and_key{,_paths}` are unaffected; this decision concerns *client* trust roots only.

`ssl_context_with_ca` *did* change as part of this work (it is no longer "unchanged"): it now accepts **PEM or DER** and detects by first byte, because user-supplied-CA acceptance is not uniform across the runtime bindings.  MicroPython detects and converts PEM→DER **unconditionally** (the old `sys.platform` rp2-vs-esp branch is gone — the only expensive input, the shipped bundle, is pre-converted DER that never hits this path, so a per-board branch guarded a non-cost and added a fragile build-flag dependency); DER passes through.  CircuitPython is **PEM-only** — its `load_verify_locations` binding is `mp_obj_str_get_str` + a `strlen`-based HAL (`shared-module/ssl/SSLContext.c`), structurally unable to carry binary DER (embedded `0x00`) — a non-PEM input now raises a clear `ValueError` up front instead of a cryptic `UnicodeDecodeError`.  CPython accepts either.  `_pem_to_der` was rewritten to stream (C-level `bytes.find` + zero-copy `memoryview` slices; `a2b_base64` skips embedded whitespace, verified in MP `modbinascii.c`), eliminating the old per-line `split` + `join` (~45 KB transient + ~250-object GC storm).  Detection is strict on the RFC 7468 `-----BEGIN CERTIFICATE-----` boundary; alternate armors (`X509 CERTIFICATE`, `TRUSTED CERTIFICATE`, PKCS7, bare base64) raise rather than risk silent empty-trust from loose detection feeding the CERTIFICATE-only extractor.

## Consequences

### Positive

- Every `tls_client_socket(host, port)` call in the workspace becomes secure-by-default on every supported runtime.  The `from_config({}, radio=...)` flows in chumicro-mqtt / chumicro-requests / chumicro-http-server / chumicro-websockets stop being silent footguns on MP.
- "Secure on MP" trusts the same roots as "secure on CP" on the same board.  No surprise where a connection succeeds on one runtime and fails on another because of trust-store divergence.
- Insecure TLS is named and greppable.  A code reviewer can `grep ssl_context_no_verify` to find every callsite that has opted out of verification; a `tls_client_socket(host, port)` with no context kwarg is unambiguously secure.
- Consumers don't pay the cognitive cost.  `chumicro-mqtt`'s `MQTTClient.from_config` and friends keep passing `ssl_context=None` through; the substrate does the right thing under them.

### Negative / tradeoffs

- **MP flash + RAM cost** — measured, not estimated (`functional_tests/test_ca_bundle_ram_cost.py`, Pi Pico W MP): ~16 KB DER flash; ~500 B parsed-chain resident heap per root (17 roots ≈ ~8-9 KB) against a ~187 KB free-heap baseline; the chain frees cleanly on context release (retained < 2 KB — no pinned buffer, no leak).  RAM is therefore *not* the binding constraint on subset size — flash (~900 B/root) and bundle maintenance are.  The flash cost is paid by every MP install regardless of TLS use, and the file also ships unused to CP (~16 KB; negligible against ~800 KB usable flash).
- **Bundle staleness** — Certificate Authorities rotate roots on multi-year cycles; a stale bundle means a TLS handshake against a server whose chain depends on a not-yet-bundled root fails with `MBEDTLS_ERR_X509_*` until the user upgrades `chumicro_sockets` or calls `set_default_ca_bundle`.  Acceptable vs. the alternative (silently accepting any cert).  Cadence: re-cut the bundle during each release pass.
- **Maintenance burden** — the bundle is curated and regenerated manually (extract the chosen roots from a trust store, concatenate DER, verify strict-subset of ESP-IDF `cacrt_all.pem`).  No automated script yet; the manual step is small but un-checked — a root that rotates out silently keeps working until removed, a needed new root is invisible until a user hits a failure.  A `regen` + subset-diff script is the obvious follow-up if this churns.

### Neutral

- The `ssl_context_no_verify()` helper exists in part because some legitimate use cases (dev against self-signed brokers, captive-portal probes, ESP32-S2 MP without `MBEDTLS_PEM_PARSE_C` against a self-signed dev cert) need an opt-out.  Naming it instead of leaving `context=None` as the opt-out makes the cost visible: every reviewer can see the call site.
- CP's empty-string `load_verify_locations("")` idiom is a real CP technique already used in negative-path tests (`tests/test_cp_adapter.py:663`).  We're not inventing a hack; we're reusing one.
- **Validation now requires a correct device clock.**  Enabling default verification means a board that boots at epoch/2021 (most MP ports) rejects a *valid* cert as "validity starts in the future".  Expired-cert *rejection* is immune (a reject is a reject regardless of skew — which is why the first 4-board acceptance run passed before this was noticed).  Real deployments must NTP-sync before TLS; the functional tests seed the RTC from the host clock (`sockets.now_utc_tuple`, mirroring requests' `_seed_rtc`).  This is inherent to certificate validation, not specific to this design, but it is a new operational requirement that `context=None`'s prior insecurity masked.
- The decision does not address `chumicro-config` extending to support a per-project `tls.ca_pem` field.  That's a natural follow-up — once the override knob exists in the library, plumbing it from config takes ~5 LOC in each consumer's `from_config` — but it's out of scope here.
