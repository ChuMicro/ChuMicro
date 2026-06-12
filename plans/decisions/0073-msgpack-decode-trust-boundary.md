# Decision 0073: msgpack decode trust boundary

Status: `accepted`
Date: `2026-05-17`
Summary: `chumicro_msgpack.unpackb` is a trusting decoder hardened against truncation, over-length, trailing-garbage, and unbounded recursion; CRC framing stays per-substrate per Decision 0034.
Related: [Decision 0009](0009-per-library-test-runs.md), [Decision 0034](0034-kvstore-api-and-backends.md)

## Context

A 2026-05-16 adversarial audit (4 independent agents + hand-verified)
found `chumicro_msgpack.unpackb` silently accepts truncated,
over-length, and trailing-garbage input and recurses unbounded:
`unpackb(b'\xc4\xc8\x01\x02')` claims a 200-byte string and returns the
2 available bytes; `unpackb(b'\x01\xff\xff\xff')` returns `1` and drops 3
trailing bytes. `chumicro-kvstore` (`core.py:157,178`) and
`chumicro-config` (`runtime.py:22`) feed *persisted flash bytes*
straight into `unpackb`, so a power-loss-truncated payload decodes as a
structurally-valid *wrong* dict, is adopted as live state, and
overwrites the original on the next commit.

The open question this resolves: is `unpackb` contractually a
*validating* decoder or a *trusting* one, and must every kvstore
persistence backend carry CRC framing? The embedded-cost gate applies —
`libraries/msgpack/src/` runs on 256 KB-RAM / 2 MB-flash (~800 KB usable) boards, and
the realistic threat is power-loss flash corruption on a *raw-flash*
backend, not a network attacker (most chumicro devices are LAN/leaf
nodes; the genuinely exposed surface is `http_server` / `websockets`).

## Decision

### 1. `unpackb` is a *trusting* decoder, hardened against malformed framing

`chumicro_msgpack.unpackb` is contractually a **trusting** decoder, not
a spec validator. It is made safe against the three malformed-framing
classes the audit found, with ~15–20 lines and no per-decode hot-path
allocation:

- **length-vs-remaining check** at every length-prefixed read (str /
  bin / array / map / ext headers) — a claimed length exceeding the
  bytes remaining raises `ValueError`, never returns a short result;
- **recursion-depth counter** (a plain int threaded through the
  recursive core) — bounded nesting raises `ValueError` rather than
  exhausting the C stack / heap;
- **reject-trailing-bytes** in `unpackb` **top-level only** (not in the
  recursive core, which legitimately stops mid-buffer) — bytes left
  after one complete object raises `ValueError`.

What it is explicitly **not**: a per-type spec validator (~100 lines +
per-decode CPU). Type-correctness of a structurally-valid payload is
the caller's contract, not the decoder's. This is the documented
residual.

### 2. CRC framing stays per-substrate — Decision 0034's model is correct

The audit's proposed *"every kvstore persistence backend MUST carry CRC
framing"* is **not adopted**. Decision 0034 §5–§7 already decided
integrity per substrate, and that reasoning stands:

- **CP NVM** (`_backends/cp_nvm.py`) — raw, non-atomic flash slab;
  carries `MAGIC | LEN | CRC32 | MSGPACK` framing (0034 §5). Already
  implemented. This is the one backend where a torn write is physically
  possible, and it is the one backend with a CRC.
- **MP NVS** — `esp32.NVS` is wear-leveled and atomic-on-commit (0034
  §6); a partial blob is not observable.
- **MP LittleFS** — tmpfile + `os.sync()` + atomic `os.rename()` (0034
  §7); the file is old-content or new-content, never partial.
- **memory** — no persistence; nothing to corrupt across power loss.

The decoder bounds in §1 close the *decode-garbage-as-valid* failure
at the codec layer on **every** backend — including memory, which CRC
framing could never protect. Mandating CRC on NVS / LittleFS would add
flash and a per-commit CRC for a torn-write threat the substrate
already closes, and would contradict 0034's deliberate per-substrate
analysis. Pushing the cheap, universal fix to the codec layer is both
cheaper and *more* correct than a CRC-everywhere mandate.

## Consequences

- Phase 1 item 1 of the `audit-remediation-and-drift-mechanization`
  workstream narrows to the §1 decoder hardening only. The "require CRC
  on every backend" sub-task is dropped — 0034's model is confirmed,
  not amended; no `_backends/` change.
- `chumicro_msgpack` gains a documented contract: trusting decoder,
  safe against truncation / over-length / trailing-garbage / unbounded
  recursion, **not** a type-spec validator. Callers persisting
  attacker- or corruption-reachable bytes still own type-shape
  validation of a structurally-valid payload.
- `unpackb` raises `ValueError` (not a silent short read) on the three
  malformed-framing classes. Any caller previously relying on the
  silent-truncation behaviour now gets an exception — correct, since
  that behaviour was the defect.
- The residual is stated in the library's own docs/guide and the
  `unpackb` docstring, not only here — a cold reader of the API must
  see "trusting, not validating" without reading this ADR.
