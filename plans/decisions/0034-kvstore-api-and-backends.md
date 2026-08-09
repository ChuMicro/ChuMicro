# Decision 0034: `chumicro-kvstore` API and backend contracts

Status: `accepted`
Date: `2026-04-25`
Summary: `KVStore` selects backend by runtime (CP NVM / MP NVS / MP LittleFS / Memory); CP NVM frames as `MAGIC|LEN|CRC32|MSGPACK`; explicit `commit` lifecycle (no per-setitem write).
Related: Decision 0030 (config vs persisted state), Decision 0010 (constructor injection + `testing.py`), Decision 0021 (annotations), Decision 0014 (tick-based runner).

## Context

Decision 0030 split the old `chumicro-settings` scope into read-only app
**config** (deploy-time TOML→msgpack pipeline, owned by
`chumicro-workspace` in Phase 4a) and mutable **persisted
state** (a new library `chumicro-kvstore`, Phase 3b).  That ADR
sketched the API and the per-runtime backend table but explicitly
deferred the detail: *"Detailed API, backend contracts, and corruption
semantics will land in a follow-on decision when the library is
built."*  This ADR is that follow-on.

Source-level research from 0030 fixed the substrate constraints:

- `microcontroller.nvm` is a byte slab with **no keys** (CP).  Per-board
  capacities range from 256 B (SAMD21) to 8 KB (ESP32 / SAMD51).  No
  wear-leveling in the wrapper itself; ESP32 rides ESP-IDF NVS
  underneath, others are raw flash.
- `esp32.NVS` is namespaced K-V but **i32 + blob only, no string type**;
  explicit `commit()` required (MP ESP32, ~24 KB).
- Pi Pico W MP has **no NVS** — only raw flash + LittleFS; `btree`
  defaults OFF in `mpconfigport.h`.
- CPython has none of these — fake backend only.

The library has to hide every one of those substrate differences
behind one uniform API while staying honest about the constraints
(capacities, atomicity, wear) so callers can reason about what their
state actually does on hardware.

## Decisions

### 1. Single class, backend selected per-runtime

```python
from chumicro_kvstore import KVStore, KVStoreFull, KVStoreCorrupt

store = KVStore(backend="auto")        # default — see §2
store = KVStore(backend="memory")      # explicit override
store = KVStore(backend="nvm")         # CP-only; raises on MP/CPython
store = KVStore(backend="nvs")         # MP-ESP32-only
store = KVStore(backend="littlefs")    # MP-non-NVS-only
```

`KVStore` is the single public entrypoint.  Per-runtime backends live
under `chumicro_kvstore._backends/` and are selected at construction —
**not** as a separate import path the caller has to know.  This mirrors
`chumicro-msgpack`'s "one library, runtime-aware delegate" shape so
calling code is identical across CP, MP, and CPython.

### 2. Auto-detect uses `sys.implementation.name` + capability probe

```python
def _select_backend() -> Backend:
    name = sys.implementation.name
    if name == "circuitpython":
        return CpNvmBackend()              # every CP build has microcontroller.nvm
    if name == "micropython":
        try:
            import esp32                    # noqa: F401
            return MpNvsBackend()           # ESP32 path
        except ImportError:
            return MpLittlefsBackend()      # everything else (RP2, nRF, …)
    return MemoryBackend()                  # CPython
```

CP always has `microcontroller.nvm`; even the SAMD21 256-B variant
exposes the API.  MP-ESP32 detection is via `import esp32` rather than
board-name parsing — works for every ESP32 variant ESP-IDF supports
without an enumeration to maintain.

**Auto-detect is a default, not a constraint.**  The substrate
choice on MP-ESP32 is genuinely "either NVS or LittleFS works"; the
auto path picks NVS because it has substrate-level wear leveling
guarantees and is the obvious match for ESP32 boards, but a caller
with a reason to prefer file-based storage on the same board can
pass `backend="littlefs"` and the LittleFS backend will use the
mounted filesystem regardless of whether `esp32.NVS` is also
available.  Auto-detect optimizes for the common case; the explicit
strings exist so users aren't locked in.

