# Decision 0030: Config vs persisted state — two problems, two mechanisms

Status: `proposed`
Date: `2026-04-21`
Related: Decision 0029

## Context

The previously-planned `chumicro-settings` library (see prior `plans/next-up.md`) conflated two unrelated concerns:

- **Config** — read-only settings shipped with the thing (wifi creds, MQTT broker, pin map, feature flags, timing knobs).
- **Persisted state** — small mutable key-value storage that must survive reboot (boot counters, last-seen timestamps, provisioning tokens, retry counters).

Source-level research against the pinned CP 10.1.4 and MP 1.26.0 trees plus vendor docs showed that a unified "rich settings" library is not buildable across the three substrates:

- **CircuitPython `microcontroller.nvm`** — byte slab, no keys. Per-board sizes hardcoded in `mpconfigport.h`: ESP32 8 KB, RP2040/RP2350 4 KB, nRF52840 4–8 KB, SAMD51 8 KB, **SAMD21 256 B**. ESP32 write path erases-then-rewrites and is not byte-atomic (`ports/espressif/common-hal/nvm/ByteArray.c:59-104`); Nordic uses per-page buffer swap and is atomic within a page. Wear leveling is absent in the CP wrapper itself (ESP32 rides on ESP-IDF NVS under the hood, which is wear-leveled).
- **MicroPython `esp32.NVS`** — namespaced K-V but **i32 and blob only, no string type**; explicit `commit()` required; partition typically ~24 KB; wear-leveled by ESP-IDF.
- **MicroPython Pi Pico W (CYW43 / RP2040)** — no NVS at all; raw flash blockdev and LittleFS filesystem only; `btree` module exists but defaults OFF in `ports/rp2/mpconfigport.h`.
- **`settings.toml`** — parsed by CP only (zero matches in MP tree). Reusing it for app config collides with CP's own `CIRCUITPY_*` keys and would not work on MP at all.
- **Filesystem writes on CP** — `storage.remount("/", readonly=False)` raises `"Cannot remount path when visible via USB."` when USB MSC is active. On-device mutation from `code.py` is hostile without `storage.disable_usb_drive()` (CP 9+) or a boot.py GPIO-gated remount.

The substrates do not share semantics.  Any unified "rich settings" library either leaks the differences upward (defeating the point) or pretends they don't exist (breaking in bad ways on small NVM or during power loss).

## Decisions

### 1. App config is read-only, shipped with the thing

Every thing carries a `config.toml` (or `config.yml`).  The deployer merges workspace-level environment defaults, per-thing overrides, and secrets at deploy time into a single artifact baked onto the device.  User code reads it once at boot.  Mutating app config requires a redeploy.

Layout:

```
things/back-porch/
  app.py
  config.toml              # thing-level defaults, checked in
things/back-porch/_generated/
  runtime_config.msgpack   # emitted by deployer, not checked in, deployed to device
```

### 2. Host format is TOML (default); device format is msgpack (default)

TOML on host because the workspace template's config shape is predominantly flat key=value, TOML parses via Python stdlib `tomllib` (zero host-side deps), and it is human-editable.  YAML is accepted opt-in for users who want richer structure.

