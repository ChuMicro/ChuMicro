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

### rsync to CIRCUITPY can hang in uninterruptible kernel I/O

Surfaced 2026-05-03 during a `test-libraries-functional --library websockets --deploy-mode flash` run that pivoted from Pi Pico W to Lolin S2 mid-session. The Pi Pico W half passed; the Lolin S2 rsync started, then the rsync subprocess hung in D-state. `kill -9` was impossible — only a board reboot (unplug + replug) cleared it. `diskarbitrationd` was healthy throughout; this is **not** the FSKit wedge from the section above.

The root cause turned out to be **three compounding bugs**:

1. **CP autoreload trampling on host writes.** `_stage_to_flash` and `deploy_files` both did host-side drive operations BEFORE sending `supervisor.runtime.autoreload = False`. With autoreload ON (the default), CP's filesystem watcher fires a soft-reboot on each file change. Each soft-reboot re-enumerates USB-CDC. Multiple re-enumerations during prep left the board's USB-CDC stack in a degraded state, so when rsync started its first batch of writes the next `write()` landed in uninterruptible kernel I/O wait. Fix: `_disable_autoreload_before_drive_writes()` helper called as the FIRST thing after `_enter_raw_repl()`, before any drive operation. No symmetric restore is needed at disconnect: `deploy_files`'s mid-method Ctrl-D soft-reboot resets `supervisor.runtime.autoreload` to default-on as a side effect, and `_stage_to_flash` deliberately leaves it off (the harness drives the raw REPL session itself; `code.py`-style reload-on-edit isn't relevant). An earlier deploy-audit pass DID add an explicit `_restore_autoreload()` call inside `disconnect()`, but it stacked a watcher-fired reboot on top of the previously-present explicit Ctrl-D, wedging ESP32-S2 USB-CDC roughly 1-in-4 sessions; both the explicit Ctrl-D and the autoreload-on were removed and `disconnect()` is now pure teardown (Ctrl-B + close).