### 3. Mapping-shaped API, plus three explicit lifecycle methods

`KVStore` implements the full `MutableMapping` surface (`__getitem__` / `__setitem__` / `__delitem__` / `__contains__` / `__iter__` / `__len__` / `get` / `keys` / `items` / `values` / `pop` / `clear` / `update`).  Excludes `setdefault` (footgun on backends with side-effecting writes) and `popitem` (no defined order; would imply one).  Full method reference lives in `libraries/kvstore/docs/`.

The three lifecycle methods are explicit because flash writes are too expensive to do per-`__setitem__`:

- `commit()` — encode in-memory dict, write to backend, fsync.  Raises `KVStoreFull` if encoded size exceeds capacity.
- `commit_if_changed()` — compare encoded payload against last successfully-persisted bytes; skip the write if identical.  First-line wear defense on raw-flash backends.
- `reload()` — discard in-memory state and reread.  Surfaces `is_corrupt=True` if the reread fails the CRC check.

### 4. Properties expose the constraints honestly

`store.capacity`, `store.bytes_used`, `store.is_corrupt`, `store.backend_name` — all read-only.  `capacity` is set per-backend at construction (`len(microcontroller.nvm) - HEADER_SIZE` for CP NVM; a fixed 16 KB default for LittleFS, overridable via `capacity=`; unbounded for memory).  `is_corrupt` is sticky for one session and clears on the next successful `commit()` — so the app can log the event without losing the ability to keep running on a fresh empty state.

### 5. CP NVM payload framing: `MAGIC | LEN | CRC32 | MSGPACK`

The CP NVM backends (ESP32, RP2040, SAMD51, SAMD21, nRF52840) write a
single contiguous header + payload into the byte slab:

```
offset 0:  4 bytes — MAGIC b"CKVS"
offset 4:  2 bytes — LEN (little-endian uint16, payload bytes 0..65535)
offset 6:  4 bytes — CRC32 (little-endian uint32, IEEE polynomial, over MSGPACK only)
offset 10: LEN bytes — MSGPACK encoded dict payload
```

Total header = 10 bytes.  `capacity = len(nvm) - 10`.  For the SAMD21
case (256 B NVM total) that leaves **246 B** of payload — small but
documented and enforced.

CRC32 is the IEEE polynomial (`0xEDB88320` reversed) — same as
`zlib.crc32`, available in CP via `binascii.crc32` and in MP via
`binascii.crc32`.  Pure-Python fallback ships with the library for
any environment without `binascii`.

Read path: read 10-byte header, validate MAGIC, validate LEN ≤
capacity, read LEN payload bytes, verify CRC.  Any check failing →
`is_corrupt = True`, store resets to empty in-memory, `commit()` then
overwrites the corrupt slab cleanly.

MAGIC distinguishes "blank flash" from "corrupted write" — without it, a freshly-initialized slab (all `0xFF` or `0x00`) computes a CRC over random bytes and reports a corruption event on every first boot.  uint16 LEN saves 2 bytes vs uint32; the library raises at construction if a future backend exposes >64 KB of NVM.

### 6. MP NVS encoding: single payload blob under a fixed key

```python
import esp32
nvs = esp32.NVS("chu_kv")
nvs.set_blob("payload", msgpack.packb(dict_))
nvs.commit()
```

`esp32.NVS` is already wear-leveled and atomic-on-commit, so the
library does not add CRC framing.  The whole encoded dict ships as
one msgpack blob under the fixed NVS key `"payload"`.

NVS namespace is fixed at `"chu_kv"`.  Co-existing apps using their
own NVS namespaces are unaffected.

**Why single-blob-not-per-key:** the MicroPython `esp32.NVS` wrapper does not expose ESP-IDF's `nvs_entry_find` iterator, so per-key blobs would need a manifest to rebuild the dict on load — extra read + write per commit for marginal wear-leveling gain (NVS already wear-levels at the partition level).  Single payload mirrors the CP NVM shape and lets `KVStore` own the msgpack codec uniformly.  `get_blob` requires a pre-allocated buffer ≥ stored value size; the library allocates `bytearray(self.capacity)` once at load time.

