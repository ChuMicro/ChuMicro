# Learnings

Non-obvious facts about the world this project lives in — discovered the hard way and worth re-reading before the same surface is touched again.

This file is the **compression tier** for "we tripped on X, here's what we know about X." Distinct from sibling files:

- **`decisions/`** = *why* we chose X over Y. Tradeoffs we made.
- **`patterns.md`** = *how* to implement X correctly. Code shape.
- **`history.md` §Rejected approaches** = approaches we *tried as a project decision* and rejected. Path-not-taken.
- **`learnings.md` (this file)** = facts about hardware, tools, runtimes, and OS behavior. Not policies — *physics*.

If a learning grows enough scope that the right response is "we should change how we build", promote it to a Decision and link back here. If it grows enough code surface to reuse, promote to a Pattern. Otherwise it lives here, terse.

Each entry: one heading + 2–6 lines + a commit reference. If you can't say it in 6 lines, you're probably writing a Pattern or a Decision.

---

## macOS hardware deploy

### macOS FSKit can wedge `diskarbitrationd` on FAT12 errors

Recent macOS replaced the in-kernel `msdosfs` driver with a user-space FSKit extension (`com.apple.fskit.msdos.appex`). When it errors mid-probe on a small FAT12 CIRCUITPY volume, `diskarbitrationd` enters an uninterruptible kernel wait (`ps` state contains `U`) and every subsequent DiskArbitration call queues behind it. Unplug/replug does nothing.

Recovery (surface to user, never auto-run): `sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd && launchctl kickstart -k gui/$(id -u)/com.apple.DiskArbitrationAgent`. The per-user `DiskArbitrationAgent` needs `kickstart -k`, not just `killall`, because its launchd plist has `KeepAlive=false` — a bare kill leaves it dead and CIRCUITPY drives mount but never appear in Finder Locations.

Detector lives at `workbench/deploy/src/chumicro_deploy/macos_fskit.py`. Fails open on any subprocess error — never block a legitimate retry. See `DeployFailureKind.MACOS_FSKIT_WEDGED`. Commit `6fdc132`.

### Finder sidebar regression after FSKit recovery is a separate Apple bug

After `MACOS_FSKIT_WEDGED` recovery, drives mount cleanly and tools see them, but Finder's Locations sidebar may still hide them. AppleScript, CLI tools, Finder Computer view, and the deploy tool all see the volumes — only the sidebar classifier filters them out. No userspace command fixes it. Tell the user, don't chase it. Workarounds: Shift+Cmd+C → drag to Favorites. Commit `6fdc132`.

### Lolin S2 Mini gets stranded after esptool default `--after hard_reset`

Single-invocation `esptool.py erase-flash write-flash …` left the Lolin S2 momentarily un-enumerable on macOS. Fix: run erase and write as two invocations, `--after no_reset` on erase, one-second settle, then write. esptool v5 also refuses chained `erase-flash` + `write-flash` in one call regardless. See `chumicro_deploy/firmware.py`. Commits `5c5ef53`, in slice 1e.2 round 2.

---

## CircuitPython runtime quirks

### Raw paste mode (Ctrl-E) is unresponsive on ESP32-S2 CP

Validated on Lolin S2 Mini during Decision 0027 PoC. Use Ctrl-A raw REPL mode instead. The `chumicro-deploy` `CircuitpythonTransport` and `chumicro-repl` `ReplSession` both standardize on Ctrl-A. Earlier planning docs referenced "raw paste mode" — those are stale; the implemented protocol is Ctrl-A only.

### `types.ModuleType` and `hashlib.sha256` are absent on ESP32-S2 CP

Means: no module-injection helpers that rely on `types.ModuleType()`, no SHA-256 staging hashes in CP RAM-mode bootstraps. Class-as-module injection (assigning a class instance into `sys.modules`) is the workaround for the missing `ModuleType`. See the bootstrap builders in `workbench/deploy/src/chumicro_deploy/`.

### CircuitPython 10.x's `bytearray` rejects `del buffer[:n]`

`del bytearray_instance[:n]` raises `TypeError("'bytearray' object doesn't support item deletion")` on CP 10.2.0-rc.0 (Pi Pico W).  CPython and MicroPython both accept it.  Cross-runtime safe alternative: `self._buffer = bytearray(self._buffer[n:])` — one extra allocation but trivially cheap on the small buffers parsers usually carry (status line ~50 B, header lines ~few hundred B).  Surfaced live during chumicro-requests slice 3c HTTPS verification.  Commits in slice 3c.

### MicroPython's `bytearray` lacks `.clear()`

`bytearray.clear()` raises `AttributeError("'bytearray' object has no attribute 'clear'")` on MP 1.28.0 (Pi Pico W rp2).  Both CPython and CircuitPython 10.x accept it.  Cross-runtime safe alternative: `self._buffer = bytearray()` — same one-allocation cost as the `del`-incompatibility workaround.  Surfaced live during chumicro-requests slice 3c HTTPS verification on the same code path that exposed the CP `del`-incompatibility.  Commits in slice 3c.

