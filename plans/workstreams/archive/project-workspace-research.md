# Project Workspace — Research Reference

Session memory for the project-workspace workstream.  Read this at the start of any session that picks up Decision 0029 / 0030 / 0031 work, so prior research does not have to be redone.

Companion to `plans/workstreams/project-workspace.md` (execution plan) and the three ADRs.  This file captures the **verified facts and findings** behind the decisions, with source file paths and line numbers so claims can be re-checked quickly.

## Canonical docs

- **Decision 0029** — workspace shape (template repo, UID identity, delegator `code.py`, derive firmware URLs, import-graph deploy, `library_sources:`, `devices.yml` zones, deploy workspace-agnostic)
- **Decision 0030** — config vs state split, TOML host → msgpack device, `chumicro-kvstore` replaces `chumicro-settings`
- **Decision 0031** — `chumicro-sockets` two-factory API (`tcp_client_socket` / `tls_client_socket`), no ACM dep, TLS config as injected `context`
- **`plans/workstreams/project-workspace.md`** — purpose, scope, library sequencing table, phases with tasks + acceptance
- **`plans/workstreams/repl-playground.md`** — sibling workstream for REPL side-portal features beyond Phase 2's minimum

## Library sequencing (seven libs total)

| Phase | Library | Depends on |
|-------|---------|-----------|
| 1 ✅ | `chumicro-deploy` (shipped 2026-04-22, `workbench/deploy/`, v0.0.0) | Decision 0028 transport |
| 2 | `chumicro-repl` | pyserial |
| 3 | `chumicro-kvstore` | msgpack |
| 3 | `chumicro-wifi` | runner, kvstore |
| 4 | `chumicro-workspace` + `chumicro-workspace-template` repo | deploy, repl, kvstore, wifi |
| 5 | `chumicro-sockets` | none (pure platform shim) |
| 6 | `chumicro-mqtt` | runner, wifi, sockets |
| 7 | sensor thing template | all prior |

## Key source-pinned facts

Paths below are under the pinned runtime trees in `.tools/` (gitignored).

### MicroPython wifi firmware auto-reconnect — ESP32

`ports/esp32/network_wlan.c:100-159` — event handler calls `esp_wifi_connect()` on disconnect while `wifi_sta_connect_requested` is true.

`ports/esp32/network_wlan.c:594-600` — exposes `wlan.config(reconnects=N)`:

- `reconnects=-1` → `conf_wifi_sta_reconnects=0` → unlimited retries (default)
- `reconnects=0`  → `conf_wifi_sta_reconnects=1` → one attempt then stop (effective "off")
- `reconnects=N`  → `conf_wifi_sta_reconnects=N+1` → N retries after initial

chumicro-wifi ownership stance (Phase 3a): library calls `wlan.config(reconnects=0)` after first successful connect, drives reconnect itself.

### MicroPython Pi Pico W — no firmware auto-reconnect

`extmod/network_cyw43.c` — `cyw43_wifi_join()` is one-shot.  No event handler retry.  chumicro-wifi is sole supervisor.

Library also applies `wlan.config(pm=0xa11140)` to kill default power-save idle lag.

### MicroPython Pi Pico W — TLS works (not what the folklore says)

`ports/rp2/mpconfigport.h:202,237` — `MICROPY_SSL_MBEDTLS=1` and `MICROPY_PY_SSL=1`.  mbedTLS is compiled in.  `import ssl` works on MP 1.26 Pico W builds.  The "no TLS on Pico W" story is stale MP 1.21-era.

### CircuitPython wifi auto-connect at boot

`supervisor/shared/web_workflow/web_workflow.c:239-277` — reads `CIRCUITPY_WIFI_SSID` / `CIRCUITPY_WIFI_PASSWORD` from `settings.toml` via `os.getenv`, enables radio, calls connect.  Happens before `code.py` runs.

chumicro-wifi ownership stance: template ships `settings.toml` **without** those keys so the supervisor path never fires.  Library calls `wifi.radio.connect()` itself.  Blocking stall on first connect accepted + documented.

### `select.poll()` / `ipoll()`