### 7. MP LittleFS encoding: tmpfile + rename, single file per store

(Pickable on **any** MP build with a writable filesystem — not just
non-NVS boards.  Auto-detect routes ESP32 to NVS by default; users
can opt back to LittleFS via `backend="littlefs"` for portability
or to share storage with other on-device files.)

```python
PATH = "/_chu_kv.msgpack"
TMP  = "/_chu_kv.msgpack.tmp"

def commit(payload: bytes) -> None:
    with open(TMP, "wb") as tmp:
        tmp.write(payload)
        os.sync()                # flush to flash before rename
    os.rename(TMP, PATH)         # atomic on LittleFS
```

LittleFS guarantees atomic rename across power-loss; the file is
either old-content or new-content, never partial.  No CRC needed —
LittleFS itself wear-levels and detects block corruption.

Path is fixed at `/_chu_kv.msgpack` (leading underscore so listing-
sorted file managers don't surface it as the user's first file).
Co-existing apps using their own filesystem files are unaffected.

### 8. Memory backend — CPython default + `FakeKVStore` substrate

```python
class MemoryBackend:
    capacity = sys.maxsize
    def __init__(self, initial: dict | None = None) -> None: ...
    def load(self) -> dict: ...
    def save(self, payload: bytes) -> None: ...
```

Used as the CPython auto-detect default and as the substrate for the
`FakeKVStore` test fixture (Decision 0010 — every library's `testing.py`
ships a fake the downstream tests can use).  `FakeKVStore` adds
explicit corruption injection (`fake.corrupt()`) and capacity overrides
(`fake.set_capacity(256)`) so downstream tests can exercise small-NVM
edge cases without having a SAMD21 plugged in.

### 9. Exception hierarchy

```python
class KVStoreError(Exception): ...
class KVStoreFull(KVStoreError): ...
class KVStoreCorrupt(KVStoreError): ...
```

`KVStoreError` is the base.  Catch it to handle every kvstore-specific
failure uniformly.  Catch `KVStoreFull` or `KVStoreCorrupt` for the
specific recoveries — typically state-reset or logging.

The CP backend writes to `microcontroller.nvm` rather than the FAT
filesystem, so it is unaffected by the USB-MSC read-only window.  No
"backend refused the write" exception is part of the current surface;
if a filesystem-backed CP backend lands later, a `KVStoreReadOnly`-
shaped class can be added then alongside it.

### 10. Values round-trip via `chumicro-msgpack`

`KVStore` uses `chumicro_msgpack` for all encoding — no per-backend serialization.  Supported types: `int`, `bool`, `float`, `str`, `bytes`, `list`/`tuple` (decoded back as `list`), `dict` (str keys only), `None`.  Cycles raise `TypeError` from msgpack's encoder.

## Consequences

- Public surface is `KVStore` + four exceptions + `FakeKVStore`.  Per-
  backend classes stay under `_backends/` (single underscore prefix per
  workspace convention) and are not part of the API contract — rewrites
  inside a backend don't bump the major version.
- `chumicro-kvstore` lives under `libraries/kvstore/` and ships to PyPI
  + the bundle.  `[tool.chumicro].platforms = ["cpython", "micropython",
  "circuitpython"]` (default; no override needed).
- Cross-runtime tests under `tests/` exercise the public contract via
  `MemoryBackend` only.  Per-backend hardware tests live under
  `functional_tests/` and are gated on board availability through the
  existing `devices.yml` plumbing.
- Capacity numbers in the §1 / §2 tables are confirmed against pinned
  CP 10.1.4 source per Decision 0030.  When CP raises NVM sizes (next
  major release will add SAMD51 8 KB hardening, per upstream PRs), the
  library picks them up automatically — `capacity` is computed from
  `len(microcontroller.nvm)` at construction, not hardcoded.