### CIRCUITPY drive must be re-probed after eject; EACCES is not a permission error

When `/Volumes/CIRCUITPY` lingers as a placeholder after Finder eject (or during an FSKit wedge), writing to it raises `OSError: [Errno 13] Permission denied`. The classifier must check drive-not-found patterns *before* port-unavailable patterns — the nested `permission denied` substring will otherwise misroute to `PORT_UNAVAILABLE` and skip the FSKit wedge detector. Transport-level guard: write a `.chu-probe` marker file before any rsync; catch `OSError` and re-raise with the drive-not-found message. Commit `38fb039`.

### CP flash deploy needs a settle delay after the board sees a new entrypoint

Without a post-visible settle, output captured immediately after `autoreload` re-engagement is one cycle behind reality. See `_BOARD_FILE_VISIBLE_POST_SETTLE` in `chumicro_deploy/transports/`. Hardware-tuned, do not remove. Commits `a561c02`, `3f11d09`.

---

## MicroPython runtime quirks

### MP ESP32 firmware lives at flash offset `0x1000`, not `0x0`

Per-runtime esptool offsets matter — MicroPython ESP32 binary at `0x0` will boot to a brick. Fixed in slice 1e.2; see `chumicro_deploy/firmware.py` `_RUNTIME_FLASH_OFFSETS`. Commit `c4e6ac1`.

### `mpremote` "failed to access" / "may be in use" is a port-unavailable signal

Classifier must route these strings to `PORT_UNAVAILABLE`, not `BOOTSTRAP_EXEC_FAILED`. Otherwise an unplugged board produces a "fix your source" message. Patterns added to `_PORT_UNAVAILABLE_PATTERNS`. Commit `38fb039`.

### Every `import` on MicroPython mount-mode is an mpremote RPC round-trip

`mpremote mount` exposes the host file system to the device via a `RemoteFS` hook. Every `import` triggers a serial-intercept callback that fetches the source file over USB CDC. A single lazy import inside a hot path (e.g. `Runner.__init__` deferring `chumicro_timing.ticks`) pulled three files over the wire on first call and added ~1 second of inflation on the Lolin S2 mini.

Implication for tests / measurement: when profiling MicroPython mount-mode, the first run of any test that exercises new imports is dominated by RPC round-trips, not by the test body. The CircuitPython numbers don't show this because CP runs the source from RAM after staging.

Fix knobs that *don't* work: eager-importing at package top level was tried (commit `9eb5980`) and reverted (commit `8b44325`) — see Rejected approaches §18 in `history.md`. The only durable fix is to amortize: batch-execute test functions, hold one `SerialTransport` per session (see `patterns.md` §mpremote internals §4), and stage all files in one rsync pass. Commit `9eb5980` (root cause analysis), `8b44325` (revert).

### MicroPython RAM-mode functional tests run noticeably slower than CP RAM-mode

Observed during 2026-04-19 live PyCharm testing. Suspect: per-file `mpremote mount` cost + cold-start interpreter overhead. Profile against the batched-execute path before optimizing — there's an open investigation in `next-up.md`. Not yet root-caused.

### A naive `recv_into` loop can starve cooperative tasks when the kernel TCP buffer is fat

`while True: recv_into(...); break-on-EAGAIN` is the obvious shape for a tick-based protocol parser, but on a Pi Pico W RP2 (lwIP TCP) the kernel can hold ~16-32 KB of inbound bytes, and our `rx_buffer_size`-bounded reads (256 B / call) mean a single `handle()` tick will iterate 60-128 times before EAGAIN drains the buffer.  At 50-200 µs per syscall + memmove on rp2, that's 6-25 ms inside a *single tick* — enough to visibly stutter a 10 ms LED blink rhythm or break a sub-second control loop.

The old basefs MQTT impl (`/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`) avoided this implicitly: `_read_socket` does **one** `recv_into` per loop call (no inner loop), so each loop call is bounded by `RX_BUFFER_SIZE` regardless of how much data is in the kernel buffer.  A 100 KB blob takes 400+ loop calls to ingest, but every call is short.

`chumicro-mqtt` 0.1.4 adopts a hybrid: a `recv_budget_per_tick` knob (default 1024 B) caps the per-tick byte budget while still letting a tick do multiple recv calls when bytes are available.  Default 1024 = 4× the steady RX buffer (256 B) = drains a typical PUBLISH in one tick AND keeps tick latency well under 10 ms even on rp2.  Configurable upward for things that want fast big-blob ingestion at the cost of LED smoothness.  The lesson is general: any tick-shaped reader on a fat kernel buffer needs an explicit per-tick byte budget OR an explicit per-tick iteration count — implicit "drain until EAGAIN" is a foot-gun.