msgpack on device because it is compact (important on 256 B–8 KB constrained devices), binary (mild obscurity against casual drive-browsing of CP's USB drive), already shipped by `chumicro-msgpack` across all three runtimes, and requires no additional parser.  JSON is accepted opt-in for users who want plaintext on-device.

Transform happens once at deploy time.  Device never parses TOML or YAML.

**Rejected:**

- **TOML all the way to device.**  No `tomllib` on CP or MP (CP has a subset parser bound to `settings.toml`, not general use).  Would need to ship a pure-Python TOML parser to the device — wasted flash + RAM for no gain.
- **YAML all the way to device.**  Pure-Python YAML parsers weigh ~20 KB; even worse cost than TOML for the same non-gain.
- **JSON all the way to device.**  Defensible, kept as opt-in.  Default is msgpack because it beats JSON on size by 30–50 % with identical capability via `chumicro-msgpack`.

### 3. Never reuse `settings.toml` for app config

`settings.toml` is reserved for CP's own `CIRCUITPY_*` environment keys the firmware cares about.  App config lives in the thing's `config.toml` (separate file), deployed to `/runtime_config.msgpack`.  The workspace template ships a `settings.toml` free of wifi keys (see Decision 0029, wifi ownership stance) and documents this in the template's `AGENTS.md`.

**Rejected:** mix app keys with CP keys in `settings.toml`.  CP-only, footgun-prone collisions, fails on MP.

### 4. Wifi credentials never in a KV store

Wifi creds live in the config pipeline above, not in any persisted-state store.  Credentials rotate at redeploy, travel with the secrets pipeline (workspace `secrets.yml` gitignored + env merge), and never touch NVM / NVS / filesystem as mutable values.

**Rejected:** storing creds in NVM for "first-boot provisioning."  Makes the workspace-level secrets pipeline redundant, creates a second source of truth, and strands creds on hardware that outlives the project.

### 5. Persisted runtime state gets a separate library — `chumicro-kvstore`

The library previously named `chumicro-settings` is renamed and rescoped.  `chumicro-kvstore` is a tiny mutable KV for state that must survive reboot — counters, timestamps, tokens, retry budgets.  It is explicitly **not** a config system.  Its documented contract includes size limits (as small as 256 B on SAMD21), wear caveats, and a recommendation not to store anything a user would edit by hand.

Per-runtime backends:

| Runtime / Board | Backend | Capacity | Atomicity | Wear |
|---|---|---|---|---|
| CP ESP32 | `microcontroller.nvm` → msgpack blob + CRC | 8 KB | erase-rewrite (power-loss risk) | ESP-IDF NVS under the hood |
| CP RP2040 / RP2350 | `microcontroller.nvm` → msgpack blob + CRC | 4 KB | raw flash | none; library caps writes |
| CP SAMD21 | `microcontroller.nvm` | **256 B** | raw flash | none; library caps writes |
| CP nRF52840 / SAMD51 | `microcontroller.nvm` | 4–8 KB | per-page atomic (nRF) / raw (SAMD) | none in wrapper |
| MP ESP32 | `esp32.NVS` namespace, one `set_blob` per key (msgpack value) | ~24 KB | commit atomic | wear-leveled |
| MP Pi Pico W | single LittleFS file `/_chu_kv.msgpack`, tmpfile+rename | filesystem-bounded | rename-based | LittleFS wear-aware |
| CPython | dict + optional JSON file | unbounded | trivial | n/a |

API (draft):

```python
from chumicro_kvstore import KVStore, KVStoreFull, KVStoreCorrupt

store = KVStore(backend="auto")          # per-runtime selection; override available
store["boot_count"] = store.get("boot_count", 0) + 1
store["last_seen_ms"] = now_ms
store.commit()                           # flush to NVM / NVS / LittleFS / dict

store.capacity                           # bytes available on this backend
store.bytes_used                         # current payload size
store.is_corrupt                         # True if last load failed CRC; store resets to empty
store.commit_if_changed()                # no-op when payload unchanged (wear mitigation)
```

Key constraints the library enforces:

- `commit_if_changed()` skips writes when encoded payload is identical to last persisted — first-line wear defense on CP NVM.
- `KVStoreFull` raised before a write that would exceed `capacity`.
- CRC header on CP NVM paths detects power-loss corruption; `is_corrupt` surfaces the event, store resets to empty.
- Values are round-tripped via `chumicro-msgpack` — strings, ints, bytes, lists, dicts all work; no i32-only restriction surfaces to the user.
- Explicit size limits per backend are exported as class constants so tests and user code can guard accordingly.

Detailed API, backend contracts, and corruption semantics will land in a follow-on decision when the library is built.  This ADR scopes the split; implementation lives in `plans/workstreams/project-workspace.md` Phase 3b.

## Consequences

- `plans/next-up.md`: the old `chumicro-settings` multi-bullet entry is replaced with a narrower `chumicro-kvstore` entry plus a note that app config does not need a library.
- `plans/workstreams/project-workspace.md` Phase 3b: rewritten around `chumicro-kvstore` + the TOML→msgpack config pipeline.  The config pipeline is primarily `chumicro-workspace-runtime` work (deployer transform) and does not land a new library.
- Template `AGENTS.md`: documents "do not store wifi creds in the KV store" and "do not reuse settings.toml for app config."
- The CI grep gate from Decision 0029 §8 (deploy package source cannot mention `workspace.yml`, `things/`, `library_sources:`) is unaffected — `chumicro-kvstore` is independent of that package too.
- Four device-verification items carry into Phase 3b: exact `len(microcontroller.nvm)` on ESP32-S3 and Pico W CP; NVS commit-survives-hard-reset on MP ESP32; write latency across CP NVM vs MP NVS vs MP Pico W LittleFS for a 512 B blob.