CP uses the shared `extmod/modselect.c` (grep `POLLIN|POLLOUT` under `.tools/circuitpython-10.1.4/extmod/modselect.c`).  Same polling code MP uses.  **Client-side connected sockets work correctly** on both.  The spurious-POLLIN quirk sometimes mentioned applies only to listening sockets waiting for `accept()` — MQTT / HTTP clients never hit it.

### CircuitPython NVM sizes (per-port, hardcoded)

`mpconfigport.h` defaults in each port:

- `ports/espressif/mpconfigport.h:45-46` — ESP32 family: **8 KB**
- `ports/raspberrypi/mpconfigport.h:27` — RP2040/RP2350: **4 KB**
- `ports/nordic/mpconfigport.h:47-48` — nRF52840: **4–8 KB** (board-dependent)
- `ports/atmel-samd/mpconfigport.h:97-98,127-128` — SAMD51 **8 KB**, **SAMD21 256 B**

Must be `FLASH_ERASE_SIZE`-aligned.

### CircuitPython NVM atomicity

- `ports/espressif/common-hal/nvm/ByteArray.c:59-104` — ESP32 erases-all-then-rewrites.  **Not byte-atomic.**  Power cut mid-write can corrupt entire blob.  CRC header + detect-and-reset strategy required (chumicro-kvstore does this).
- Nordic implementation uses per-page buffer swap — atomic within a page.

Wear leveling is absent in the CP wrapper itself; ESP32 rides on ESP-IDF NVS under the hood which is wear-leveled.

### MicroPython esp32.NVS

`ports/esp32/esp32_nvs.c:40-151`.  `set_i32/get_i32`, `set_blob/get_blob`, `erase_key`, `commit`.  **No string type** — only i32 and blob.  Explicit `commit()` required.  Wear-leveled by ESP-IDF.  Partition typically ~24 KB.

### MicroPython — no `settings.toml` parsing

Grep of MP tree returns zero matches for `settings.toml`.  Confirms it is CP-only; reusing it for app config is a CP-only footgun.

### CircuitPython settings.toml parser

`shared-module/os/getenv.c:26-417`.  Generic TOML string/int parser.  Accepts **any** key via `os.getenv(name, default)`.  No hardcoded `CIRCUITPY_` prefix in the parser; the firmware reads specific keys from its own callers.

### CircuitPython filesystem write-gate

`shared-module/storage/__init__.c:183-204` — `storage.remount("/", readonly=False)` raises `"Cannot remount path when visible via USB."` when USB MSC is active.  Workarounds: `storage.disable_usb_drive()` in `boot.py` (CP 9+) or GPIO-gated remount.  Hostile for casual users; this is why app config flows through deploy-time transform rather than on-device mutation.

## pythonProject3 MQTT refactor reference

File: `a previous-generation MQTT reference implementation` (~1043 lines).

### Preserve (solid)

| What | Lines |
|------|-------|
| Packet encode/decode primitives (`_encode_varlen`, `_decode_varlen`, `_encode_string`, `topic_matches`) | 977-1043 |
| `select.poll()` loop with `ipoll(0)` | 524 |
| Static 256 B RX buffer + degraded-state partial buffer | 231, 856-872 |
| Buffer constants (RX_BUFFER_SIZE=256, DEGRADED_BUFFER_SIZE=512, MAX_MESSAGE_SIZE=256 KB) | 69-72 |
| Callback registration API (`on_message`, `on_connect`, pattern-routed handlers) | 260-269 |
| Keepalive via PINGREQ | 510-513, 605, 929 |
| Will / retain | 211-215, 274-283, 402-413, 568-586 |
| `const()` usage throughout | 13-16 |

### Rewrite (broken / risky)

| What | Lines | Fix |
|------|-------|-----|
| QoS 1 tracking via single `_publish_retransmit` bool | 250 | Replace with per-packet_id dict |
| PUBACK match compares live MQTTMessage object | 392, 752 | Store `packet_id` bytes only |
| Callback deque popleft-then-requeue desync | 489-499, 495 | Per-packet_id callback map |
| Handshake lock blocks all sends on any waiting state | 537-542 | Block only the specific response type |
| `_packet_count_that_must_send` leak on partial send | 614-619, 648 | Deadline-bounded partial send |
| Oversized message silent drop (PUBACKs broker, empty payload to user) | 899-905 | `WhenOversized` enum: DROP_SILENT / DROP_WITH_EVENT (default) / DISCONNECT |
| `adafruit_connection_manager` dependency | 9, 294-301 | Switch to chumicro-sockets via `socket_factory=` |
| `adafruit_ticks` dependency | 10 | Switch to chumicro-timing |
| Clean-session hardcoded | 567 | Make configurable |