### CircuitPython's `ssl` module deliberately omits server-side TLS

Verified live 2026-04-26 on Pi Pico W CircuitPython 10.2.0-rc.0 during chumicro-http-server slice 7t investigation:

* `ssl.PROTOCOL_TLS_SERVER` doesn't exist; `dir(ssl)` exposes no `PROTOCOL_*` constants whatsoever.
* `ssl.SSLContext()` is hard-wired to the client side; there's no parameter to flip it server-side.
* `AttributeError("'module' object has no attribute 'PROTOCOL_TLS_SERVER'")` when you try.

This is a CircuitPython platform decision, not a heap constraint — the device had ~157 KB free heap at the time of the failure.  Adafruit's `httpserver` runs into the same wall and quietly degrades on CP.  The recommended workaround is to terminate TLS in front of the board with a proxy (Caddy / nginx / Cloudflare Tunnel) and let the board speak plain HTTP on the LAN behind it.  Lifted to `chumicro_sockets.ssl_context_with_cert_and_key`'s CP adapter, which now raises `UnsupportedSSLConfigError` with a clear explanation rather than the bare `AttributeError`.

### MicroPython TLS server *does* fit on Pi Pico W (Adafruit's "limited" framing was too pessimistic)

Slice 7t live verification on Pi Pico W MicroPython 1.28.0 (rp2 port) — the assumption that "TLS server only fits on ESP32-S3 class boards" (per the `adafruit_httpserver` README) was wrong.  The handshake fits fine on a Pi Pico W with the right key shape:

