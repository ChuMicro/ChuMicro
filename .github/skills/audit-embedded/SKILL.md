---
name: audit-embedded
description: Embedded-systems audit of a single device library — flash footprint, import-time RAM, hot-path allocations, heap fragmentation, runtime quirks on MicroPython and CircuitPython, and docs-vs-code drift.  Complements (does not replace) `/audit-library`.  Use when a library is bound for boards with 256 KB RAM / 2 MB physical / ~800 KB usable flash and you want a focused pass on whether it pulls its weight there.
---

# Embedded-library audit

Audit one device library (`libraries/<name>/`) through the **on-device lens**: does the code respect the realities of MicroPython and CircuitPython on a 256 KB-RAM / 2 MB-flash (~800 KB usable) microcontroller? Output a prioritized punch-list, then execute the high-confidence items with the user's go-ahead.

Argument: the library name (matches the folder under `libraries/`). Example: `/audit-embedded mqtt`, `/audit-embedded wifi`, `/audit-embedded sockets`.

## Primary lens for `libraries/`

For code under `libraries/`, this is the **primary** audit lens — `/audit-library`, `/audit-code`, and `/audit-branch` defer to it here rather than merely complementing it. Embedded cost (flash bytes, import-time RAM, hot-path allocations, class / def / exception count, string-constant weight) outranks the standards lenses — docstring completeness, defensive guards, rich error prose, well-formedness — on this tree. A standards finding that *adds* code to a device library must justify its bytes or drop to advisory. Standards stay primary everywhere else: `scripts/`, `workbench/`, `.claude/surfaces/`, and the skills themselves.

**Calibration — measured 2026-07-05 baseline (Pi Pico W).** Importing the whole fleet costs ~142 KB of MicroPython heap — about 72 % of a Pico W's usable heap gone before any application code runs. The heavy trio (requests, websockets, mqtt) accounts for ~80 KB of that; `chumicro_mqtt` alone imports at ~9× a stripped `umqtt.simple`. Audit-driven standards adherence has been inflating device code — well formed, but size abounds. Score every device-library finding against these numbers. The cut campaign that tracks the work is [`plans/workstreams/library-size-cut.md`](../../../plans/workstreams/library-size-cut.md).

## Scope

Device libraries only. `workbench/<name>/` is host-only CPython — none of these dimensions apply there. `support/test_harness/` is borderline (it does run on devices); if you point this skill at it, only the device-side modules count.