2. **Excess pre-rsync drive writes.** Even with autoreload OFF, every host-side write to a USB FAT mount adds a wedge-risk vector — Spotlight indexer, FSEvents daemon, and the FAT controller all see each write. The old prep wrote `.chu-probe` (writability test), planted three macOS skip-sentinels (`.metadata_never_index` / `.fseventsd/no_log` / `.Trashes`), removed three noise dirs (`.Spotlight-V100` / `.TemporaryItems` / `.DocumentRevisions-V100`), and *then* started rsync. Six on-drive ops before the actual deploy. Fix: dropped `.chu-probe` from the default `_resolve_circuitpy_drive` path (rsync's own write failure now signals unwritable mounts; only the wipe-and-wait poll keeps the probe behind a `probe_writable=True` opt-in); moved sentinel plants into the local rsync staging tree so they ride along in the single rsync pass; moved noise-dir rmtree to *after* rsync where the drive is in a known state. Net pre-rsync drive writes: zero.

3. **No `timeout=` on the rsync subprocess.** Once the kernel I/O wedged, rsync had no way out. SIGTERM/SIGKILL only fire when the process can be reaped — a child stuck in D-state is unkillable until the underlying USB connection is forcibly closed via board reset. Fix: every CIRCUITPY-touching subprocess in `chumicro_deploy.flash_drive` now passes `timeout=` (`RSYNC_TIMEOUT_SECONDS=90`, `SYNC_TIMEOUT_SECONDS=30`, `METADATA_HELPER_TIMEOUT_SECONDS=10`). On `subprocess.TimeoutExpired` the deploy raises `FlashDriveError` with the recovery procedure ("reboot the board"). Timeout enforcement is best-effort — if the parent's `waitpid` itself blocks, the timeout can't fire — but for the common "rsync got 95% through and the next `write()` hangs" pattern it converts a process wedge into a clean error.

Cleanup that fell out: `disable_spotlight_indexing` (`mdutil -i off`) was redundant with the `.metadata_never_index` sentinel — both tell Spotlight the same thing and the file form survives remount whereas mdutil state does not. Removed entirely. `neuter_macos_metadata` split into `plant_macos_sentinels_in_staging` (writes to a local staging dir, no drive I/O) and `cleanup_macos_noise_dirs_post_rsync` (called after rsync). Regression test `test_flash_stage_disables_autoreload_before_any_drive_write` asserts the wire-side autoreload-off command precedes the rsync subprocess invocation.

Detection-only signals like "warn when more than one CIRCUITPY mount" are useless in our rig because the normal state is two boards plugged in simultaneously (Lolin S2 + Pi Pico W) — both labeled CIRCUITPY, macOS auto-numbers the second to `CIRCUITPY 1`. UID-based identity matching (already implemented in `_verify_drive_for_board`) is the real disambiguator.

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

### MP `network.WLAN` API is identical between ESP-IDF and CYW43; only the `config(...)` knobs differ

`network.WLAN(network.STA_IF)`, `active`, `connect`, `isconnected`, `ifconfig`, `disconnect` all behave the same on the MP ESP-IDF port (ESP32, S2, S3, C3, C6) and the MP CYW43 port (Pi Pico W).  What differs is which `wlan.config(**kwargs)` knobs the substrate accepts and *when* they take effect:

* **ESP-IDF**: `config(reconnects=0)` disables the firmware-level auto-reconnect supervisor.  Read at re-association time, not activation time, so it must be applied *after* the first successful link, not at configure time.  Setting it before the first link silently no-ops or raises.
* **CYW43**: `config(pm=0xa11140)` disables idle power-save (eliminates ~30-100 ms tick spikes).  Stateless from the substrate's perspective — applied at configure time, takes effect on the next idle window.  No firmware reconnect supervisor on CYW43, so no `reconnects` knob exists.

Both knobs are `try`/`except (OSError, ValueError)` — older MP firmware variants (and non-ESP-IDF/non-CYW43 builds) may not expose them at all.  Substrate detection is a one-line probe: `try: import esp32 → "espidf"; except ImportError → "cyw43"`.  The MP `esp32` module ships with every ESP-IDF chip and is absent on CYW43.  See `chumicro_wifi._adapters.mp`.  Commit `0304542` consolidated two per-stack adapter classes into one substrate-aware adapter once the API-identity was confirmed across our four-board matrix.

### A naive `recv_into` loop can starve cooperative tasks when the kernel TCP buffer is fat

`while True: recv_into(...); break-on-EAGAIN` is the obvious shape for a tick-based protocol parser, but on a Pi Pico W RP2 (lwIP TCP) the kernel can hold ~16-32 KB of inbound bytes, and our `rx_buffer_size`-bounded reads (256 B / call) mean a single `handle()` tick will iterate 60-128 times before EAGAIN drains the buffer.  At 50-200 µs per syscall + memmove on rp2, that's 6-25 ms inside a *single tick* — enough to visibly stutter a 10 ms LED blink rhythm or break a sub-second control loop.

The old basefs MQTT impl (`/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`) avoided this implicitly: `_read_socket` does **one** `recv_into` per loop call (no inner loop), so each loop call is bounded by `RX_BUFFER_SIZE` regardless of how much data is in the kernel buffer.  A 100 KB blob takes 400+ loop calls to ingest, but every call is short.

`chumicro-mqtt` 0.1.4 adopts a hybrid: a `recv_budget_per_tick` knob (default 1024 B) caps the per-tick byte budget while still letting a tick do multiple recv calls when bytes are available.  Default 1024 = 4× the steady RX buffer (256 B) = drains a typical PUBLISH in one tick AND keeps tick latency well under 10 ms even on rp2.  Configurable upward for things that want fast big-blob ingestion at the cost of LED smoothness.  The lesson is general: any tick-shaped reader on a fat kernel buffer needs an explicit per-tick byte budget OR an explicit per-tick iteration count — implicit "drain until EAGAIN" is a foot-gun.

### CircuitPython server-side TLS works (the API is just different from CPython's)

Initial conclusion ("CP can't host TLS server because `ssl.PROTOCOL_TLS_SERVER` doesn't exist") was wrong — corrected by the user pointing at adafruit_httpserver's working `https=True` path.  CircuitPython's `ssl` module exposes only `SSLContext` and `create_default_context`, but the recipe that works is:

```python
ctx = ssl.create_default_context()        # nominally client-side
ctx.load_verify_locations(cadata="")      # required pre-load step
ctx.load_cert_chain(cert_path, key_path)  # paths, not bytes
sock = ctx.wrap_socket(sock, server_side=True)  # works anyway
```

Two gotchas that bit me on the way:

1. `load_cert_chain` on CP **requires filesystem paths**, not in-memory PEM bytes.  Passing bytes raises `OSError(2, <bytes>)` — mbedTLS interprets them as a path it can't open.  CPython + MicroPython both accept bytes; CP is the odd one.
2. The empty `load_verify_locations(cadata="")` call is required before `load_cert_chain` will accept the server identity (verified empirically — without it, the chain load was ignored).

Live-verified on Lolin S2 ESP32-S2 / CP 10.2.0-rc.0: 6 KB SSLContext + 35 KB handshake heap cost, ~2 MB free heap remaining; HTTPS GET round-trip from a host CPython client succeeded.  Adafruit's "limited to ESP32-S3" framing in the `httpserver` README is overstated — S2 works fine.

`chumicro_sockets.ssl_context_with_cert_and_key_paths(cert_path, key_path)` is the cross-runtime API that handles all three runtimes (CP needs paths; MP + CPython convert paths to bytes internally and use the in-memory helper).

### TLS handshake heap differences across runtime / port — the real story is allocator placement, not HW accel

Slice 7t / 7d live measurements on Pi Pico W MP (rp2 port) vs Lolin S2 MP (ESP32-S2 port) vs Lolin S2 CP, all running CHUmicro's TLS server with the same RSA-2048 cert + DER encoding:

* **Pi Pico W MP (rp2):** TLS handshake heap cost = **~25 KB**.
* **Lolin S2 MP (ESP32-S2):** TLS handshake heap cost = **~1 KB** (944 bytes).
* **Lolin S2 CP (ESP32-S2):** TLS handshake heap cost = **~35 KB**.

An earlier version of this file blamed the rp2-vs-S2 delta on hardware-accelerated mbedTLS on the S2 (`MBEDTLS_HW_*` AES / SHA / RSA peripherals, hand-waved as "handshake state lives in HW buffers").  **That framing is wrong** and was retired after a deep source dive (2026-05-02).  Hardware accel on the S2 (`MBEDTLS_HARDWARE_AES`, `MBEDTLS_HARDWARE_SHA`, `MBEDTLS_HARDWARE_MPI`) replaces the C reference implementations of AES / SHA / bignum with peripheral-driver calls — it shortens handshake **CPU time** (hundreds of ms), not heap footprint.  mbedTLS allocates the same record buffers, x509 parse arena, and ECDH/RSA scratch with or without HW accel.

What actually drives the deltas:

1. **Allocator placement.**  CP-rp2's mbedtls config (`.tools/circuitpython-10.1.4/lib/mbedtls_config/mbedtls_config.h:117-119`) sets `MBEDTLS_PLATFORM_STD_CALLOC = m_tracked_calloc` — every mbedTLS internal allocation routes through CP's GC heap (`m_malloc_maybe`).  The 16 KB IN buffer + 4 KB OUT buffer + handshake working set show up directly in `gc.mem_free()`.  CP-espressif uses ESP-IDF's `esp_config.h` and `heap_caps_malloc` — mbedTLS internal buffers go to ESP-IDF heap.  But on espressif both runtimes have `MICROPY_GC_SPLIT_HEAP_AUTO=1`, so `gc.mem_free()` includes the largest free ESP-IDF block via `heap_caps_get_largest_free_block` and still reflects the ~35 KB consumption — just at a different probe boundary.
2. **Per-connection vs per-context state.**  CP's `shared-module/ssl/SSLSocket.h:21-43` inlines `mbedtls_entropy_context`, `mbedtls_ctr_drbg_context`, `mbedtls_ssl_context`, `mbedtls_ssl_config`, two `mbedtls_x509_crt`, and `mbedtls_pk_context` into the **per-connection** `ssl_sslsocket_obj_t`.  `accept()` (`shared-module/ssl/SSLSocket.c:442-452`) creates a brand-new SSLSocket + runs `mbedtls_ssl_setup` per connection, so the 16K+4K record buffers + cert/key parsing arena are paid every accept.  MP (`extmod/modtls_mbedtls.c:84-119`) parks all the heavy state on the **`mp_obj_ssl_context_t`** — created once at `ssl.SSLContext(...)` time.  The chumicro MP adapter reuses one SSLContext across all accepts (`libraries/sockets/src/chumicro_sockets/_adapters/mp.py:344-359`), so the bulk allocation happens once at context-build time and the per-accept measurement looks tiny.

The "S2 = 1 KB / rp2 = 25 KB / CP-S2 = 35 KB" pattern is fully explained by these two facts.  Reference: [micropython/micropython#8940](https://github.com/micropython/micropython/issues/8940) traces the ~35 KB mbedTLS handshake working set ("16717, 4429, 220, 128, 2240..." — 16 KB IN + 4 KB OUT + cert parse arena + ECDH scratch).

Practical implication for sizing: every supported board pays roughly the same total mbedTLS heap (~35 KB) for a server-side handshake.  Where it lands (Python GC heap vs ESP-IDF heap) depends on the runtime/port pair, but the total is similar.  Pi Pico W has ~115-130 KB free post-wifi-up so a single-in-flight TLS server fits but is tight; ESP32-S2/S3 have ~150 KB+ and comfortably support multi-in-flight TLS.

### CircuitPython rp2 (Pi Pico W) — server-side TLS unsupported (mid-handshake OSError(32) + CYW43 chip wedge)

Same chumicro-sockets code path that succeeded on Lolin S2 ESP32-S2 (CP 10.2.0-rc.0) reaches the listener-open + first accept, but `accept()` raises `OSError(32)` (EPIPE) immediately after the TLS handshake bytes traverse.  Heap was ~115 KB free at the time, so not a memory issue.

An earlier version of this file blamed an "rp2-port mbedTLS feature-flag gap vs ESP-IDF's mbedTLS" (parallel to the `MBEDTLS_PEM_PARSE_C` story for CA-load).  **That framing was retired** after a 2026-05-02 source dive verified the structural claim does not hold up:

* mbedTLS feature flags on rp2 are fine.  `.tools/circuitpython-10.1.4/lib/mbedtls_config/mbedtls_config.h:53-105` enables every server-side flag we'd need: `MBEDTLS_SSL_SRV_C`, `MBEDTLS_SSL_TLS_C`, `MBEDTLS_KEY_EXCHANGE_RSA_ENABLED`, `MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED`, `MBEDTLS_PEM_PARSE_C`, `MBEDTLS_X509_CRT_PARSE_C`, `MBEDTLS_PK_PARSE_C`, `MBEDTLS_RSA_C`.  Buffer sizes: IN 16384, OUT 4096.  MP-on-rp2 working with the same hardware confirms server-side TLS primitives are present and functional.
* In CP 10.1.4 and 10.2.0-rc.0 both, **espressif and rp2 use the shared `shared-module/ssl/SSLSocket.c`** — there is no per-port override on either side.  Both ports run `do_handshake(sslsock)` synchronously inside `common_hal_ssl_sslsocket_accept` (`shared-module/ssl/SSLSocket.c:442-452`).  An "espressif lazy / rp2 eager" structural divergence sometimes cited from older (pre-9.0, Oct-2023) CP source no longer exists.
* `OSError(32)` (EPIPE) is not produced by any direct path I could trace in `ports/raspberrypi/common-hal/socketpool/Socket.c`.  The lwIP `error_lookup_table` (lines 95-117 of CP 10.2.0-rc.0) maps to ECONNRESET (104), ENOTCONN (128), ECONNABORTED, ENOMEM — but never EPIPE.  EPIPE only originates from `mp_raise_BrokenPipeError()` in `shared-bindings/socketpool/Socket.c:233,239,263,270` and `shared-bindings/ssl/SSLSocket.c:220,226`.  The SSL BIO's `_mbedtls_ssl_send` calls the C-level `socketpool_socket_send` helper, which bypasses the shared-bindings BrokenPipe paths, so the OSError(32) path through the SSL handshake is not source-derivable.

What chumicro does that may be the trigger and remains untested: `libraries/sockets/src/chumicro_sockets/_adapters/cp.py:239-243` calls `wrapped.setblocking(False)` on the wrapped TLS listener after wrap+bind+listen, before accept.  Each accepted client inherits `accepted->timeout = self->timeout` (`ports/raspberrypi/common-hal/socketpool/Socket.c:817`), so the eager `do_handshake` runs on a non-blocking socket.  `do_handshake` itself handles `WANT_READ`/`WANT_WRITE` correctly via a `mp_hal_delay_ms(1)` loop, so non-blocking-by-itself shouldn't break — but this is the one chumicro-controlled variable left in the loop.

For HTTPS-server use cases on CircuitPython today, the operational guidance still stands: prefer ESP32-family boards (S2 / S3) over Pi Pico W.  See `.scratch/run_cp_rp2_tls_listener_modes.py` for the experimental probe that distinguishes "chumicro setblocking ordering" from "upstream CP-rp2 bug" — until that probe runs, the right framing is "CP-rp2 HTTPS server fails for reasons not yet pinned" rather than the upstream-bug claim.

#### Empirical findings from `.scratch/run_cp_rp2_tls_listener_modes.py` (2026-05-02)

Live-reproduced the OSError(32) on Pi Pico W CP 10.2.0-rc.0 with a host-side CPython HTTPS client connecting to the device's RSA-2048 self-signed TLS server on port 8451 (nonblocking listener mode, the chumicro default).  Full trace from the run:

```
WIFI_OK ip=172.16.1.21
CONTEXT_BUILT
HEAP_FREE_PRE_LISTEN 140976
LISTENER_NONBLOCKING
LISTENING_ON_PORT 8451
HEAP_FREE_PRE_ACCEPT 114752    (~26 KB consumed by listener wrap)
STATUS: FAIL_ACCEPT OSError(32,)
```

Two facts that update the framing above:

1. **The OSError(32) fires DURING the eager handshake inside `accept()`, not pre-handshake or post-handshake.** A real host TLS client connects (the probe's host poll loop running concurrent with the deploy hits the device while it's in the accept loop), the device's `common_hal_ssl_sslsocket_accept` runs `do_handshake` on the wrapped client socket, and the handshake fails with mbedTLS returning a small-negative error that the `mbedtls_raise_error` small-int trap renders as `OSError(32)`.  This is *not* the "post-handshake EPIPE" the original learnings text claimed — handshake bytes are still flying when it fires.
2. **chumicro's `setblocking(False)` ordering is not the trigger.** The blocking-listener variant of the probe could not be tested in the same session because of side-effect (3) below; on theory grounds the eager `do_handshake` loops correctly on `WANT_READ`/`WANT_WRITE` regardless of listener-blocking mode (`shared-module/ssl/SSLSocket.c:389-421`).  Filing the upstream issue as "TLS server-side OSError(32) on rp2 / CYW43" without the listener-mode hypothesis attached.

3. **OSError(32) puts the CYW43 chip in a wedged state — every subsequent `wifi.radio.connect()` returns `ConnectionError("Unknown failure 1")`.** This is independently reproducible: direct `wifi.radio.connect("Things Cat", PASSWORD, timeout=15)` from the REPL (zero chumicro code in the path) fails identically after the probe runs and hits OSError(32).  The wedged state survives:
    * `microcontroller.reset()` (rp2040 hard reset) — the rp2040's reset doesn't toggle the CYW43's `WL_REG_ON` line, so the CYW43 chip's state persists.
    * `wifi.radio.enabled = False` / `True` cycling.
    * `wifi.radio.stop_station()` alone.

   What *does* recover the chip in software: `wifi.radio.stop_station()` followed by `wifi.radio.start_station()` followed by `wifi.radio.connect(...)`.  Without explicit `start_station()`, `connect()` keeps returning `Unknown failure 1`.  The board's solid green LED (`CYW_GPIO0`, driven by CYW43 firmware not the rp2040) reflects the wedged state.  USB power-cycle (full power off) is the only reliable way to clear the chip — and it implies the fault is in the CYW43's wpa_supplicant state, not anywhere CP can fully reach via API.

   Operational consequence: any CP-rp2 TLS-server experiment that hits OSError(32) wedges the chip until recovery.  Iterating the probe is rate-limited to "one failing run per power cycle" unless the recovery dance is automated.  This is itself an upstream CP-rp2 bug (a TLS handshake error path that corrupts CYW43 station-mode state), separate from the OSError(32) handshake bug itself but compounding it.

The originally-quoted measurement "Heap was ~115 KB free at the time, so not a memory issue" still stands — `HEAP_FREE_PRE_ACCEPT 114752` matches.

Cross-reference: [adafruit/circuitpython#10339](https://github.com/adafruit/circuitpython/issues/10339) reports a *client-side* TLS bug on Pi Pico **2** W (rp2350) with a different error class (`MBEDTLS_ERR_X509_CERT_VERIFY_FAILED`).  Not our bug, but a sister datapoint of "CP TLS on rp2 + CYW43 is fragile in ways the espressif port is not."

Filing-ready summary for an upstream issue: **TLS server-side `accept()` raises `OSError(32)` mid-handshake on Pi Pico W (rp2040 + CYW43439), CP 10.2.0-rc.0; failure additionally wedges CYW43 station-mode state until USB power-cycle.** Reproduce via `.scratch/run_cp_rp2_tls_listener_modes.py`.

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

### Pin the root, not the chain — embedded TLS clients only need the trust anchor

mbedTLS validates the server's chain against the client's trust anchor.  The server presents its leaf + intermediates during the handshake; the client only needs the **root** that signs the chain.  Pinning the whole chain (root + intermediates + leaf) wastes heap on every handshake and (worse) silently drags in cross-signs that may have far-future `NotBefore` dates and force RTC seeding the test would otherwise not need.

Concrete instance from `libraries/requests/functional_tests/test_real_get_tls.py` (2026-05-02): example.com's chain has three certs — Cloudflare's TLS Issuing ECC CA 1 intermediate, the SSL.com TLS ECC Root CA 2022, and an AAA Comodo cross-sign of the same SSL.com root with `NotBefore` 2025-08-01.  Initial draft of the test pinned all three (3.7 KB PEM); the cross-sign forced an RTC seed on every embedded port (boot RTC = 2021-01-01) and the extra heap pushed Pi Pico W MP into ENOMEM during `ssl.wrap_socket`.  Switching to just the SSL.com root (1.3 KB PEM, `NotBefore` 2022-10-21) shrank the bundle, the chain still validates because Cloudflare's intermediate comes from the server, and Pi Pico W MP now passes (5.27 s).

How to find the right cert in a server's `s_client -showcerts` output: the **last** cert in the printed chain is the root (or the highest cert the server chose to send, which chains directly to a root the client should pin).  Discard everything above it.

RTC seeding is still needed if the chosen root's `NotBefore` post-dates the boot RTC default (most embedded ports default to 2021-01-01 / Unix epoch).  But pinning the root with the *earliest viable* `NotBefore` minimises how far forward the device clock has to be nudged.

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

### MP doesn't expose `BlockingIOError` as a built-in

CPython promotes `EAGAIN`/`EWOULDBLOCK` `OSError`s to the dedicated `BlockingIOError` subclass (PEP 3151).  MicroPython doesn't — code that references `BlockingIOError` by bare name compiles fine on CPython but fails with `NameError` the first time the line executes on MP.  Surfaces only on the path that actually hits it; module-level `import` of code containing `except BlockingIOError:` succeeds because the name lookup is deferred.  Affects `chumicro_websockets._session._is_eagain` and `chumicro_websockets.testing` — discovered when `chumicro_websockets` outbound fragmentation tests ran on MP unix-port.  Portable check: `isinstance(error, OSError) and error.args and error.args[0] in (errno.EAGAIN, errno.EWOULDBLOCK)`.

### MP `collections.deque()` requires positional `iterable, maxlen` args

CPython allows `deque()` with no args (defaults to empty + unbounded).  MP's `deque` doesn't — `from collections import deque; deque()` raises `TypeError: function missing 2 required positional arguments`.  Use `deque((), 0)` for the same semantics.  Surfaced when running `chumicro_mqtt` fragmentation tests on MP unix-port via `chumicro_sockets.testing.FakeSocket`, which calls `deque()` at line 50.  Test helpers that aren't exercised on MP can ship CPython-only API uses without ever knowing.

### CP unix-port `hashlib` only exposes sha256 — no sha1, no `hashlib.new()`

`dir(hashlib)` on `circuitpython-10.1.4` unix-port returns `['__class__', '__name__', '__dict__', 'sha256']`.  Code that needs SHA-1 (e.g. `chumicro_websockets._wire._sha1_digest` for the RFC 6455 `Sec-WebSocket-Key` challenge) breaks with `AttributeError: 'module' object has no attribute 'sha1'`.  Hidden until now because no chumicro test had ever run on CP unix-port without skipping (every CP test imports pytest / tracemalloc / unittest, which all fail to import there).  Workaround for tests: detect with `_HAS_SHA1 = hasattr(hashlib, "sha1") or hasattr(hashlib, "new")` and early-return.  Real fix: bundle a pure-Python SHA-1 fallback in `chumicro_compat`.

### Test-file imports fragment the unix-port heap as much as anything else

Running the cross-runtime test harness on MP / CP unix-port loads every library's test files into a single Python process.  Each test module's body — function definitions, class fixtures, canned bytes literals, dict scripts — becomes permanent allocations rooted from `sys.modules`.  Measurement: importing `libraries/requests/tests/test_*.py` (~1000 lines, no tests run) drops the largest-contiguous-block ratio from 0.9559 to 0.8463 on a fresh MP unix-port heap.  That residue is the root cause of the order-dependent test failures in `chumicro_requests` (committed as test-environment fragmentation in 2026-05-03 investigation), and it doesn't represent real-board behaviour at all (frozen modules don't take heap, test files don't ship to devices).  Mitigation: subprocess-per-file isolation in the harness (shipped this commit), so each test file starts with a clean heap.

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

### `chumicro-msgpack` wire format = PyPI `msgpack` with `use_single_float=True`

`chumicro_msgpack.packb(obj)` produces bytes byte-for-byte identical to `msgpack.packb(obj, use_single_float=True)` for any subset-conforming input (ints in `[-2^31, 2^32-1]`, no float64, sizes < 65 536, no ext types).  This is the load-bearing fact that lets workbench packages import PyPI `msgpack` while device packages import `chumicro_msgpack` — they share a wire format with zero conversion.  The contract is pinned by `test_byte_identity_with_pypi_msgpack` in `libraries/msgpack/tests/test_msgpack_pytest.py`.

Two ways the contract has historically broken and would break again without vigilance:

1. **PyPI default float encoding is float64.**  Without `use_single_float=True`, `msgpack.packb(0.5)` emits `0xcb` + 8 bytes; chumicro's decoder rejects `0xcb`.  The workbench writer in `workbench/workspace/src/chumicro_workspace/writer.py` hard-codes the flag for this reason.
2. **CPython sees PyPI msgpack via the same `import msgpack`.**  An earlier version of `chumicro_msgpack/__init__.py` did `try: from msgpack import pack, unpack` on every runtime — on CPython that succeeded against the PyPI package and silently switched the encoder to one that produced float64 / int64 / strict_map_key bytes.  Commit `fecbc4c` gated the native delegation to `sys.implementation.name == "circuitpython"`.  If you see a similar pattern anywhere — `try: import <X>` where `<X>` is a CPython PyPI package name with a different contract from the device-side library — flag it.

The decoder names the offending tag in its `ValueError` (e.g. `"float64 (0xcb) not in chumicro msgpack subset; encode with msgpack.packb(obj, use_single_float=True)"`) so a debugging session lands on the fix immediately.