* RSA-2048 cert + key in DER encoding (PEM is rejected by rp2's mbedTLS for keys, same `MBEDTLS_PEM_PARSE_C`-disabled story as the CA-load path).
* SSLContext build cost: ~8 KB heap.
* Per-connection handshake cost: ~25 KB heap.
* Free heap remaining post-handshake: ~130 KB.
* End-to-end: HTTPS GET round-trip from a host CPython client to the device's `chumicro-http-server` succeeded.

ECC keys (SECP256R1) failed at context build with `ValueError("invalid key")` — RSA was the only key type that worked end-to-end.  The MP build's mbedTLS server-side code path may not include ECC private-key parsing, or the PKCS#8 wrapping isn't recognized.  Documented in `chumicro_sockets._adapters.mp.ssl_context_with_cert_and_key`.

Honesty about LED-blink: TLS handshake on the server side is synchronous inside `wrap_socket(..., server_side=True)` — same blocking-during-handshake tradeoff as the client side has during `tls_client_socket()`.  The runner pattern still applies for the HTTP exchange after the handshake; just budget for ~100-500 ms of listener stall during accept.

### MP TLS `SSLSocket.recv()` returns `None` for WANT_READ (not raises EAGAIN like plain TCP)

MP plain TCP non-blocking `recv` raises `OSError(11)` (EAGAIN) when no data is available.  MP TLS `SSLSocket.recv` instead returns the literal `None` — mbedTLS's `MBEDTLS_ERR_SSL_WANT_READ` / `WANT_WRITE` maps to `MP_EWOULDBLOCK` internally but the Python-level surface for `SSLSocket` returns `None` rather than raising.

`chumicro_sockets._adapters.mp._MpSocketWrapper.recv_into` originally polyfilled `None → 0` to "treat as no data this tick".  This works for `chumicro-mqtt` because its RX loop already breaks on both EAGAIN and 0, but it **silently breaks any caller that distinguishes 0 (clean peer close) from EAGAIN (no data this tick)** — the `chumicro-requests` HTTP parser uses 0-return as the end-of-body signal for length-unknown responses, so on MP TLS every Content-Length-framed response failed with `HttpProtocolError("peer closed before response completed")` the moment a recv raced ahead of the peer's send.

Fix: the wrapper now raises `OSError(11)` on `None`, restoring the standard contract uniformly across plain TCP and TLS.  See `chumicro-sockets` 0.1.5 + slice 3c.

### Embedded `ssl.create_default_context()` is not the CPython equivalent

Probed live 2026-04-26 on Pi Pico W (MP 1.28.0 / rp2 + CP 10.2.0-rc.0) in flash mode:

* **MicroPython:** `ssl.create_default_context()` **doesn't exist** — `AttributeError("'module' object has no attribute 'create_default_context'")`.  You build a context yourself: `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` (no CAs loaded) or via `chumicro_sockets.ssl_context_with_ca(pem)`.
* **CircuitPython:** `ssl.create_default_context()` **exists and builds cheaply** (~80 bytes of heap), but the returned context has `check_hostname=False` and no CAs loaded.  Effectively useless for verifying a real-world cert without further setup.

The CPython intuition that `create_default_context()` loads a multi-hundred-KB system trust store doesn't apply — neither embedded runtime bundles a trust store at all.  Memory pressure during TLS handshake comes from the **mbedTLS handshake itself** (cipher suites, intermediate cert validation buffers), not from context construction.  CA-pinning via `chumicro_sockets.ssl_context_with_ca(pem)` is the canonical embedded pattern on both runtimes.

### MicroPython rp2 mbedTLS handshake doesn't fit into CIRCUITPY/MP RAM-mode bootstraps

A wifi → sockets → TLS → requests stack with the CA-pinned context only fits on the Pi Pico W class (256 KB RAM, ~150 KB heap free post-wifi) when deployed in **flash mode**.  RAM-mode keeps the full library bootstrap on the heap for the duration of the test, leaving < 50 KB for mbedTLS handshake — `ssl_context.wrap_socket(...)` fails with `OSError(12)` (ENOMEM) before any cert validation runs.

Document the constraint at every entry point: any acceptance runner / functional test that exercises HTTPS on these boards must default to `--deploy-mode flash`.  RAM-mode is fine for single-library tests; the multi-stack TLS chain isn't a single-library test.  Verified live during chumicro-requests slice 3c on Pi Pico W CP + MP (2026-04-26).

### MP rp2 firmware ships mbedTLS *without* `MBEDTLS_PEM_PARSE_C` — pass DER, not PEM, to `load_verify_locations`

`load_verify_locations(cadata=...)` accepts PEM on the ESP32 family but rejects it with `ValueError('invalid cert')` on the Pi Pico W RP2.  The split is build-config:

* The C-level `asn1_get_data` adds a NUL terminator to the buffer length when the input starts with `-----BEGIN ` *only* when `MBEDTLS_PEM_PARSE_C` is defined.  Without it, mbedTLS itself doesn't know how to parse PEM, returns `MBEDTLS_ERR_X509_BAD_INPUT_DATA`, and the Python layer surfaces "invalid cert".
* `MICROPY_INCLUDED_MBEDTLS_CONFIG_H` in `ports/rp2/mbedtls/mbedtls_config_port.h` does NOT define `MBEDTLS_PEM_PARSE_C` (and the common config it pulls in doesn't either).  ESP-IDF's mbedTLS does — that's the asymmetry.
* DER (raw binary, no PEM markers) parses on every port — `mbedtls_x509_crt_parse` walks the DER tag bytes directly without a preprocessing step.

Verified live on MP 1.28.0 against five `cadata` shapes on each board:

| input shape                                        | Pi Pico W RP2 | Lolin S2 ESP32-S2 |
|----------------------------------------------------|---------------|-------------------|
| PEM, bytes, multi-line LF, trailing newline        | invalid cert  | OK                |
| PEM, str (ASCII-decoded), same shape               | invalid cert  | OK                |
| PEM, bytes, no trailing newline                    | invalid cert  | OK                |
| PEM, bytes, CRLF line endings                      | invalid cert  | OK                |
| PEM body concatenated on one line (no markers)     | invalid cert  | invalid cert      |
| **DER (binary, ~752 bytes for an RSA-2048 cert)**  | **OK**        | **OK**            |

Lowest-common-denominator path for `chumicro_sockets._adapters.mp.ssl_context_with_ca`: accept PEM at the API surface (it's what `openssl req -x509 ...` produces by default), strip the header / footer / blank lines, base64-decode the body, pass raw DER to `load_verify_locations`.  See `libraries/sockets/src/chumicro_sockets/_adapters/mp.py` `_pem_to_der` helper.

End-to-end verification (Pi Pico W RP2, Mosquitto on 172.16.1.15:18883 with a self-signed cert): PEM → DER conversion → `verify_mode = CERT_REQUIRED` → mbedTLS validates against our embedded CA → TLS handshake completes → 3 QoS-1 PUBLISHes round-trip with PUBACKs.  No "blind trust" — the verification is real.  Two operational gotchas to flag for downstream consumers:

* **Device RTC matters.**  TLS validity-period checks fail with `ValueError('The certificate validity starts in the future')` if the device clock is unset (default ~2021 epoch on bare Pi Pico W).  Either NTP-sync after wifi-up or backdate cert `notBefore` for development.
* **mbedTLS error surface is conservative.**  "invalid cert" from `load_verify_locations` could mean "bad PEM" OR "bad base64 inside PEM" OR "DER doesn't parse" — there's no further detail.  When debugging, generate the DER form first (`openssl x509 -in ca.pem -outform DER -out ca.der`) and try that path before suspecting the cert itself.

### MP stdlib socket constructs in *blocking* mode by default

Same default as CPython.  If a library's tick / poll loop expects EAGAIN-on-no-data semantics, every consumer must call `setblocking(False)` after `socket.socket(...)` + `connect(...)` — there is no implicit non-blocking mode.  A blocking `recv` on a Pi Pico W RP2 will *eventually* return (lwIP has a long internal poll-or-give-up around 5–30 s depending on port + traffic), so the resulting hang doesn't look like a deadlock — it looks like a slow connection or a timeout.

Phase 7 Layer-3 tripped on this: `chumicro-mqtt`'s tick-shaped client called `recv_into` on a default-blocking MP socket, the recv blocked, the broker's CONNACK was already on the wire but the device's tick loop couldn't drain it within the 5 s `ack_timeout_seconds`, the deadline expired, the client transitioned to `FAILED`, self-heal rebuilt the socket — same blocking mode — and the cycle repeated forever.  Fix shape: `MQTTClient` enforces `setblocking(False)` on every socket it acquires; consumers don't have to remember.  See `libraries/mqtt/src/chumicro_mqtt/client.py` `_force_non_blocking` (commit landing this learning) and Phase 7 integration log §"Layer-3 broker round-trip — MP socket default-blocking mode".

TLS variant — verified live on MP 1.28.0 (Pi Pico W RP2 + Lolin S2 ESP32-S2): mbedTLS `SSLSocket` *does* expose `setblocking`, and `setblocking(False)` is honored on both boards.  `modtls_mbedtls.c` ships it in the method table (`{ MP_ROM_QSTR(MP_QSTR_setblocking), MP_ROM_PTR(&socket_setblocking_obj) }`); the `axTLS` variant exposes it too.  An older comment in `chumicro_sockets/_adapters/mp.py` claiming the Lolin S2 ESP32 drops `setblocking` was stale (likely from an older firmware) and has been removed.

There IS a contract divergence between plain TCP and TLS recv on MP: plain TCP raises `OSError(11)` on no-data in non-blocking mode, but TLS `recv` returns `None`.  Fix shape: `_MpSocketWrapper.recv_into` polyfill treats `None` as 0 bytes return, which feeds cleanly into chumicro-mqtt's `if got == 0: break` path.  End-to-end TLS+MQTT (3 QoS-1 PUBLISHes against a local self-signed broker) verified working on a Pi Pico W RP2 with this fix.

---

## Tooling and process

### Classifier ordering matters: drive-specificity before errno-substring

When several pattern lists feed one classifier, order by *prefix specificity* not by category, because nested errno strings will win against more-specific drive/port patterns. Rule: most-specific message prefix first. The CIRCUITPY-drive-found fix above is the canonical example. Commit `38fb039`.

### `replace_all` substring collisions silently corrupt longer names

Before `replace_all` on `_foo`, grep for longer names containing it (e.g. `_apply_foo`). Literal substitution does not respect identifier boundaries and will silently change `_apply_foo` → `_apply_bar` if you replace `_foo` → `_bar`. From user feedback memory; surfaced often enough to belong here too.

### `git commit -m` breaks in zsh on special characters

Always write the message to `.scratch/commit-msg.txt` with a file tool, then `git commit -F .scratch/commit-msg.txt`. The `git-commit` skill captures the full procedure. Heredoc / `echo` / `printf` from the agent terminal also fail — they truncate multi-line input and lose closing delimiters.

### Commits in this repo are authored by the human, not the agent

Strip Claude Code's default `Co-Authored-By: Claude …` trailer before writing the commit message. The agent is a tool, not a co-author. Enforced in `git-commit` skill. Commit `f0b9df1`.

### Branch protection breaks PAT-based bundle pushes; use SSH deploy keys

When the bundle repos got branch protection, `BUNDLE_TOKEN` (a PAT) couldn't bypass rules cleanly. Per-repo SSH deploy keys (single-repo scoped, least privilege) work. PAT retained only for `gh release create` API calls. See Decision 0019 area. Commit history pre-2026-04-15.

### `sys.modules`-walk leakage tests must capture *delta*, not absolute state

`test_public_api_alone_is_sufficient` originally walked global `sys.modules` after importing the third-party fixture, asserting nothing from `chumicro_timing` etc. was present. This works under per-package pytest (clean module table per subprocess) but false-positives under root-level pytest where prior library tests leave their modules cached.

Fix: snapshot `sys.modules` before the fixture import, snapshot again after, assert nothing prohibited appears in the *delta*. Correct under both regimes. Apply this pattern any time you assert "import of X did not transitively pull Y." Commit `73e9270`.

### Transport caches must invalidate on batch-execution failure, not just record the error

When the IDE-side `pytest_device.py` plugin caches a `Transport` per `(device, file)` tuple and a batch execution fails, **invalidating only the cached *result* leaves the transport itself in whatever state it crashed in** (raw REPL stuck mid-Ctrl-D, mpremote stuck mid-mount). The next file gets a cache hit, reuses the broken transport, and cascade-fails with cryptic errors.

Pattern: on batch-failure, call `transport.recover()` first; if recovery itself fails, drop the transport from the cache (`invalidate_device(device_id)`) but keep the cached batch *result* so subsequent items from the same file see the original failure rather than retrying. The CLI orchestrator had this from the start; the IDE plugin had to be brought into line. Commit `a4566eb`.

### `pytest --import-mode=importlib` is required when duplicate test basenames exist across packages

Once root pytest started collecting `workbench/deploy/tests/` + `workbench/repl/tests/` in the same session, duplicate basenames (`test_cli.py` exists in both) tripped pytest's classic-prepend collector with `ImportPathMismatchError`. Switching root pytest to `--import-mode=importlib` resolves it without renaming files. Commit `73e9270`. Decision 0008 originally selected importlib mode for similar reasons within a single library, then Decision 0009 superseded it for per-library pytest runs — this is the third regime: root-level multi-package collection.

### Workbench packages skip bundle staging + `.mpy` compile but keep VERSION gates

`libraries/` packages flow through `circup` / `mip` / `pip` and need bytecode + bundle staging. `workbench/` packages flow through `pip` only and skip both — but they keep `VERSION` files, `check-version`, `check-api`, and the experimental→stable promotion lifecycle. Decision 0032 codifies this. Both pre-merge gates were extended to walk `workbench/*/` in commit `104e129` (2026-04-25); release-workflow side covered by `fa8628c`.

### Wifi-substrate failure modes differ across the three runtimes (and all three are honest)

Three substrate variants exist for `chumicro_wifi`'s adapters and each surfaces an unreachable AP through a different code path:

| Substrate | When AP is unreachable |
|---|---|
| CircuitPython `wifi.radio` | Blocks inside `connect()` until its `timeout=` parameter expires, then raises `TimeoutError` / `ConnectionError` (both subclasses of `OSError`) |
| MicroPython ESP32 `network.WLAN` | Returns immediately from `connect()` (non-blocking), then raises `OSError("Wifi Internal State Error")` on the next interaction with the radio |
| MicroPython CYW43 (Pi Pico W) `network.WLAN` | Returns immediately, `isconnected()` silently stays `False`, no exception ever raised |

Adapter implication: each adapter has to handle its substrate's error idiom.  CP catches `OSError` (covers both `TimeoutError` + `ConnectionError`); MP-ESP32 + MP-RP2 just check `isconnected()` post-call.  All three preserve the same outward contract: `connect()` returns `True` on success, `False` on a clean refusal; programmer-error exceptions propagate to `WifiService.last_error`.

Substrate-honesty implication: every variant correctly refuses to claim `connected` or assign an IP when the AP is unreachable.  Surfaced 2026-04-25 during real-router-power-cycle acceptance on all four boards (Pi Pico W CP, Lolin S2 CP, Lolin S2 MP, Pi Pico W MP).  The MP-ESP32 exception is the only one that populates `WifiService.last_error` — the other two substrates silently fail, which is fine because the state machine's `RECONNECTING` / backoff logic doesn't depend on `last_error` being set.

### CircuitPython RAM-mode silently bypasses module-level `__getattr__`

PEP 562 module-level `__getattr__` is implemented at the firmware level on both MP and CP (verified against pinned source — `MICROPY_MODULE_GETATTR` default-on at `CORE_FEATURES` ROM level), but the **deploy harness's CircuitPython RAM-mode path wraps the package in a class-as-module stub (`_Mod`) that doesn't honour PEP 562**.  Lookups against the wrapper hit the stub's `__dict__` directly without consulting `__getattr__`, so the lazy attr table just silently doesn't fire.

The unit-test hint that masks this: looking up an unknown attr raises `AttributeError` even when the hook is bypassed, so a test like `with raises(AttributeError): module.NotARealSymbol` passes regardless of whether `__getattr__` is being invoked.  To detect bypass, you need a **positive** lazy-resolution test (`module.RealSymbol` returning the resolved value) — that's the one that fails on CP RAM-mode and reveals the harness behavior.

Practical consequence: **package-level PEP 562 `__getattr__` is unsafe for cross-runtime device libraries that need to work via RAM-mode deploy.**  Per-function lazy imports (named `from X import Y` inside a function — what `chumicro_kvstore._select_backend` does) work everywhere because the runtime's import machinery handles them, not the harness's wrapper.

Surfaced when chumicro-wifi Slice 0 added a PEP 562 table at the top of `__init__.py` mirroring `chumicro-deploy`; passed every host-side test, the MP unix-port functional test, and the on-device MP test, but failed exactly the positive-resolution scenarios on real CP boards.  Reverted wifi to eager package-level imports (Tier A — only 3 attrs, well below the threshold the research recommended PEP 562 for); kept lazy adapter selection inside `_select_adapter`.  Updated lazy-loading-research.md + patterns.md PEP 562 entry with the harness caveat.

### MicroPython rejects multiple inheritance from differing-layout `Exception` subclasses

A class like `class MissingConfigKey(ConfigError, KeyError): ...` parses fine on CPython but raises `TypeError: multiple bases have instance lay-out conflict` at module import on MicroPython 1.26 (and CircuitPython by extension).  Built-in exception types each carry their own C-level memory layout; MP's class machinery refuses to combine two of them in a single subclass.

The "ergonomic dual-catch" pattern (`except ConfigError` *or* `except KeyError` both work) is a CPython-only luxury for library code that has to load on device.  Pick **one** parent — usually the library's domain-specific base — and document it.  Callers catch via the single parent.

Surfaced in `chumicro-config` Slice 0 when `MissingConfigKey(ConfigError, KeyError)` and `InvalidConfigType(ConfigError, TypeError)` failed import on the MP unix-port even though host-side CPython tests passed.  Fix: drop the stdlib parents, document the workaround in Decision 0036 §2.

### Library import RAM cost: chumicro-mqtt is ~5x heavier than its peers

Per-library import cost measured on all four supported boards via `.scratch/run_ram_audit.py` (flash-mode, per-library, with cleanup before / after).  Each row is the heap free delta from `gc.mem_free()` immediately before and after `__import__(module)`.  Numbers accumulate — each library imports on top of the previous one, simulating realistic stack-up.

| library  | Lolin S2 CP | Pi Pico W CP | Lolin S2 MP | Pi Pico W MP |
|----------|------------:|-------------:|------------:|-------------:|
| compat   |        n/a* |         256  |        320  |        256   |
| timing   |     -5376** |        2768  |       2624  |       2656   |
| msgpack  |       480   |         480  |       4624  |       3920   |
| config   |      2864   |        2800  |       5760  |       5584   |
| runner   |     15360   |        6944  |       6320  |       6080   |
| kvstore  |     14848   |        6544  |       9088  |       8864   |
| sockets  |      2720   |        2720  |       3120  |       2960   |
| mqtt     |     33712   |       21216  |      23936  |      22928   |
| wifi     |     19168   |         n/a† |      13776  |      12976   |

\* USB-reattach race on a slow remount after `storage.erase_filesystem()`; longer post-cleanup wait fixes.
\** Allocator artifact — GC reaped more than the import allocated.
† Pi Pico W CP ran out of CIRCUITPY space before staging wifi (FAT-cluster-waste finding below).

**Three substrate-level facts the data surfaces:**

1. **`chumicro-mqtt` is the consistent heavyweight** — 21-34 KB across runtimes.  Roughly 4-5x the next-heaviest (kvstore, runner).  Worth the readability sacrifice if a future board is tight: lazy-import `_encoder` / `_decoder` until first publish saves ~10 KB if the user only subscribes.

2. **`chumicro-msgpack` cost differs by ~10x between CP and MP** — 480 bytes on CP, 4-5 KB on MP — because CP ships a native C `msgpack` module our package delegates to, while MP runs the pure-Python encoder.  Same library, very different on-device cost.

3. **CP numbers are noticeably lower than MP** for the larger libraries — CP's frozen-bytecode + `.mpy` cache reduce .py parse cost.  Real cold-start cost is closer to the MP numbers; CP's deploy mechanism gets a free amortization.

**Pi Pico W CIRCUITPY ran out before wifi** — not because heap was tight, but because FAT12's 4 KB cluster size means every .py file (most are < 1 KB of source) consumes at least 4 KB of disk.  8 libraries × ~10 files avg = ~80 files × 4 KB = ~320 KB, plus a cluster per subdirectory.  Pi Pico W's ~870 KB CIRCUITPY drive maxed out before the 9th library landed.  Real users dodge this entirely by shipping `.mpy` bytecode (smaller and fewer files) via the bundle staging pipeline.

**Verdict: no urgent RAM optimization needed.** Pi Pico W MP starts at 195 KB free; after loading all 9 libraries it still has ~140 KB.  The `MemoryBackend` lazy-import in `chumicro_kvstore` (commit `c8917f5`) shipped as a small cleanup; further per-library RAM tightening waits for a real constraint to surface.

**Worth it if a future board makes it necessary:** lazy `chumicro_mqtt._encoder`/`_decoder` (~10 KB), lazy `chumicro_kvstore`'s unused backends (~2-3 KB).  **Not worth it:** inlining modules into single files (kills traceback clarity), stripping `const()` declarations (negligible), removing docstrings (`.mpy` already strips them).

**Update 2026-04-26 — file count *is* the dominant flash cost on Pi Pico W.**  The 800 KB CIRCUITPY drive on Pi Pico W (FAT12, 4 KB clusters) means every `.mpy` file pays ≥ 4 KB on disk regardless of how small it actually is.  At 51 source files in the workspace, that's ~204 KB of pure cluster overhead before any content.  The earlier "not worth it: inlining modules" verdict was written assuming RAM was the bottleneck — when flash is the bottleneck, file count flips from neutral to load-bearing.  Two cuts that reflect this: (a) `bundle_manager._find_bundle_modules` now excludes `_HOST_ONLY_MODULES = {"testing.py"}` from the device bundle (~24 KB across 6 libraries that have it); (b) `chumicro-mqtt` consolidated 8 source files (`_packets`, `_encoder`, `_decoder`, `_errors`, `_state`, `client`, `__init__`, `testing`) → 4 (`_wire`, `client`, `__init__`, `testing`), with `testing` excluded from the bundle = 3 device files (saves ~16-20 KB FAT cluster cost on MQTT alone).  Traceback clarity stays acceptable because the splits were across one logical concern (wire format) — keeping `client` separate preserves the orchestration/wire boundary.

Audit runner: `.scratch/run_ram_audit.py` (gitignored — uses live wifi creds + spawns Mosquitto for MQTT-touching variants).  Cleanup helper: `.scratch/clean_circuitpy_board.py` — `storage.erase_filesystem()` for CP, `os.remove`/`os.rmdir` walk for MP.  Both auto-invoked before + after audits to keep boards in a known state.

Surfaced 2026-04-26 during the post-Phase-6 audit cycle.  Two prior runs broke board state (FSKit wedge from a single 9-library rsync burst on CP; RAM-mode bootstrap OOM on Pi Pico W CP).  Settled on flash-mode + per-library + 12 s post-cleanup wait + cleanup automation as the safe shape.

### `griffe check --search` silently ignores absolute paths in 2.x

Pass `--search` as a path *relative to the subprocess cwd*, not absolute. With griffe 2.0.2, an absolute `--search /abs/path/to/src` resolves nothing — griffe exits 0 with empty stdout/stderr regardless of breakages, making any check_api-style gate a silent no-op. The relative form (`--search workbench/deploy/src` from the repo root) works. This bug had been live in `scripts/check_api.py` since the gate was added: every PR was passing it without any actual API comparison. Caught during 2026-04-25 manual end-to-end validation while extending the gates to workbench. Fix: `str((package_root / "src").relative_to(ROOT))`. Always run a real-fixture pass when wiring tools that fail-soft like this — unit tests with mocked subprocesses can't see this class of regression.

### macOS doubles the on-device file count on FAT mounts via AppleDouble (`._foo`) sidecars

CircuitPython firmware does **not** auto-generate `.mpy` cache files at import time (`MICROPY_PERSISTENT_CODE_SAVE_FILE = 0` in `py/mpconfig.h`).  When the on-device file count looks ~2× higher than the `.py` source set predicts, the cause is **macOS AppleDouble sidecars** — the kernel's FAT driver writes a `._foo` companion alongside every `foo` whenever the source file has any extended attribute (which Finder, Spotlight, or even routine `pathlib.Path.write_bytes` can attach).  The board's `os.listdir` sees the sidecars as real files and they consume FAT clusters like any other.

`flash_drive.clean_dot_files` (`dot_clean -m`) cleans them up post-write, but only if the deploy path actually *calls* it.  `chumicro_deploy.circuitpython_transport.deploy_test_files` (rsync path) was already calling it; `deploy_files` (the `FileMapSource` per-file `write_bytes` path used by `Deployer.deploy()` and the on-board RAM audit) was **not**.  Fix landed in commit `<TODO>`: wire `disable_spotlight_indexing` + the new `neuter_macos_metadata` helper before writes and `clean_dot_files` after, in both flash-mode paths.

`neuter_macos_metadata` is the new persistent-prevention helper.  It plants two sentinels macOS honours across remounts (`.metadata_never_index` for Spotlight, `.fseventsd/no_log` for FSEvents) and removes already-accumulated noise directories (`.Spotlight-V100`, `.Trashes`, `.TemporaryItems`, `.DocumentRevisions-V100`).  The sentinels persist on the FAT volume so a board that's been deployed to once carries the suppression forward — the equivalent of `mdutil -i off` (which resets every remount) but durable.

Pi Pico W CP audit before/after on `chumicro_wifi`:

* **Before fix:** `lib_files=15`, `lib_bytes=52 878`, `flash_free=476 160` — 8 phantom `._foo` sidecars per package, ~33 KB sidecar bytes for the wifi tree alone.
* **After fix:** `lib_files=7`, `lib_bytes=20 110`, `flash_free=492 544` — exactly matches the `bundle_manager` Decision 0037 prediction (CP-mpy bundle = 7 files).

Lesson: when you're auditing on-device file counts on macOS, always cross-check against the bundle audit's prediction.  A 2× discrepancy is almost certainly AppleDouble noise, not a real deploy bug.