### Allow but don't implement (QoS 2)

Reserve constants `MQTT_PUBREC 0x50`, `MQTT_PUBREL 0x62`, `MQTT_PUBCOMP 0x70`.  Leave parallel in-flight dict shape in place.  Raise `UnsupportedQoSError` at call time.  Future addition is local, not invasive.

### Other pythonProject3 bits worth reading

- `basefilesystem/lib/basefs/thing_settings.py` — compressed JSON NVM storage ideas (numeric key mapping, byte-code compression for common JSON punctuation).  Not used directly — chumicro-kvstore uses msgpack — but pattern is informative.
- `basefilesystem/lib/basefs/hardware/{lolin_s2,s3_dev_kit,tinys3}.py` — per-board hardware abstraction pattern.  Informs how thing templates might declare hardware in config vs detect at runtime.
- `sync_to_circuitpy.py` — overlay-rsync deploy pattern.  Superseded by chumicro-deploy but documents what *not* to rebuild (blanket copy, no manifest, no import-graph).

## Public API sketches (from prior agreement)

### chumicro-sockets

```python
sock = tcp_client_socket(host, port, *, radio=None)
sock = tls_client_socket(host, port, *, context=None, radio=None)
ctx = ssl_context_with_ca(ca_pem=CA_PEM)
# On returned socket: send, recv_into, close, setblocking, settimeout, fileno.
# No connect() — factory connects before returning.
# No recv() — CP-incompatible idiom.
```

Adapters: `_adapters/{cp.py, mp_esp32.py, mp_rp2.py, cpython.py}`.  CP adapter reimplements the socketpool-memoization + TLS_MODE fake-context patterns in-tree (borrowed from ACM shape, not dep).

### chumicro-wifi

```python
config = WifiConfig(ssid, password, hostname=None, static_ip=None,
                    power_save=False,
                    connect_timeout_ms=15_000,
                    reconnect_backoff_start_ms=1_000,
                    reconnect_backoff_max_ms=60_000,
                    reconnect_max=None)
wifi = WifiService(config, ticks=ticks)
runner.add(wifi)
# wifi.state ∈ {DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, FAILED}
# wifi.connected: bool, wifi.ip: str|None, wifi.on_state_change(cb)
```

Ownership: library is sole supervisor.  CP template ships `settings.toml` without SSID keys.  MP ESP32: call `wlan.config(reconnects=0)` after first connect.  MP Pico W: apply `pm=0xa11140`, library is sole owner anyway.

### chumicro-kvstore

```python
store = KVStore(backend="auto")        # "nvm" | "nvs" | "littlefs" | "memory"
store["boot_count"] = store.get("boot_count", 0) + 1
store.commit()                          # explicit, flush backend
store.commit_if_changed()               # wear-mitigation
# store.capacity, store.bytes_used, store.is_corrupt
# KVStoreFull / KVStoreCorrupt exceptions
```

Backends: `_backends/{cp_nvm.py, mp_nvs.py, mp_littlefs.py, memory.py}`.  Values via `chumicro-msgpack`.  CP NVM prepends length + CRC header.

### chumicro-mqtt

```python
def make_socket():
    return tls_client_socket(broker, port, context=ctx, radio=wifi.radio)

mqtt = MqttService(
    MqttConfig(client_id=..., username=..., password=..., keep_alive=60,
               root_topic=..., when_oversized=WhenOversized.DROP_WITH_EVENT),
    socket_factory=make_socket,
    ticks=ticks,
)
runner.add(mqtt)
mqtt.subscribe("cmd/#", qos=1)
mqtt.publish("status", b"online", qos=1, retain=True)
@mqtt.on_message
def handle(topic, payload): ...
```