A library's `tests/` are out of this skill's footprint scope (they don't ship), but the on-device unit sweep does run them: a very large class-organized test module that `MemoryError`s on a 256 KB board is a [Decision 0072](../../../plans/decisions/0072-large-test-modules-on-constrained-boards.md) reactive split (tracked via [device-testing.md](../../../docs/contributing/device-testing.md#large-test-modules-on-a-256-kb-board)), not a `src/` footprint finding — flag-and-file it, don't fold it into this pass.

**The named scope is the only scope.** Observations outside the named library — even adjacent fixes that look obvious — file as a new `## Next` entry in `plans/next-up.md` and stop there. Don't fold them into the audit's commits. Out-of-scope diffs that ride along are the leading cause of revert traffic on audit work.

Inside a device library, `src/<name>/testing.py` (and any other file marked `__chumicro_runtimes__ = ("cpython",)`) **is in scope**: even though those files never deploy to a board, they're imported by cross-runtime test files at runtime on MicroPython and CircuitPython unix ports. So the same parse-time / import-time rules apply — no `from __future__`, no `from typing import …`, no leading-underscore `const()` imports from siblings. The flash / cluster cost dimensions don't apply (the file doesn't ship to a device), but the runtime-correctness dimensions do.

This skill runs **orthogonally to `/audit-library`** — they look for different things and both can be useful on the same library at different times — but on `libraries/` code the embedded lens leads and `/audit-library`'s standards findings defer to it (see "Primary lens for `libraries/`" above).

| Skill | Lens | Cares about |
|-------|------|-------------|
| `/audit-library` | Reader / maintainer | Honesty, dead code, method shape, duplication, top-to-bottom readability, peer-LOC outliers |
| `/audit-embedded` | The board running the code | Flash bytes, import-time RAM, hot-path allocation, fragmentation, runtime branches, `const()` / `memoryview` / `__slots__` reality, FAT overhead, doc-vs-code drift |

Tag a finding `cross-skill` and escalate when it really belongs in the other audit.

**Running both on the same library:** one at a time, never in parallel — they both write to `src/`, so concurrent passes would clobber each other. Default order is **`/audit-library` first**, then `/audit-embedded`. The general pass shrinks the surface (dead code, single-use helpers, cargo-cult methods, duplication), which makes the embedded pass cleaner — less code to grep for hot-path allocations, lazy-import candidates, and FAT-cluster math. The reverse works but produces more churn: if `/audit-embedded` consolidates files first, `/audit-library` then re-evaluates duplication against the merged shape. You don't have to run both on every library — pick based on what the library has accumulated since its last audit.

## Audit philosophy

Minimum board class is 256 KB MCU RAM + 2 MB physical / ~800 KB usable flash ([Decision 0015](../../../plans/decisions/0015-board-architecture-support.md)). Everything below follows from that:

* **Less code is better than more code.** Flash is a hard cap and `.py` source is what ships in practice (most users install via `mip` / `circup` against the `.py` side of the bundle; `.mpy` adoption is limited by bytecode-version bugs and runtime mismatches). Class explosion and helper-bucket modules cost flash bytes, FAT cluster waste, and parse-time RAM. Form is good; size is the constraint. Don't add abstractions without a caller demanding them.
* **The heap fragments under the kind of work libraries do.** Long-lived state interleaved with short-lived buffers leaves the small-block tier full of holes. A 100-byte allocation can fail with 20 KB free if every free slot is 40 bytes. Reserve buffers up front; reuse them; pass `memoryview` slices instead of copies. See [`plans/patterns.md` "Static recv buffer + memoryview window"](../../../plans/patterns.md).
* **CPython habits leak.** `from typing import Optional`, `from __future__ import annotations`, `dataclasses.dataclass`, f-strings inside hot loops — all benign on a laptop, all costly or broken on-device. Pyright suggestions that improve a host program may regress a library.  (Eager top-of-file imports are NOT in this list — eager is the right default on-device, see §2 / §4 / §6.)
* **The code is the source of truth.** When docs or docstrings disagree with the code, the code wins by default — but ask the user when ambiguous (the doc may encode the original intent).
* **CPU matters less than memory.** A 250 MHz dual-core RP2350 is plenty for scripted networking work *unless* a tight loop allocates per iteration. Then the GC pause dominates. The audit cares about allocation-per-tick more than raw cycles.

## Audit dimensions

Run through each. Note findings as a punch-list with `file:line` + one-line description + dimension tag. Tag taxonomy is listed in **Output format** at the bottom.

### 1. Flash footprint — every byte ships

Source files land on a small FAT filesystem; `.py` is what most installs pull. Less surface = less flash, less parse-time RAM, less bytecode.

* **Speculative classes.** A class with one instance, no subclasses, and 4-5 small methods is often a module with extra ceremony. If callers only need 2-3 functions, propose the dataclass-and-namespace shape (module-level state if there's truly one instance, or top-level functions if state can be parameter-passed).
* **Excess `__init__.py` content.** Re-export-only `__init__.py` files are the convention; an `__init__.py` over ~100 lines doing real work hides the actual modules from grep and inflates the always-loaded top of the package. Compare across the repo: `wc -l libraries/*/src/chumicro_*/__init__.py` (most sit at 11–100 lines).  Any package whose `__init__.py` runs several hundred lines above the cohort median is a candidate for splitting its real work into named submodules — flag and propose the split shape.
* **Many small files.** CIRCUITPY's FAT filesystem rounds every file up to the cluster size (typically 512 B or 1024 B; verify with `os.statvfs("/")` from REPL). Five tiny modules at 200 B each cost ~2.5 KB of cluster waste on top of the 1 KB of source. The `chumicro_mqtt._wire` module's own header documents the historical merge ("shipping them as four files cost ~16 KB of FAT cluster waste on Pi Pico W") — that's the reference precedent. **Threshold:** if the library has 4+ modules each under ~1 KB of real code and the dependency graph between them is tight (one calls the next which calls the next), propose consolidation.
* **Long docstrings and comments — advisory only since Decision 0090.** The deploy pipeline strips docstrings and comments from every staged `.py` (measured 2026-07-05: strip removes 58 % of fleet source), so doc prose costs the sdist and the unstripped test lanes, **not** device flash or import heap. Do not rank doc-trim findings above structural ones — the bytes that reach a board come from classes, defs, exception types, string *constants* (f-string error prose does NOT strip), and file count. The density-triage snippets in field-reality stay useful only for unstripped-test-lane heap pressure.
* **Cargo-cult class methods (peer-LOC trigger).** Same check as `/audit-library §8` — flag here when the method-set is wider than this library's own callers need *and* the un-called methods drop flash if removed.
* **Wrapper-doubling / prefix-sugar method pairs.** Two methods with the same signature whose bodies differ by one call (a prefix resolver, a normalizer, a default-applier).  Examples: `publish(topic, ...)` + `publish_raw(topic, ...)` where `publish` is `publish_raw(self._prefixed_topic(topic), ...)` and the rest is identical; `read(key)` + `read_raw(key)` where the only delta is a key transform; `send_event(name, payload)` + `send_event_unencoded(name, payload)`.  Each pair is N additional lines of duplicated body + duplicated docstring + an extra class-dict entry on every instance.  Cargo-cult-methods catches *unused* methods; this catches *used-but-redundant* methods — both are flash and import-time RAM, but the redundant-pair pattern doesn't trip a peer-LOC outlier check because each method has its own callers.  Default fix: collapse to one method with a binary kwarg (`prefixed=True`, `normalize=False`, `encoded=True`) — same shape `set_will(..., prefixed=False)` already uses in `chumicro_mqtt.client`.  Audit move: grep for `def \w+_raw(` / `def \w+_unencoded(` / `def \w+_unprefixed(` / `def raw_\w+(`; for every match, diff the body against the unsuffixed sibling — if the delta is a single helper call or a single conditional branch, it's a wrapper-doubling candidate.  See [field-reality → publish / publish_raw wrapper-doubling](field-reality.md#publish--publish_raw-wrapper-doubling).

  **When NOT to collapse.** The structural match is real but collapse isn't always the right move.  Three exception classes surfaced by the 2026-05-23 workspace re-pass:
    1. **PyPI-library convention.** `requests.get(url)` vs `request("GET", url)`; `msgpack.pack` + `packb`.  The verb-named methods are the API contract callers reach for; collapse trades ergonomics for one qstr in flash.  Flag for awareness; leave.
    2. **Positional / kwarg asymmetry.** `runner.add_periodic(handler, 500)` reads cleaner than `runner.add(handler=handler, period_ms=500)` because `add()`'s first positional slot is `task`.  When collapse forces every caller to switch to kwarg syntax across 20+ call sites, the call-site noise outweighs the one class-dict slot saved.  Flag for awareness; leave.
    3. **Caller-unused query helper.** When the "lighter" method has no real external callers (only the wrapper uses it internally), privatize as `_name` instead of inventing an `advance=True/False` kwarg nobody asked for.  Smaller diff, smaller public API.  Example: `Heartbeat.is_due` → `_is_due` (every real caller used `.poll()`).

  See [field-reality → wrapper-doubling workspace re-pass](field-reality.md#wrapper-doubling-workspace-re-pass) for the full sweep findings.

### 2. RAM at import time — module top-level work

"Executing this code [module top level] creates objects in the MicroPython heap … these allocations constitute the RAM cost of loading a module" ([MicroPython constrained-runtime docs](https://docs.micropython.org/en/latest/reference/constrained.html)).

* **Top-level `import` of heavy modules — default eager.** Module-top imports load long-lived state contiguously into the heap before any short-lived buffer churn starts; deferring them to function scope means the deferred state lands later, in fragmentation holes the early churn left behind.  Lazy is justified only when the symbol's path is **genuinely optional** — DI / factory fallbacks where the caller usually injects an alternative, error-format helpers reached only on the failure branch, firmware-update paths that fire once a year, runtime-specific branches the current runtime never hits.  "Cold path called once at boot" does NOT qualify — the deferred-to point sits microseconds after deferred-from and peak RAM is unchanged; you've paid fragmentation cost for a saving that doesn't exist in practice.  Don't lazy-import primitives used on every tick (`struct`, `time`) either — per-call dict lookup costs more than the load.  See [`plans/patterns.md` § "Eager imports are the default"](../../../plans/patterns.md).
* **Top-level computed dicts / list literals / `.encode()` chains.** A `STATUS_MAP = {0: "OK", 1: "...", ...}` allocates the dict at import. If used in one cold path, push into the function. If used in a hot path, keep at module level.
* **Module-level eager hardware init.** `import board, busio` + `_DEFAULT_I2C = busio.I2C(...)` at module top instantiates hardware on import. Banned by [Decision 0010](../../../plans/decisions/0010-library-testability.md); flag if present.
* **Speculative pre-allocation at module top.** A 4 KB module-level scratch buffer that's used by exactly one rarely-called function pins RAM forever. Move into the function or into the consuming class's `__init__`.
* **Public default-kwarg values that drive `__init__`-time heap allocation.** `MpNvsBackend(capacity=DEFAULT_CAPACITY)` looks like a sizing knob, but if `__init__` does `self._buf = bytearray(self.capacity)`, the default value is the long-lived RAM cost every instance pays. Audit the default against the *documented* use case (boot counters, short tokens, etc.), not against the maximum-supported workload.  See [field-reality → kvstore MP-NVS default sizing](field-reality.md#kvstore-mp-nvs-default-sizing).
* **Asymmetric workloads → asymmetric defaults.** When a library has two paths that allocate independently — RX and TX on a network client, server-side vs client-side on a transport, read-buffer vs write-buffer on a persistence layer — the right default for each side comes from its *own* usage profile, not from a unified "library footprint" target.  The two paths can be symmetric in code shape but asymmetric in workload: a subscriber receives broker fan-out + retained-message replay + N concurrent subscribed-topic bursts (RX is noisy → 256 B-class buffer right-sized), while the same client publishes once every N seconds (TX queue stays near zero → 20-slot cap plenty).  When auditing defaults, name each path's documented profile separately before deciding numbers.  See [field-reality → asymmetric tx / rx defaults](field-reality.md#asymmetric-tx--rx-defaults--chumicro_mqtt).

### 3. Heap allocation in hot paths — the most common defect

Hot paths are: any `runner.tick()` callback, any `check(now_ms)` / `handle(now_ms)`, any inner loop in a decoder / parser / state machine, any per-message / per-frame / per-byte processing.

* **f-strings and `.format()` inside hot loops.** Every f-string allocates a new `str`. `log.info(f"got {n} bytes")` inside `handle()` allocates per tick even when log level filters the message. Replace with `log.info("got %d bytes", n)` (logger interpolates only on emit) or guard with `if log.is_enabled(INFO):`.
* **`dict(...)` / `{...}` / `[...]` literal inside a hot loop.** Reuse a module-level constant or a cleared scratch container.
* **`bytes(memoryview_slice)` to satisfy an API.** Forces a copy and defeats the point of holding the memoryview. Inspect the consumer — does it really need `bytes`, or does `unpack_from(fmt, buf, off)` / passing `memoryview` work?
* **`bytes(view).decode("utf-8")` → `str(view, "utf-8")` for utf-8 decode.** The 3-arg `str()` constructor accepts any bytes-like (including memoryview) and skips the intermediate `bytes` copy that `bytes(view).decode(...)` allocates.  See [field-reality → `str(view, "utf-8")` allocation savings](field-reality.md#strview-utf-8-allocation-savings) for bench numbers and the integration-scope multiplier.
* **`buffer.extend(struct.pack(fmt, value))` → `_append_packed` helper.**  `struct.pack` allocates a fresh `bytes` per call that's copied into the destination and freed; `pack_into` writes directly into a pre-extended bytearray slice.  Established hot-path pattern for new code — flag divergence in existing libraries rather than rewriting mid-pass.  See [field-reality → `_append_packed` encoder pattern](field-reality.md#_append_packed-encoder-pattern) for the helper shape, the zero-byte literals trick, the existing-library convergence note, and bench numbers.
* **`struct.unpack(fmt, view[a:b])` on MicroPython.** Has historically been patchy ([micropython#8747](https://github.com/micropython/micropython/issues/8747)); current chumicro-supported builds accept it (mqtt's `_wire.py` uses the pattern in production). If a finding turns up an MP build that rejects it, `struct.unpack_from(fmt, buf, offset)` is the portable fallback — no slice memoryview construction, no allocation either.
* **`int.from_bytes(bytes(buffer[a:b]), "little")` — drop the `bytes()` wrapper.** `int.from_bytes` accepts any buffer-protocol object (bytearray slices, memoryviews, plain bytes) directly; the explicit `bytes()` cast adds one allocation per call for no semantic gain. Same shape as the `unpack_from` rule above, different consumer. Cold-path appearances are micro; hot-path appearances (per-frame header parsing) compound quickly.
* **Per-byte loops where per-chunk works.** Same check as `/audit-library §5`. MicroPython frame allocation per call is real; on a 1024-byte recv buffer, per-byte processing is 1024 frames per tick. Restructure to per-chunk consumption (`view[start:start + needed]`).
* **`self.x.y.z.method()` chains used >2× in a loop body.** Cache to a local: `cb = self._state.callbacks.on_publish` before the loop, then call `cb(...)`. [MicroPython speed_python](https://docs.micropython.org/en/latest/reference/speed_python.html) is explicit about this. **Exception:** runner-way submodule-on-self patterns established by `/audit-library` (e.g. `self._ticks.ticks_diff(...)` in a per-service `is_due` / `check` method that runs ~10× per tick) are accepted defaults — the per-call attribute-lookup cost is amortised against the readability and family-convergence wins. Re-flag only when the same chain runs per-byte or per-message inside a parser inner loop.
* **`gc.collect()` in library code is a smell.** Legitimate use is *between* major state changes (post-handshake, post-bulk-decode, post-`connect()`) where pre-emptive collection is cheaper than letting the next allocation trigger one. `gc.collect()` inside `tick()` or `handle()` indicates the real fix is pre-allocation. Flag any `gc.collect()` and ask: does this hide a pre-allocation bug?
* **Sender-controlled `bytearray(N)` / `bytes(N)` allocations — the heap-DoS vector.** Trace every allocation in inbound-parse code and ask "what's the maximum N this can take?"  When N comes from a peer-controlled field (MQTT remaining-length varlen, HTTP `Content-Length`, WebSocket frame length) and the allocation is unbounded, a hostile peer can request whatever heap you have.  Fix shapes: (a) bound N at the documented cap-knob (`max_message_bytes`, `max_body_bytes`) and refuse / drop above it; (b) reuse a pre-allocated steady-state buffer as a rolling sink and discard bytes as they drain.  Flag every match even when a nearby comment claims heap-safety.  See [field-reality → sender-controlled bytearray](field-reality.md#sender-controlled-bytearray--heap-dos).

### 4. Heap fragmentation prevention

Fragmentation manifests as "100 bytes won't fit even though 20 KB is free." The cure is structural — but the structural answer depends on the buffer's lifetime.

* **Long-lived stateful buffers** — recv buffers, parser accumulators, per-instance scratch space — should be constructed in `__init__` once and held for the object's lifetime, with cached memoryview windows for slicing. See [`patterns.md` "Static recv buffer + memoryview window"](../../../plans/patterns.md) and "_buf + cached _buf_view." Cross-check: every long-lived `bytearray` should have a sibling cached `memoryview` if it's sliced more than once.
* **A buffer earns long-lived status by call frequency, not by the word "reusable" in a comment.** A long-lived buffer pays off when it's touched many times per session or in a hot path; a buffer touched 1–2 times per object lifetime is transient masquerading as persistent — allocate it inside the call site and let GC reclaim.  When the audit sees a `_buf = bytearray(N)` in `__init__`, count actual touches per session before defending the long-lived shape.  See [field-reality → long-lived buffer that was actually transient](field-reality.md#long-lived-buffer-that-was-actually-transient).
* **Transient per-call buffers** — encoder output for `packb`-shaped functions, formatter accumulators, anything built once per call and immediately returned — DO NOT default to pre-allocate-and-position-track.  Don't pre-allocate transient buffers without bench-measuring against the capacity-doubling baseline first.  See [field-reality → pre-allocate-and-position-track regression](field-reality.md#pre-allocate-and-position-track-regression) for the bench numbers that flip the intuition.
* **`bytearray.extend` in a hot path on a long-lived buffer** — three allocations per call (alloc bigger, copy old, copy new, free old). Audit the use site: does a fixed buffer with slice-assign (`buf[a:b] = data`) and a write cursor work instead? (For transient per-call buffers, see the bullet above — extend is usually fine.)
* **Front-of-bytearray consumption** — `self._buffer = bytearray(self._buffer[N:])` churns the small-tier. Use the read-cursor pattern from `chumicro_requests._wire.ResponseParser._consume` instead. Flag if seen.
* **Per-iteration `bytearray(N)`** — the worst case. Reuse a steady-state buffer and only allocate fresh when the size genuinely exceeds capacity ([`patterns.md` "Reuse buffers; only allocate fresh"](../../../plans/patterns.md)).
* **String concatenation in a loop** — `result = result + chunk` allocates a new string each iteration. Use `"".join(parts)` after collecting into a list, or write into a pre-allocated bytearray.
* **Lazy-import fragmentation rule (default = eager).** Eager module-top imports load long-lived state contiguously before short-lived buffer churn fragments the heap; lazy imports land later, in the holes that churn leaves behind, and the deferred globals fragment apart from the rest of the library's long-lived state.  Lazy is justified only for **genuinely optional code paths** — DI / factory fallbacks where the caller usually injects, error-only helpers, runtime-specific branches the current runtime never hits, paths that fire once in a blue moon between actual hardware boots.  "Cold path called once at boot" does not qualify (deferred-to point too close to deferred-from to save anything), and "import-time RAM saving in a synthetic bench" does not qualify either (peak RAM is unchanged; the bench measures the wrong thing).  Don't propose lazification in punch-lists for symbols whose path runs on every boot.  See [`plans/patterns.md` § "Eager imports are the default"](../../../plans/patterns.md).
* **`gc.collect()` at library-import boundaries — yes, in `__init__.py`.** The AGENTS.md / `/audit-library` ban on `gc.collect()` is about *hot paths* (tick / handle / per-message callbacks).  Module-import time is a different case.  MicroPython's compiler allocates intermediate scratch (AST nodes, transient tuples, interned-name artifacts) during compile.  Auto-GC only fires under allocation pressure, so a successful import can complete without ever collecting it — and the scratch stays interleaved with the library's persistent function / code / class / string objects until the *next* allocation pressure event, which is often inside a TLS handshake that needs ~25 KB contiguous.  Put `import gc` at the top of the library's `__init__.py` and call `gc.collect()` at the end of the file, and also between submodule imports when the library spans more than one `.py` file (so each submodule's compile scratch is reclaimed before the next submodule's persistent state lands).  Measured win on Pi Pico W MP: +33 KB contiguous heap at `post_import`, enough to flip the originally-failing `mqtt_tls_probe` TLS legs from ENOMEM to ROUND_TRIP.  Benign on CPython (cycle collector runs a no-op pass for non-cyclic code).  See [field-reality → gc.collect at import boundaries](field-reality.md#gccollect-at-import-boundaries) for the cumulative measurement set and the things that didn't work.

### 5. Runtime-specific branches — CP vs MP vs CPython

Three runtimes ([Decision 0049](../../../plans/decisions/0049-three-runtime-trinity.md)), three behavior profiles, multiple correct patterns.

* **`if sys.implementation.name == "..."` inside a hot path.** Both branches land in RAM and the comparison runs every tick. Resolve to a callable at import time:
  ```python
  if sys.implementation.name == "circuitpython":
      from chumicro_sockets._adapters.cp import build_socket as _build_socket
  else:
      from chumicro_sockets._adapters.mp import build_socket as _build_socket
  ```
  Then call `_build_socket(...)` directly. Per-function lazy adapter selection is documented in [`patterns.md` "Per-function lazy adapter selection"](../../../plans/patterns.md).
* **Missing `__chumicro_runtimes__` marker.** Files that import `wifi`, `esp32`, `socketpool`, `microcontroller`, `machine`, or other runtime-specific modules must declare `__chumicro_runtimes__ = ("circuitpython",)` (or the MP equivalent) at module top. Grep for runtime-specific imports without the marker — they ship to the wrong runtime and crash on first import ([Decisions 0037](../../../plans/decisions/0037-runtime-file-marking.md), [0044](../../../plans/decisions/0044-deploy-time-runtime-filtering.md)).
* **Bare `raise TimeoutError(...)` in cross-runtime code.** MicroPython 1.28 doesn't ship `TimeoutError` as a builtin. Use a library-specific exception subclass (`HttpTimeoutError`, `WebSocketTimeoutError`) or raise `OSError`. See [`patterns.md` "Missing builtins on MicroPython 1.28"](../../../plans/patterns.md).
* **`from __future__ import annotations` or `from typing import ...` in `libraries/*/src/`.** Banned by [Decision 0021](../../../plans/decisions/0021-docstring-type-policy.md). PEP 604/585 syntax (`int | None`, `list[int]`) only. CPython-only trees (tests, scripts, workbench) may keep them.
* **Hoisting function-local code to module scope: re-verify the runtime marker covers what runs at import time.** A common cleanup is moving an inner class definition + its `import builtins; import os` out of a function (where they ran lazily) up to module top (where they run at every import).  Before committing, confirm the file's `__chumicro_runtimes__` marker matches what every newly-top-level statement now requires.  See [field-reality → runtime marker after a hoist](field-reality.md#runtime-marker-after-a-hoist).

### 6. Import hygiene

* **Relative imports in `libraries/*/src/`.** Banned — CircuitPython RAM-mode deploys `exec()` modules without a `__package__` binding, so `from .helpers import x` raises `ImportError`. Use `from chumicro_<name>.helpers import x`. Enforced by ruff TID252 but the audit catches edge cases (deep relative imports, parent-package imports).
* **Dotted-deep imports inside a package.** `from chumicro_<name>._wire._codec import encode_string` is fine if `_codec` is a real module, suspicious if the dotted path navigates through compatibility re-exports. Trace the resolution; if there's a shim layer, propose flattening.
* **Unused imports.** Cheap to spot via `ruff check`; cheap flash + RAM savings.
* **Top-level imports that should be lazy** — only when the symbol's path is genuinely optional (DI / factory fallbacks the caller usually injects past, error-only helpers, once-a-year firmware-update paths, runtime-specific branches the current runtime never hits).  Default is eager — see §2 and §4 for the fragmentation framing.
* **Lazy imports that should be top-level** — `struct`, `time`, `gc`, `sys`, `errno` are called from many sites; lazy-importing them adds per-call dict lookup with no offsetting benefit.
* **Before flipping a lazy import to eager, audit who depends on the late binding.** A lazy `from X import func` inside a function resolves `X.func` at call time, so tests can monkey-patch `X.func` directly and the consumer sees the patch.  An eager `from X import func` at module top binds the function into the consumer's namespace at module-load time — the same `X.func` patch no longer takes effect, because the consumer holds its own reference.  When the audit recommends eager (because §4's lazy-import-fragmentation rule says the saving is illusory, or because the lazy form is just shielding test patches), grep for `monkeypatch.setattr` / direct attribute rebinding of the function: those test paths must move from `<source_module>.<func>` to `<consumer_module>.<func>` in the same diff.  Same Python binding-shape gotcha as the "Extraction patterns" section of `/audit-library`; applies symmetrically here when the move is import-shape rather than helper-extraction.  See [field-reality → lazy → eager flip](field-reality.md#lazy--eager-flip-and-the-test-patch-path).

### 7. Code shape for embedded

Audit each of these patterns honestly against the actual MicroPython / CircuitPython behavior, not folklore:

* **`micropython.const()` use.**
  * `_FOO = const(7)` — underscore-prefixed constants are *hidden* by the MicroPython parser; not stored as module globals, "does not take up any memory during execution" ([MicroPython `micropython` module docs](https://docs.micropython.org/en/latest/library/micropython.html)). Implemented in CircuitPython too (gated on `MICROPY_COMP_CONST`; see [circuitpython/tests/micropython/const.py](https://github.com/adafruit/circuitpython/blob/main/tests/micropython/const.py)). The CPython fallback (`def const(v): return v`) makes the pattern safe everywhere.
  * **Audit checks:**
    * Module-level uppercase int literals that look like constants — `MAX_RETRY = 5` — should be wrapped in `const(...)` so MP can inline at compile time. The leading-underscore form (`_MAX_RETRY = const(5)`) ALSO strips the module-level binding on MP/CP at compile time, which is the right call only when no other module — including `testing.py` and cross-runtime test files — needs to import the value.
    * **Default action when the candidate is currently `_NAME = N` (leading-underscore bare int) and tests OR other modules import the name: drop the underscore AND wrap.**  `NAME = const(N)` (public-but-not-in-`__all__`) keeps both wins — inlining at use sites *and* the importable name.  This is a redirection, not a blocker.  Skip the `const()` wrap only when the constant is genuinely internal-only *and* not referenced from tests / siblings / examples.  Importing leading-underscore `const()` names from a sibling module on MP/CP raises `ImportError` (see `/audit-library §7` for the same heuristic).  See [field-reality → `const()` underscore rename](field-reality.md#const-underscore-rename).
    * `const(some_func())` or `const(other_constant + 1)` where the argument isn't a compile-time-foldable literal — defeats folding silently. Inline the literal or compute once at module top without `const()`.
* **`memoryview` use.**
  * Verified gotchas: `bytes(mv)` copies; `mv.decode()` doesn't exist on MP; cached views over a bytearray must be released before the bytearray resizes (see [`patterns.md` "_buf + cached _buf_view"](../../../plans/patterns.md)).
  * **Audit checks:**
    * Every long-lived bytearray sliced more than once should have a cached sibling `memoryview` constructed in `__init__`. Per-access `memoryview(self._buf)[:n]` allocates a fresh view-object each time.
    * `bytes(view[a:b])` passed to `struct.unpack` — replace with `unpack_from(fmt, buf, offset)`.
    * `memoryview` returned from a public method whose lifetime extends past the underlying buffer's next mutation — recipe for garbage reads. Document the lifetime contract or return a `bytes()` copy at the boundary.
* **`__slots__` reality — remove from cross-runtime device libraries.**  MicroPython and CircuitPython parse the `__slots__` syntax for compatibility but don't use it for instance layout or attribute enforcement: zero RAM saving, zero attribute locking, plus a worse outcome — CPython's real `__slots__` would raise `AttributeError` on a typo'd attribute write, but MP/CP silently accept it.  The same test sweep reports green on one runtime and is blind to the failure on the other two.
  * **Audit answer:** in cross-runtime library code (`libraries/*/src/`), `__slots__` is dead weight that diverges runtime test semantics.  Remove.  The check-api gate will see the slot list as a public-surface change → minor VERSION bump.
  * See [field-reality → `__slots__` reality](field-reality.md#__slots__-reality-on-mp-and-cp-unix-port) for bench numbers and the local-reproduction recipe under `.tools/`.
* **Descriptive names everywhere (Decision 0022).** Already enforced by `CHU001`; the audit-embedded angle is that `buf` / `mv` / `_pv` / `_bv` (cached-view shorthand) are *not* in the whitelisted abbreviation set despite appearing in patterns. If the audit sees one-letter view variables in library code, flag — `_payload_view` over `_pv`.
* **Pre-encoded byte literals.** `PACKET_PINGREQ = b"\xc0\x00"` (module-level pre-encoded constant) beats encoding on demand. Look for `bytes([0xc0, 0x00])` or `struct.pack(...)` for fixed packets — usually a candidate for module-level pre-encoding.

### 8. Comments and docstrings — prose quality, not flash

The "code comments" rule in AGENTS.md says comments document the *why* of current code. A `.py` reaches a board with its docstrings and comments blanked: the workspace deploy transports run `chumicro_deploy.source_minify` on every staged file, and `bundle_manager`'s source stage runs the same strip on what `mip` and `circup` install (Decision 0090). Comment prose therefore costs the sdist, the repo reader, and the unstripped test lanes, and the audit weighs it for signal, not bytes.

**Scope split with sibling skills.**

* For the **prose-quality lens** (cold-reader test, KEEP / TRIM / REWRITE / DELETE classification, definition-by-superlative, the *new prose written from a fresh read of the code* discipline), route to [`/audit-comments`](../audit-comments/SKILL.md).  This skill stays focused on the flash-cost angle: density, signature-restating bulk, per-change justification residue.
* For **AI-tic vocabulary in docstrings** (*"comprehensive"*, *"robust"*, *"seamlessly"*, etc.), run the standing regex from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex) over `src/` docstrings and comments.  The cost amplifies here — every byte of empty-adjective prose ships to every board.  Treat hits per [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans).

* **Multi-paragraph docstrings that re-state the signature in prose.** Flag — collapse to one sentence (or drop, if the name is self-evident).
* **Block comments narrating history.** "Previously this returned a list, we switched to deque for…" — belongs in the commit message. Delete.
* **Stale TODO / FIXME / XXX.** Same. Delete unless actionable now.
* **Docstring examples that drift from the API.** A docstring `>>> client.subscribe("topic")` while the method is now `client.subscribe("topic", qos=0)` — fix the example or drop it. Doctests don't run on-device anyway.
* **Audit-pass per-change justification comments carry no reader value.**  Inline notes like `# bench-validated -25% allocation` or `# skips the bytes() copy` belong in the commit message body, not in shipped source.  Per-change comments document *why the diff exists* (audit reasoning) — they rot fast and they multiply across sites.  A general work-being-done comment at a strategy's home is OK sparingly; per-change notes are not.  Pre-existing per-change comments from earlier audits are legacy — don't proliferate, trim when convenient.  Parallel rule in `/audit-library` Anti-patterns; AGENTS.md → Code comments is the broader source.

### 9. Docs match code — code is the source of truth

The library's `docs/guide.md`, the library's `README.md`, the docstrings in `src/`, and any examples under `examples/` make claims about the API.  Each claim is a candidate for drift.

**Scope split with `/audit-docs`.**  This skill catches the *factual* drift: a documented CLI flag the code no longer accepts, a renamed exception, a default value that changed, a dead cap-knob.  When the fix opens prose that needs reshaping — a paragraph rotted from prior trims, a structural-flow issue, AI-tic phrases that won't survive the rewrite, a section that no longer matches the cold-reader arc — route the prose-shape work to [`/audit-docs`](../audit-docs/SKILL.md).  Two skills, two scopes, one library.

* **Every CLI command / flag mentioned in docs:** does it still exist in the code with the documented shape? Grep the code for the flag name; if absent, the doc is wrong. Default: fix the doc to match the code.
* **Every public symbol mentioned in docs:** still exported from `__all__`? Same parameter list? Same return-shape?
* **Every error class / exception mentioned in docs:** still raised by the code path described? `git log -S "ExceptionName"` to see if it was renamed.
* **Every config key / option mentioned in docs:** still read by the code with the same default?
* **Every code example in docs:** does it import successfully against the current code? Can it run on at least CPython without modification?  Same shape of finding as the [audit-library doc bugs cluster](../audit-library/field-reality.md#doc-bugs-cluster--audit-numbers-and-symbols-together) — copy-paste examples that hit `NameError` on a cold reader are a common drift.
* **Doc bugs cluster — find one, audit every numeric and symbolic claim in the same file.** When one quantitative or symbolic claim is wrong, re-read every other number and symbol in the file before moving on.  Doc-writers introduce errors in batches; auditors should find them in batches.  Same incident detail as [audit-library → doc bugs cluster](../audit-library/field-reality.md#doc-bugs-cluster--audit-numbers-and-symbols-together).
* **Ambiguous case:** doc says X is supported but code is silent on X. Could be an aspirational claim never implemented, or a regression that removed the feature. **Ask the user** which way to resolve — don't silently delete documented features.
* **Dead cap-knobs — public parameters the docs treat as load-bearing that the code never reads.**  A constructor kwarg like `max_message_bytes=...` shows up in the signature, in the README, in the user guide's tuning table, and in test fixtures — but the implementation only does `self._max_message_bytes = max_message_bytes` and nothing else reads it again.  Static lint can't catch this (the assignment is a real line), and prior `/audit-library` passes that check "is this name exported / called?" also miss it because the parameter IS exported and IS passed to the constructor.  **Audit move:** for every cap / threshold / size / timeout / limit kwarg, grep for both `self._foo = ` (assignment) AND `self._foo` (read) in the same module + every module that imports from it.  Assigned-only-never-read = dead public surface, doc claims notwithstanding.  See [field-reality → dead cap-knob](field-reality.md#dead-cap-knob--assigned-never-read).

### 10. Validation via instrumentation — when static review isn't enough

Some claims can only be verified dynamically. The audit should propose (and, with sign-off, execute) temporary instrumentation to validate or refute:

* **"This is a hot-path allocation"** — wrap the suspect section with:
  ```python
  gc.collect()
  gc.disable()
  before = gc.mem_alloc()
  for _ in range(100):
      <suspect call>
  after = gc.mem_alloc()
  gc.enable()
  print((after - before) / 100, "bytes per call")
  ```
  `gc.disable()` is **load-bearing** — without it, an auto-GC mid-loop reclaims short-lived objects between `mem_alloc()` reads and undercounts actual allocations. `gc.collect()` before `mem_alloc()` ensures a clean baseline. 100 iterations amortizes the per-iteration noise floor (~10 bytes on MP). Remove the instrumentation before committing.
* **Always validate at the integrated scope, not just the micro-bench.** A pattern that saves N bytes in a tight loop often saves 2-3× more in real use because the operation runs multiple times per public call (`unpackb` may do 4-8 string decodes; an `_encode` recursion may make many `_append_packed` calls). Bench the public function with a realistic payload after the micro-bench validates the pattern — the integrated number is what justifies the diff.
* **"This loop misses the runner tick budget"** — wrap with `t0 = ticks_ms(); … ; t1 = ticks_ms(); print(ticks_diff(t1, t0))`. Compare against the configured tick budget (often 10 ms).
* **"This buffer fragments the heap"** — record `gc.mem_free()` before and after N iterations; trend over many iterations exposes fragmentation. Bench against an alternative that pre-allocates. **But beware:** "total bytes allocated" doesn't fully measure fragmentation pressure — freed blocks can be reused before the next allocation, masking the real heap-fingerprint cost. A proper fragmentation test interleaves the suspect call with long-lived allocations and watches `gc.mem_free()` for available large blocks.
* **Measure fragmentation properly: `max_free_sz` from `micropython.mem_info(1)`, not `gc.mem_free()` alone.** `gc.mem_free()` reports total free bytes — high even when the heap is Swiss cheese.  The fragmentation signal is `max_free_sz` (max contiguous free run, in 16-byte GC blocks on rp2; ×16 for bytes) and the count of 1-block / 2-block allocations.  A library that adds ~200 small pins while consuming only ~27 KB of useful state can destroy ~100 KB of contiguous heap (`mqtt_tls_probe` failed this way at `max_free_sz` ~490 blocks ≈ 8 KB despite ~140 KB total free).  Run `micropython.mem_info(1)` after `gc.collect()` at every checkpoint (boot / post-wifi / post-import / post-connect / mid-runtime / post-disconnect) — the heap map at the bottom of the dump is the ground truth.
* **Build a fragmentation harness as a workspace-template project.** Pattern: `projects/<lib>_frag_probe/app.py` that (1) connects wifi, (2) imports the library chain, (3) exercises it (open a connection, do N message round trips), (4) dumps `mem_info(1)` at each checkpoint with `gc.collect()` first.  Output `RESULT <label> <value>` lines for grep extraction.  Then deploy with `chumicro-workspace deploy <name> --device pi-pico-w-mp --tail 30 --non-interactive 2>&1 > .scratch/frag-<iter>-<slug>.log` and diff successive iterations.  Reference: `projects/frag_probe_runtime/app.py` + `.scratch/frag-iter-log.md` from the rp2-MP TLS fragmentation hunt (see commit `a99221b9`).
* **Track hypothesis iterations as a running table.** A markdown table with columns `Iter | Change | max_free_sz | Δ vs baseline | 1-blocks | Δ vs baseline | Kept? | Notes` lets you separate signal (consistent delta across re-runs) from noise (single-run variance of ±10 blocks).  Re-run a candidate twice before deciding — the baseline itself drifts a few blocks across MP boots, so a single-block change isn't significant.  Counter-intuitive results worth flagging: removing a long docstring made fragmentation *worse* (-5 blocks) because the freed string-block left a gap that small allocations scattered into.  Inlining a single-call helper saved -1 1-block but cost -8 max_free_sz blocks.  Be willing to revert.
* **"This `__init__.py` re-export costs RAM on import"** — `before = gc.mem_alloc(); import chumicro_<name>; after = gc.mem_alloc(); print(after - before)` in a fresh REPL.
* **Module-import-cost validation uses a fresh process per scenario.** Once a module is imported into a running interpreter, subsequent `gc.mem_alloc()` deltas around `import X` show zero — the second import is just a cache lookup. For honest cold-import measurement, spawn a fresh interpreter per scenario (`.tools/micropython-v*/ports/unix/build-standard/micropython -c '<test>'` and the matching CP path). The pattern: one process per `(scenario, runtime)` cell, each reporting `gc.mem_alloc()` before/after a single `import` of the target module. To compare variants of the same module (e.g. eager vs lazy `from chumicro_msgpack import unpackb`), stage the variant as a synthetic package under `.scratch/` so the original library is unmodified during measurement.
* **Don't trust intuition alone for buffer-strategy refactors.** The obvious "pre-allocate to skip extend churn" intuition can measure *worse* than the current capacity-doubling baseline at every realistic payload size.  Bench BEFORE proposing the refactor; the bench can flip the recommendation.  See [field-reality → capacity-doubling baseline](field-reality.md#capacity-doubling-baseline-beats-hand-rolled-buffering).
* **Distinguish "eliminates cost" from "defers cost."**  A measured saving that defers an allocation (on-demand decode, late-bound callback, dynamic dispatch) is only a real saving if the deferred-to point is far enough from the deferred-from point that the program enters a different state in between — different working set, different live longevity, different fragmentation context.  When the deferred-to point is "a few stack frames later with no other work in between," peak RAM is unchanged and the optimization is timing-only.  Always pair the micro-bench number with a real-usage timing trace: when does the cost actually get paid in the typical app shape?  **For lazy imports specifically, the rule is even stronger:** lazy is also worse for fragmentation (long-lived module state lands in heap holes), so the default is eager regardless of bench numbers (§2 / §4).  See [field-reality → lazy import that deferred cost without saving it](field-reality.md#lazy-import-that-deferred-cost-without-saving-it).
* **Instrumentation lives in a temporary branch** — never commit `print(gc.mem_alloc())` to library source.  The validation is for the audit; the diff for the user is whatever cleanup the validation justifies.
* **When a network call fails inconsistently across contexts, instrument the function — don't theorise.** A connect that succeeds from the REPL but fails from `main.py` is tempting to explain as a wifi-settle / lwIP-TIME_WAIT / cyw43-power-save race.  None of those are usually it.  The fastest path is to add `print()` statements around the suspect function (`socket.getaddrinfo`, `sock.connect`, the factory closure) printing the **arguments it's actually receiving** and run again.  The diagnosis you can't theorise into is usually "the arguments aren't what you think they are."  Tag findings as `cpu` or `runtime` depending on which dimension the fix lands in.  See [field-reality → wrong-host bug found by `print()`](field-reality.md#wrong-host-bug-found-by-print-not-by-theorising).

### 11. Reference-implementation reading — `.tools/` and prior art

When a behavior is uncertain (does CircuitPython actually no-op `__slots__`? does this MP build accept `unpack(memoryview)`?), check the runtime source under `.tools/` (gitignored, populated by `python scripts/run.py prepare-circuitpython` / `prepare-micropython`). The runtime source is authoritative when the docs are silent. Cite the path in the punch-list finding (`.tools/circuitpython/py/objslot.c` or similar) so the user can verify.

Worked example: the kvstore embedded audit needed to know whether `MpNvsBackend` could discover blob size before allocating its read buffer. `.tools/micropython-v1.26.0/ports/esp32/esp32_nvs.c:103` showed `esp32_nvs_get_blob` is a fill-and-return-length wrapper around `nvs_get_blob` with no size-query path — which ruled out a try-small-buffer-then-resize refactor and pointed the fix toward "make the buffer transient instead" plus "shrink the default." Reading 12 lines of C saved a wrong refactor.

**Prior art outside `.tools/` — when the library has a predecessor, do a side-by-side compare.**  If the user references "we had an MQTT client that worked before — see `<path>`," or if the library's docstrings credit an upstream implementation, read that reference top-to-bottom under the same audit lens.  Compare along three axes: (a) **missing concepts** — what tiers / modes / lifecycle phases does the reference distinguish that the current library has collapsed? (b) **buffer sizing** — what fixed-size buffers does the reference reserve where the current library allocates dynamically, and vice versa? (c) **error pathways** — does the reference raise / disconnect / fault on inputs the current library silently accepts?  Reference comparison is the single highest-yield move when prior art exists.  Cite the reference path in punch-list findings so the user can verify the comparison.  See [field-reality → prior-art side-by-side compare](field-reality.md#prior-art-side-by-side-compare).

## Process

1. **Read the library top-to-bottom first.** One full pass through every `.py` under `src/` to build mental model. Same as `/audit-library` step 1 — but with the embedded lens active (note allocations, cached views, runtime imports, top-level work).
2. **Tabulate library size.** `wc -l libraries/<name>/src/chumicro_<name>/*.py`. Compare to peer libraries (`wc -l libraries/*/src/chumicro_*/__init__.py` and per-module). Note any peer-LOC outliers.
3. **Check the cluster math.** Count `.py` modules in `src/<name>/`. If 4+, estimate `cluster_size_bytes * file_count` of waste against the total source size. If the cluster overhead is comparable to or larger than the consolidated source size, propose consolidation.
4. **Grep for hot-path patterns:**
   * `time\.sleep\|select\.poll\|async\|await` — runner-shape violations.
   * `from typing\|from __future__` — banned in device code.
   * `\.format(\|f"` — flag every match inside `tick`/`check`/`handle`/parser bodies.
   * `gc\.collect` — every match is a finding candidate.
   * `bytes(.*\[.*:.*\])\|memoryview(self\._` — manual review of every match.
   * `__slots__` — every match is a CPython-only-feature audit candidate.
   * `import wifi\|import esp32\|import socketpool\|import microcontroller\|import machine` — every match must pair with a `__chumicro_runtimes__` marker in the same file.
   * `def \w+_raw(\|def \w+_unencoded(\|def \w+_unprefixed(\|def raw_\w+(` — wrapper-doubling candidates (§1 prefix-sugar pattern).  For every match, diff the body against the unsuffixed sibling — if the delta is one helper call or one conditional, it's a candidate for collapse-with-kwarg.
5. **Run the audit dimensions.** Note findings in a list.
6. **Where static review is inconclusive, propose instrumentation.** Don't execute without sign-off — instrumentation runs change the running code temporarily and the user may have a deploy in flight.
7. **Score each finding by confidence:**
   * **High** — banned syntax (`from __future__`, bare `TimeoutError`, missing runtime marker), unused imports, `bytes(view[a:b])` to `unpack`, dead constants. Safe to fix without further discussion.
   * **Medium** — `__init__.py` consolidation proposals, file-count consolidations, lazy-import recommendations, `__slots__` drops, structural memoryview-caching changes. Benefit from a second opinion.
   * **Low** — doc-vs-code ambiguities where the user must decide which side is correct. Escalate via the punch-list.
8. **Present the punch-list to the user.** Group by dimension. Flag taste calls separately.
9. **Execute high-confidence items as one cohesive commit.** Run the library's tests + every sibling package that imports from it after each batch. Hardware-verify if the change touches a deploy / probe / transport path (Pi Pico W CP / MP boards from `devices.yml` defaults).
10. **Execute medium-confidence items as separate commits, one per finding.** Per the user's preference: small reversible commits beat one big merge.
11. **Inspect the staged diff before every audit commit.** Run `git --no-pager diff --cached` and confirm every staged hunk is one you made.  Audits run iteratively, and concurrent edits (linter hooks, parallel agent sessions, the user's own in-flight work) can land in the same files between your Edit and your `git add`; staging "the file" with `git add libraries/<name>/...` then picks up everything in the working tree.  Either stage with `git add -p` for surgical commits when foreign hunks are present, or always inspect `--cached` before `commit`.  Same failure mode as `/audit-library` step 8; cached-diff check costs ~2 seconds.  See [audit-library → inspect the staged diff](../audit-library/field-reality.md#inspect-the-staged-diff-before-every-audit-commit) for the incident detail.
12. **For doc-vs-code drift:**
    * If the code is clearly right and the doc is stale — fix the doc, no question to user.
    * If the doc encodes intent the code lost (a feature that regressed silently) — surface as a separate finding for user decision, don't auto-resolve.
13. **For instrumentation findings — three commits:**
    * Commit 1: instrumentation added (so the validation is reproducible).
    * Commit 2: the fix justified by the instrumentation.
    * Commit 3: instrumentation removed.
    Or, equivalent: instrumentation lives only in a stash that the audit log references in the commit message of the fix.
14. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.** Same rule as `/audit-library`.

## Anti-patterns

* **Don't apply embedded micro-optimizations to workbench packages.** `workbench/<name>/` is CPython-only; flash and heap don't apply there. The `--coverage-threshold` math is the only carryover.
* **Don't `gc.collect()` everywhere to fix a fragmentation finding.** The fix is pre-allocation; `gc.collect()` is a thermometer, not a treatment.
* **Don't keep `__slots__` "just in case."** Bench-verified: zero RAM saving on MP and CP, zero attribute enforcement, and CPython's real `__slots__` masks typo bugs that the device runtime would silently accept. In cross-runtime library code, remove. See §7 "`__slots__` reality" for the empirical evidence.
* **Don't consolidate modules just to win the file-count game.** If two modules legitimately have separate roles (e.g. wire-protocol code vs orchestration code), the cluster cost is the price of clarity. Consolidate when the dependency graph is a chain (A → B → C and nothing else calls B or C); leave when modules serve distinct purposes with multiple consumers.
* **Don't lazy-import primitives used on every tick.** `struct`, `time`, `gc`, `sys`, `errno`, `socket` (when used) belong at module top in their consuming module — the per-call dict lookup of a function-scoped import costs more than the load.
* **Don't commit instrumentation.** `print(gc.mem_alloc())` in library source ships to devices. Remove before committing.
* **Don't override the user on doc-vs-code ambiguity.** Code-as-source-of-truth is the *default*; the user's judgment overrides when an aspirational doc claim represents an intentional roadmap.
* **Don't break public API to win an audit dimension.** A symbol exported from `__all__` and imported by sibling libraries / workbench / examples is out-of-scope for renames in this pass; flag separately.
* **Don't ignore the `/audit-library` lens.** A finding that's really about code shape, dead code, or readability belongs in `/audit-library`. Cross-tag and escalate.
* **Don't dismiss inline comments that justify a non-obvious structure without verifying the claim.**  A comment like *"pre-allocated here because fragmentation"*, *"eager import to avoid an mpremote RPC on mount-mode tests"*, or *"constants redefined to dodge `const()`-stripping"* is direct evidence that the cleaner-looking alternative was considered and rejected.  Before "fixing" the structure, validate the claim against the actual constraint it names — and run the runtime / test sweep the constraint relates to, not just `pytest libraries/<name>/tests/`.  If the file is imported by cross-runtime tests, run `python scripts/run.py preflight` before committing.  Same anti-pattern as `/audit-library`; embedded code attracts these comments more often because it's where runtime quirks live.

## After the audit

If the audit produced commits:

* Bump the library's `VERSION` file *once* at the end of the audit pass — not per commit (same rule as `/audit-library`).
* Run the `task-checkpoint` skill: `python scripts/run.py preflight --coverage-threshold 94` to confirm the full sweep passes.
* If the change touched device libraries that own time / I/O, also run `python scripts/run.py test-libraries-functional --library <name>` to hardware-verify against `devices.yml` defaults.
* If the change touched a hot path, run a real-board sanity check — `chumicro-workspace deploy --device <board>` + observe in `chumicro-workspace repl --tail` for at least one minute under load.
* Run `python scripts/run.py check-version` and `python scripts/run.py check-api` if the library has a public API surface.
* Update any docstrings the user-facing API rewrites invalidated. The audit's own §9 found these; don't re-introduce them.

The audit is done when:

* Every HIGH-confidence finding either has a corresponding commit or has been explicitly skipped with the user's sign-off.
* Every MEDIUM and INSTRUMENTATION finding has an answer from the user — applied, deferred to `plans/next-up.md`, or dropped.
* No `print(gc.mem_alloc())` / `print(ticks_ms())` instrumentation remains in `src/` (the instrumentation commits are reverted or never landed).
* `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.
* If the library owns time / I/O, `python scripts/run.py test-libraries-functional --library <name>` passes on the `devices.yml` defaults (or you've flagged that you couldn't run it).
* If the change touched a hot path, a one-minute under-load REPL tail on real hardware showed no regressions.
* `check-api` agrees with the chosen VERSION bump level.
* Any USER-DECISION findings have an answer; any ESCALATE findings are filed as `## Next` entries routing to `/audit-library` or `/audit-integration`.

If new stumbles surface after the final commit (a runtime-marker mismatch unmasked by the hoist, a doc example that still names a deleted symbol), file as a follow-up rather than expanding the audit pass.

## Output format

```
Embedded audit: chumicro_<name>
================================

HIGH-CONFIDENCE (safe to fix):

  flash     src/<name>/<file>.py:NN — <one-line description>
  ram-imp   src/<name>/<file>.py:NN — <top-level work that should be lazy>
  heap      src/<name>/<file>.py:NN — <hot-path allocation>
  runtime   src/<name>/<file>.py:NN — <missing __chumicro_runtimes__ / banned syntax>
  imports   src/<name>/<file>.py:NN — <relative import / unused import / wrong-direction lazy>
  shape     src/<name>/<file>.py:NN — <const() / memoryview / __slots__ recommendation>
  docs      docs/guide.md:NN — <doc claim that contradicts code>
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  flash     src/<name>/*.py — file-count consolidation (N modules → M)
  ram-imp   src/<name>/__init__.py — re-export reduction
  frag      src/<name>/<file>.py:NN — pre-allocation / cached-view proposal
  shape     src/<name>/<file>.py:NN — drop __slots__ from <Class>
  ...

INSTRUMENTATION (validate dynamically):

  heap      src/<name>/<file>.py:NN — wrap with gc.mem_alloc() delta; expect ≤ 0
  cpu       src/<name>/<file>.py:NN — wrap with ticks_ms() delta; expect ≤ 10ms
  ...

USER DECISION (doc vs code ambiguous):

  docs      docs/guide.md:NN — claims feature X; code is silent on X. Aspirational or regression?
  ...

ESCALATE:

  cross-skill   src/<name>/<file>.py:NN — finding is really about <reader-readability/method-shape>
                (route to /audit-library <name>)
```

Tag taxonomy:

* `flash` — flash footprint (file count, module size, dead methods, long docstrings).
* `ram-imp` — RAM consumed at module import time (top-level work, eager initialization).
* `heap` — heap allocation in hot paths.
* `frag` — fragmentation prevention (pre-allocation, cached views, buffer reuse).
* `runtime` — runtime-specific code (CP/MP/CPython branches, runtime markers, missing-builtin handling).
* `imports` — import hygiene (relative imports, unused, wrong-direction lazy).
* `shape` — embedded-specific code shape (`const()`, `memoryview`, `__slots__` reality, pre-encoded literals, attribute-chain caching).
* `docs` — docs-match-code drift (default: fix doc to match code).
* `cpu` — tight-loop CPU budget under runner ticks.
* `cross-skill` — finding belongs in `/audit-library`; escalate.

The goal: same library, fewer flash bytes, less import-time RAM, no hot-path allocations, no runtime-branch surprises, docs that match the code as-shipped. Tests still pass, preflight green, project-policy invariants enforced.