### Config pipeline (not a library — owned by chumicro-workspace)

- User edits `things/<name>/config.toml` (or `.yml` opt-in)
- Deployer merges with `workspace.yml` env defaults + `secrets.yml` at deploy
- Writes `/runtime_config.msgpack` to device
- App reads once: `config = msgpack.unpackb(open("/runtime_config.msgpack","rb").read())`
- `settings.toml` reserved for CP's own `CIRCUITPY_*` keys only.

## Device verification items still pending

Not design-critical for doc work; run when boards are plugged in.

### Phase 3a (wifi)

- Does `wifi.radio.enabled = False` in CP `boot.py` actually veto the supervisor auto-connect path?  (Belt-and-suspenders for the no-SSID-key approach.)
- CP blocking `connect()` on unresponsive AP — stall duration.  Informs `connect_timeout_ms` default.
- MP ESP32 `wlan.config(reconnects=0)` mid-session — effective, or must be pre-connect?  Source suggests mid-session works (it's just a config variable read at event time).
- Pico W MP `pm=0xa11140` responsiveness delta vs default.

### Phase 3b (kvstore)

- `print(len(microcontroller.nvm))` on ESP32-S3 and Pico W CP — confirm 8192 / 4096 match source defaults.
- MP ESP32 `esp32.NVS` commit survives hard reset.
- Write latency for 512 B blob across CP NVM / MP NVS / MP Pico W LittleFS.
- Pico W LittleFS atomic rename survives mid-rename power cut.

### Phase 5 / 6 (sockets / mqtt)

None specific — functional tests against a real broker on one CP + one MP board is Phase 6's acceptance.

## Open sub-questions

From `plans/open-questions.md` under the workstream entry:

- Library sequencing — does `chumicro-mqtt` refactor need to land before any first end-to-end sensor template, or can an MQTT-less headless thing prove things earlier?  Current answer: Phase 6 first, Phase 7 sensor uses it.  Reconsider if Phase 6 slips.
- Import-graph conditional imports — AST parsing sufficient for `try: import wifi; except ImportError` and `importlib.import_module(name)` cases?  Or is runtime trace-collection on CPython sim worth adding?
- `devices.yml` round-trip contract on unusual user edits (anchors, merge keys, multi-doc) — what does the write-safety contract promise vs what the YAML library actually preserves?

## OTA — deferred until after Phase 7

Explored as a later phase (Phase 8 in `project-workspace.md`).  Not in active scope.  Captured here so the next session doesn't have to reconstruct the thinking.

### Scope intent

Application-level OTA (code + libs), not firmware OTA.  Target audience: a thing on a wall / in a yard / stuck somewhere inconvenient, where pulling it back to a laptop to reflash is painful.  "Deploy without crawling behind the couch."

### Proposed shape

New library: `chumicro-update`.  Runner-shaped service.  Primary delivery over MQTT (already in the stack from Phase 6); HTTP delivery as an optional later adapter.

- Device subscribes to `chumicro/<device-id>/update`.
- Host publishes a msgpack-encoded payload: a manifest (version counter, per-file SHA256) + file tree.
- Device stages each file with `.new` suffix, verifies all hashes, atomic rename swap, `machine.soft_reset()` / `supervisor.reload()`.
- Failure at any step: discard `.new` files, keep running.

Host side: `chumicro-deploy` grows an `OTATransport` sibling to the serial transports it already has (Decision 0028 / 0031).  `python run.py deploy back-porch --via ota` packages files the same way as serial deploy, publishes over MQTT instead.

### CP filesystem-mode auto-detect

CP's CIRCUITPY drive vs filesystem-writable-from-code is mutually exclusive.  The workspace template ships a `boot.py` that picks by USB presence at boot:

```python
# boot.py — shipped by workspace template
import supervisor, storage

if supervisor.runtime.usb_connected:
    # Plugged into a host: keep CIRCUITPY drive visible for drag-drop dev.
    # FS stays readonly from code this session.  OTA is off.
    pass
else:
    # Running untethered: no host has the drive.  Open FS to code so OTA works.
    storage.remount("/", readonly=False)
```

Best-of-both without a config flag.  Caveats to document in the template:

- Mode is locked at boot.  Plug in USB mid-session → host won't get drag-drop until next reset.
- Unplug mid-session in dev mode → FS stays readonly that session; next boot auto-switches.
- UX hint: light an onboard LED per-mode so the user knows which session they're in.
- MP doesn't need this — FS always writable, OTA always available.

### Security — tiered

Hobbyist threat model.  Physical access to a board = game over on CP/MP-class hardware (no secure enclave, flash readable).  Realistic threats: on-subnet attacker, internet attacker if broker is exposed, replay of captured updates.  Goal: block network attackers and raise the bar on casual physical attacks.

**Tier 1 (baked in from v1):**

1. **TLS to broker + pinned CA** — already available via `chumicro-sockets` + `chumicro-mqtt` + `ssl_context_with_ca()`.  Blocks on-subnet sniffing and MITM.  Biggest single win.
2. **HMAC-SHA256 over payload** — pre-shared secret, computed over manifest + files.  Device rejects anything that doesn't verify.  Secret baked into device via `secrets.yml` → `/runtime_config.msgpack` pipeline (Decision 0030); rotatable per-deploy.
3. **Monotonic version counter** — manifest has `version: N`.  Device stores last-installed version in `chumicro-kvstore`.  Rejects `version <= stored`.  Defeats replay of old updates.
4. **MQTT broker ACLs + per-device credentials** — broker-side config.  Each device authenticates with its own creds; broker allows publish to `chumicro/<device-id>/update` only for the matching admin identity.
5. **Per-file SHA256 in manifest** — corruption detection at the protocol level.

Tier 1 combined defeats the realistic threats (on-subnet and internet attackers without broker creds or HMAC secret).

**Tier 2 (opt-in, v2+):**

6. **Ed25519 asymmetric signing** — private key on host laptop, public key on device.  A compromised device cannot forge updates.  Pure-Python Ed25519 verify is ~300 lines but slow (~5 s on ESP32).  Opt-in.
7. **Rollback on boot failure** — `app/` + `app_last_good/`, try new, revert on crash/reset-loop.  Hard to implement cleanly without a supervisor outside the Python process; needs `esp32.Partition` A/B (MP ESP32 only) or a watchdog + marker file pattern (flakier).
8. **Secrets-at-rest encryption** — encrypt the secrets section of `runtime_config.msgpack` with a key derived from `microcontroller.cpu.uid` / `machine.unique_id()`.  Defeats casual flash dumps; doesn't stop targeted extraction.

**Tier 3 (out of scope for chumicro):**

9. Secure boot via ESP32-S2/S3 fuses — requires custom firmware builds, abandons the stock CP/MP story.
10. ATECC608A / external secure element — board-specific, out of scope.
11. Attestation — builds on Tier 3 foundations.

### What's explicitly NOT in this phase

- **CP firmware self-update.** No exposed API.  `run.py upgrade-firmware` over serial / UF2 stays the firmware-update story.
- **MP ESP32 A/B firmware OTA via `esp32.Partition`.** Possible but a separate spike with its own signing / rollback / failure-mode design.  Not required for the common case.
- **Switching runtime to Zephyr / MCUboot.** Different ecosystem entirely; abandons the Python-focus that is chumicro's reason to exist.

### Revisit trigger

Someone has a thing running on a wall for >30 days and actually needs to push a code change without physical access.  Until then, `run.py deploy --via serial` and `run.py deploy --via ram` cover the real usage pattern.

### Open questions to resolve at explore-time

- Chunked delivery vs single-payload?  A 60 KB update payload is fine single-shot on MQTT; a 1 MB one (bundled lib/, rare) needs chunking.  Start single-shot, chunk when a real use case shows up.
- Update while runner is live vs stage-then-reset?  Runner-shaped service can stage files during normal operation, only soft-reset at swap time — short downtime window.
- Log channel for OTA status back to host — reuse `chumicro/<device-id>/log` MQTT topic or create a dedicated status topic?  Probably the general log topic.
- Relationship to `chumicro-repl`'s `tail()` — can `run.py deploy --via ota` feed post-update REPL output back the same way the serial transport does?  Yes, via MQTT log topic.

## Runtime source trees (pinned, gitignored)

- CircuitPython: `$CHUMICRO_ROOT/.tools/circuitpython-10.1.4/`
- MicroPython: `$CHUMICRO_ROOT/.tools/micropython-v1.26.0/`
- Rebuild via `python scripts/run.py prepare-circuitpython` / `prepare-micropython` if missing.

## Research URLs (for re-check)

### Wifi

- https://docs.circuitpython.org/en/latest/shared-bindings/wifi/index.html
- https://docs.micropython.org/en/latest/library/network.WLAN.html
- https://learn.adafruit.com/pico-w-wifi-with-circuitpython/create-your-settings-toml-file
- https://github.com/adafruit/circuitpython/issues/8032 — CP reconnect after router reboot
- https://github.com/adafruit/circuitpython/issues/7557 — CP connect() timeout on unresponsive DHCP
- https://github.com/adafruit/circuitpython/issues/7598 — CP web workflow auto-connect coupling
- https://github.com/micropython/micropython/issues/6747 — MP credentials not persisted on ESP32
- https://forums.raspberrypi.com/viewtopic.php?t=346686 — Pico W reconnect after extended outage

### Sockets / TLS

- https://docs.circuitpython.org/en/latest/shared-bindings/socketpool/
- https://docs.micropython.org/en/latest/library/socket.html
- https://github.com/adafruit/Adafruit_CircuitPython_ConnectionManager
- https://github.com/adafruit/Adafruit_CircuitPython_MiniMQTT
- https://github.com/adafruit/Adafruit_CircuitPython_Requests
- https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple

### Persistence

- https://docs.circuitpython.org/en/latest/shared-bindings/nvm/
- https://docs.micropython.org/en/latest/library/esp32.html
- https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/storage/nvs.html
- https://learn.adafruit.com/circuitpython-essentials/circuitpython-storage

### Workspace tooling prior art

- https://github.com/BradenM/micropy-cli — micropy-cli (MP-only, semi-dormant)
- https://github.com/BrianPugh/belay — belay decorator-based host↔device model
- https://docs.platformio.org/en/latest/projectconf/sections/env/index.html — PlatformIO `[env:name]` pattern

## Conventions the workstream needs to honor

From AGENTS.md / existing chumicro decisions:

- No `async`/`await`, no ISRs — tick-based runner pattern (Decision 0014).
- Constructor injection for time, I/O, network (Decision 0010).  `testing.py` submodule with fakes per library.
- Per-library tests via `python scripts/run.py test`, **94 %** coverage threshold for agents, 85 % human baseline (Decision 0025).
- f-strings everywhere, `const()` + `memoryview` + pre-allocated buffers in library code.
- No single-letter or abbreviated variable names — agents use descriptive names even in loops (Decision 0022, CHU001 lint).
- PEP 604 / 585 type syntax (`int | None`, `list[int]`); no `typing` import in library code (Decision 0021).
- `git commit -F .scratch/commit-msg.txt`, never `-m`.  Read `.github/skills/git-commit/SKILL.md` before every commit.
- After each unit of work: `task-checkpoint` skill — preflight + commit + push.

## Remember — things we explicitly decided against

So a future session does not reopen them without cause:

- Global pip-installed `chum` CLI (Decision 0029)
- `--type sensor|controller|headless` scaffold flags (Decision 0029)
- Generated `code.py` with `chum eject` escape hatch (Decision 0029)
- Port-keyed device identity (Decision 0029)
- Hosted per-board firmware catalog (Decision 0029)
- Blanket `shared/` copy on deploy (Decision 0029)
- Published-only library resolution — no dogfooding path (Decision 0029)
- Reusing `settings.toml` for app config (Decision 0030)
- Storing wifi creds in any KV store (Decision 0030)
- TOML or YAML parsing on device (Decision 0030)
- A unified "rich settings" library (Decision 0030)
- Overloaded `ssl=bool|context` socket arg (Decision 0031)
- Post-connect `wrap_socket()` step (Decision 0031)
- `adafruit_connection_manager` as a runtime dependency (Decision 0031)
- Bundled CA policy (Decision 0031)
- `ownership="delegate"` wifi mode (let CP's settings.toml win) (Phase 3a)
