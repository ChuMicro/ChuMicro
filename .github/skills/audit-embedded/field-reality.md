# Audit-embedded field reality

Incidents, bench numbers, and worked examples that shaped the audit dimensions in [SKILL.md](SKILL.md).  Each section is referenced from a bullet there.  Consult an entry when the *how this came up* context behind a rule is useful; the rule itself stays in SKILL.md.

A few cross-cutting incidents (kvstore guide doc cluster, chumicro_ntp staged-diff surprise) live in the [audit-library reference file](../audit-library/field-reality.md) and are linked from this skill rather than duplicated.

## Contents

- [Useful snippets](#useful-snippets)
- [Docstring density trim — chumicro_config](#docstring-density-trim--chumicro_config)
- [kvstore MP-NVS default sizing](#kvstore-mp-nvs-default-sizing)
- [Asymmetric tx / rx defaults — chumicro_mqtt](#asymmetric-tx--rx-defaults--chumicro_mqtt)
- [`str(view, "utf-8")` allocation savings](#strview-utf-8-allocation-savings)
- [`_append_packed` encoder pattern](#_append_packed-encoder-pattern)
- [Sender-controlled bytearray — heap-DoS](#sender-controlled-bytearray--heap-dos)
- [Long-lived buffer that was actually transient](#long-lived-buffer-that-was-actually-transient)
- [Pre-allocate-and-position-track regression](#pre-allocate-and-position-track-regression)
- [Runtime marker after a hoist](#runtime-marker-after-a-hoist)
- [Lazy → eager flip and the test-patch path](#lazy--eager-flip-and-the-test-patch-path)
- [`const()` underscore rename](#const-underscore-rename)
- [`__slots__` reality on MP and CP unix-port](#__slots__-reality-on-mp-and-cp-unix-port)
- [Dead cap-knob — assigned, never read](#dead-cap-knob--assigned-never-read)
- [Capacity-doubling baseline beats hand-rolled buffering](#capacity-doubling-baseline-beats-hand-rolled-buffering)
- [Lazy import that deferred cost without saving it](#lazy-import-that-deferred-cost-without-saving-it)
- [Wrong-host bug found by `print()`, not by theorising](#wrong-host-bug-found-by-print-not-by-theorising)
- [Prior-art side-by-side compare](#prior-art-side-by-side-compare)
- [gc.collect at import boundaries](#gccollect-at-import-boundaries)
- [publish / publish_raw wrapper-doubling](#publish--publish_raw-wrapper-doubling)
- [Wrapper-doubling workspace re-pass](#wrapper-doubling-workspace-re-pass)

## Useful snippets

### Docstring density triage

For the "long docstrings and comments" dimension — quick AST walk to estimate doc-line density on a module.  Anything over ~30% on a small library is a trim candidate.

```bash
python -c "import ast; tree=ast.parse(open('<file>').read()); print(sum((ast.get_docstring(n, clean=False) or '').count(chr(10))+1 for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(n)))"
```

Output is total docstring lines; divide by `wc -l` of the file for the ratio.

## Docstring density trim — chumicro_config

A config-library pass found 50–60% doc-line density across three modules; trimming to 15–33% saved ~5 KB of `.py` source with no API surface lost.  Multi-paragraph docstrings re-explaining the obvious are flash bytes for nothing.

## kvstore MP-NVS default sizing

kvstore's MP-NVS backend defaulted `capacity=16 KB` — generous against the ~24 KB partition ceiling, but ~32× larger than the documented "boot counters + timestamps + short tokens" workload needs.  The default looked like a sizing knob, but `__init__` did `self._buf = bytearray(self.capacity)`, so every instance pinned 16 KB of long-lived RAM for an 0.5 KB workload.

**Pattern:** audit `__init__`-time heap allocations against the *documented* use case, not the maximum-supported workload.  The fix is two-part: shrink the default and (if call frequency justifies it) make the buffer transient.

## Asymmetric tx / rx defaults — chumicro_mqtt

chumicro_mqtt's `max_tx_queue_size` defaulted to 100 packets — matching the RX-side `recv_budget_per_tick`-shape generosity.  But a subscriber receives broker fan-out + retained-message replay + N concurrent subscribed-topic bursts (RX is noisy → 256 B-class buffer right-sized), while the same client publishes once every N seconds (TX queue stays near zero → 20-slot cap plenty).  Dropped to 20 once the asymmetry framing made the documented use case clear.

**Pattern:** when a library has two paths that allocate independently — RX and TX on a network client, server-side vs client-side on a transport, read-buffer vs write-buffer on a persistence layer — the right default for each side comes from its *own* usage profile, not from a unified "library footprint" target.  Name each path's documented profile separately before deciding numbers.

## `str(view, "utf-8")` allocation savings

`bytes(view).decode("utf-8")` allocates the intermediate `bytes` copy that the 3-arg `str()` constructor skips.  Bench: **-25%** allocation per call on MP 1.26 + CP 10.2 unix-port (96 vs 128 bytes per call).  Worth more in integration: a `chumicro_msgpack` `unpackb` of a 4-string payload dropped **-37%** (961 → 609 bytes) because each call did multiple decodes.

## `_append_packed` encoder pattern

Encode-side counterpart to the `unpack_from` rule.  `buffer.extend(struct.pack(fmt, value))` allocates a fresh `bytes` per call; `pack_into` writes directly into a pre-extended bytearray slice.  Pattern: a small `_append_packed(buffer, fmt, value, zero_bytes)` helper plus module-level `_ZERO2 = b"\x00\x00"` / `_ZERO4 = b"\x00\x00\x00\x00"` literals to skip per-call zero-byte allocation.  Bench: **-50%** allocation per pack on MP 1.26 (64 vs 128 bytes per call).  For signed single-byte fields (`>b`), `buffer.append(value & 0xff)` skips struct entirely.

**Important:** this is an established hot-path pattern *for new code*.  Existing libraries (`chumicro_mqtt._wire`, `chumicro_requests._wire`, `chumicro_websockets._wire`) still use `extend(struct.pack(...))` and should converge on `_append_packed` in their own embedded-audit passes — flag the divergence rather than rewriting an unaudited library mid-pass.

## Sender-controlled bytearray — heap-DoS

chumicro_mqtt's "oversized message" path allocated `bytearray(payload_to_drain)` sized to the remaining payload — a 1 MB hostile inbound PUBLISH allocated 1 MB on a 256 KB-RAM board.  Three prior audit passes had walked past this.

**Pattern:** every sender-controlled `bytearray(N)` / `bytes(N)` is a heap-DoS vector when N comes from a peer-controlled field (MQTT remaining-length varlen, HTTP `Content-Length`, WebSocket frame length).  The line `self._foo = bytearray(payload_remaining)` looks ordinary in code review; static lint won't catch it.  Fix has two shapes: (a) bound N at the documented cap-knob (`max_message_bytes`, `max_body_bytes`) and refuse / drop above it; (b) reuse a pre-allocated steady-state buffer as a rolling sink and discard bytes as they drain.  Flag every sender-controlled `bytearray(N)` even when it sits next to a comment that claims to be the heap-safe degraded path.

## Long-lived buffer that was actually transient

`MpNvsBackend` held `self._read_buffer = bytearray(self.capacity)` for the object's lifetime to "reuse across loads," but `load()` runs at construction + on explicit `reload()` only (never on the commit hot path).  The buffer pinned 16 KB on a 256 KB-RAM ESP32 for zero per-call benefit.  Moving the allocation inside `load()` made the buffer transient and dropped the long-lived RAM cost to near-zero.

**Pattern:** a buffer earns long-lived status by call frequency, not by the word "reusable" in a comment.  When the audit sees a `_buf = bytearray(N)` in `__init__`, count actual touches per session before defending the long-lived shape.

## Pre-allocate-and-position-track regression

The obvious "`bytearray(64)` + write cursor + `bytes(memoryview(buf)[:pos])` return" pattern for transient per-call encoder output measured **+33% to +135%** allocation across realistic payload sizes (47–500 B) vs plain `bytearray()` + `.append()` / `.extend()` + `bytes(buf)` on MP 1.26 unix-port.  MicroPython's bytearray uses capacity-doubling internally; `buf.append(byte)` is one C-level call, while `buf[pos] = byte; pos += 1` is two Python operations + an attribute lookup, and `bytes(memoryview(buf)[:pos])` adds a wrapper allocation on top of the bytes copy.

**Pattern:** don't pre-allocate transient buffers without bench-measuring against the capacity-doubling baseline first.  The intuition that "pre-allocate to skip extend churn" wins can flip on actual measurement.

## Runtime marker after a hoist

Hoisting `_RuntimeFs` (a class definition + its `import builtins; import os`) out of `MpLittlefsBackend._acquire_runtime_fs()` to module top was safe specifically because the file was `("micropython",)`-marked and both `os` and `builtins` are always available on MP.  The same hoist in a cross-runtime file would have surfaced the missing builtin on a runtime that previously avoided the import via lazy evaluation.

**Pattern:** when moving function-local code to module scope (lazy → import-time), re-verify the file's `__chumicro_runtimes__` marker matches what every newly-top-level statement now requires.  The hoist is a runtime-marker audit, not just a perf cleanup.

## Lazy → eager flip and the test-patch path

A chumicro_mqtt re-pass flipped `from chumicro_sockets import tcp_client_socket` from lazy-in-factory-closure to module-top eager.  The one test patching `chumicro_sockets.tcp_client_socket` immediately attempted a real socket and timed out for 75 s; fixed by patching `chumicro_mqtt.client.tcp_client_socket` instead.

**Pattern:** a lazy `from X import func` inside a function resolves `X.func` at call time, so `monkeypatch.setattr("X.func", ...)` works.  An eager `from X import func` at module top binds the function into the consumer's namespace at module-load time — the same patch no longer takes effect, because the consumer holds its own reference.  When the audit recommends eager, grep for `monkeypatch.setattr` of the function being eager-imported and update test patch paths from `<source_module>.<func>` to `<consumer_module>.<func>` in the same diff.  Same Python binding-shape gotcha as `/audit-library`'s "Extraction patterns" section, applied symmetrically to imports.

## `const()` underscore rename

A chumicro_ntp embedded audit initially classified four module-level int constants (`_NTP_TO_UNIX`, `_PACKET_SIZE`, `_CLIENT_FIRST_BYTE`, `_SERVER_MODE`) as "blocked, skip `const()` wrap" because tests imported `_NTP_TO_UNIX`.  User correction was to drop the underscore on all four — `NTP_TO_UNIX = const(2208988800)`, `PACKET_SIZE = const(48)`, etc — and update the test import.

**Pattern:** when the candidate is currently `_NAME = N` (leading-underscore bare int) and tests OR other modules import the name, drop the underscore AND wrap.  `NAME = const(N)` (public-but-not-in-`__all__`) keeps both wins — inlining at use sites *and* the importable name.  Importing leading-underscore `const()` names from a sibling module on MP/CP raises `ImportError`; this is a redirection, not a blocker.

## `__slots__` reality on MP and CP unix-port

Bench-validated on MicroPython 1.26 unix port and CircuitPython 10.2.0 unix port: 100 instances of a slotted class consume the same heap as 100 instances of an unslotted class (10688 bytes on both runtimes), and `instance.unknown_attribute = 1` is accepted without raising `AttributeError`.  The MP/CP parser accepts the `__slots__` syntax for compatibility but doesn't use it for instance layout or attribute enforcement.

**On-device picture:** zero RAM saving, zero attribute locking, plus a worse outcome — CPython's real `__slots__` would raise `AttributeError` on a typo'd attribute write, but MP/CP silently accept it.  The same test sweep reports green on one runtime and is blind to the failure on the other two.

**Reproduce locally:** `.tools/micropython-v*/ports/unix/build-standard/micropython -c '<test>'` and the equivalent under `.tools/circuitpython-*/ports/unix/build-standard/`.  Both runtimes give the same answer.

## Dead cap-knob — assigned, never read

A chumicro_mqtt audit found `max_message_bytes` was the named cap on every doc surface (README, guide.md memory-notes table, constructor docstring, four test fixtures) but the decoder never compared anything against `self._max_message_bytes`.  The implementation did `self._max_message_bytes = max_message_bytes` and nothing else read it.  Three prior audits missed it because the parameter IS exported and IS passed to the constructor — the "is this name exported / called?" check passes, but "is the stored value ever read?" doesn't.

**Audit move:** for every cap / threshold / size / timeout / limit kwarg, grep for both `self._foo = ` (assignment) AND `self._foo` (read) in the same module + every module that imports from it.  Assigned-only-never-read = dead public surface, doc claims notwithstanding.  Same shape as the `/audit-library` lying-class-name honesty check — the gap is between what the parameter looks like it's doing and what it actually does.

## Capacity-doubling baseline beats hand-rolled buffering

The msgpack audit found that the obvious "pre-allocate to skip extend churn" intuition measured *worse* than the current capacity-doubling baseline at every realistic payload size.  Bench BEFORE proposing the refactor; the bench can flip the recommendation.

## Lazy import that deferred cost without saving it

A chumicro_config pass measured a clean 7.1 KB import-time saving for lazy `from chumicro_msgpack import unpackb` on MP 1.26 + CP 10.2 unix-port — bench number looked great.  But real apps call `load_runtime_config()` at the top of `main()`, so the saving window doesn't exist in practice.  AND the lazy form would land unpackb's globals after the eager-config module state, fragmenting them apart from the rest of the library's long-lived state.

**Pattern:** distinguish "eliminates cost" from "defers cost."  A measured saving that defers an allocation (on-demand decode, late-bound callback, dynamic dispatch) is only a real saving if the deferred-to point is far enough from the deferred-from point that the program enters a different state in between — different working set, different live longevity, different fragmentation context.  For lazy imports specifically, the rule is even stronger: lazy is also worse for fragmentation, so the default is eager regardless of bench numbers.  Always pair the micro-bench number with a real-usage timing trace.

## Wrong-host bug found by `print()`, not by theorising

A chumicro_mqtt bench session burned an hour theorising wifi-settle timing for an `ECONNABORTED`.  Four `print()` lines added to `connect_tcp` on-device immediately showed `host=test.mosquitto.org` (from `secrets.toml`) instead of the expected local broker host, and the broker-side mosquitto log confirmed the connections-and-immediately-closes pattern.

**Pattern:** when a network call fails inconsistently across contexts (succeeds from REPL, fails from `main.py`), it's tempting to explain as a wifi-settle / lwIP-TIME_WAIT / cyw43-power-save race.  None of those are usually it.  The fastest path is to instrument the function — `print()` statements around `socket.getaddrinfo`, `sock.connect`, the factory closure — printing the **arguments it's actually receiving**.  The diagnosis you can't theorise into is usually "the arguments aren't what you think they are."  Static review and theorising can't substitute for "what value is this function actually called with right now."  Tag the finding as `cpu` or `runtime` depending on where the fix lands.

## Prior-art side-by-side compare

A chumicro_mqtt audit took 30 minutes for a side-by-side against a previous-generation MQTT reference implementation.  Surfaced: the missing intact-delivery tier (the current library treated every PUBLISH > rx_buffer_size as oversized; the reference distinguished "fits in heap, deliver intact" from "way too big, discard via rolling sink"), the missing fixed `DEGRADED_BUFFER_SIZE` constant, and the missing SUBACK 0x80-rejection auto-fault.  None of those had been flagged in three prior audit passes.

**Pattern:** reference comparison is the single highest-yield move when prior art exists.  Read the reference top-to-bottom under the same audit lens; compare along three axes: (a) **missing concepts** — what tiers / modes / lifecycle phases does the reference distinguish that the current library has collapsed? (b) **buffer sizing** — what fixed-size buffers does the reference reserve where the current library allocates dynamically, and vice versa? (c) **error pathways** — does the reference raise / disconnect / fault on inputs the current library silently accepts?  Cite the reference path in punch-list findings so the user can verify the comparison.

## gc.collect at import boundaries

`projects/mqtt_tls_probe` on Pi Pico W MP failed every TLS handshake with `OSError(ENOMEM)` despite ~140 KB total free, because `max_free_sz` collapsed to ~490 16-byte blocks (~8 KB) — Swiss-cheese fragmentation, not exhaustion.  A 25-iteration hypothesis sweep (`.scratch/frag-iter-log.md`, commit `a99221b9`) bisected this to MicroPython's compile-time scratch staying resident after `chumicro_mqtt` and its dependencies finished loading.  Auto-GC only fires under allocation pressure; a successful import sequence never triggers it.  The scratch interleaves with the library's persistent objects (function / code / class / string heads), and the next big contiguous allocation request (the TLS handshake) fails.

The fix is six `gc.collect()` calls at strategic placement (`import gc` at module top, `gc.collect()` at each point; see commit `a99221b9` for the historical diff):
- `chumicro_mqtt/__init__.py` — between `_wire` and `client` imports (defragment _wire's scratch before client.py's persistent state lands) AND at end (defragment before downstream imports of `sockets_factory` and `runner`).  The end-of-init position is **load-bearing**: removing it drops `max_free_sz` by 1117 blocks (~18 KB).
- `chumicro_mqtt/_wire.py` — before the `PacketDecoder` class body (+5 blocks, marginal but stable).
- `chumicro_sockets/__init__.py` — at end, mainly to help the runtime-gated lazy `_adapters/mp` import behind the TLS-using entry points.
- `chumicro_config/__init__.py`, `chumicro_runner/__init__.py`, `chumicro_timing/__init__.py` — at end, no measurable benefit in this particular probe chain but the pattern is the load-bearing one and applies symmetrically.

Measured net win on Pi Pico W MP: post_import `max_free_sz` `4089 -> 6170` blocks (~+33 KB contiguous heap recovered), and the originally-failing `mqtt_tls_probe` TLS_NOVERIFY + TLS_CA legs both succeeded with 10/10 publish-echo cycles at 137 ms connect-to-echo.  Runtime is stable: `max_free_sz` holds across a 20-publish session.

**Things that did NOT work** during the sweep (all reverted, full table in `.scratch/frag-iter-log.md` in the same commit):

- **Trimming long docstrings:** -5 blocks `max_free_sz`.  Counter-intuitive: removing a large string left a gap that small allocations scattered into, *increasing* fragmentation.  Large contiguous allocations (multi-paragraph docstrings, big code objects) are NOT the fragmentation source — they're the *opposite* of fragmentation.  Don't propose docstring trimming as a fragmentation fix.
- **Inlining a single-call helper function** (`_force_non_blocking`): -1 1-block but -8 max_free_sz blocks.  The structural-readability cost is real and the win is noise.
- **Inlining a single-call method** (`_parse_connack`): same pattern, net negative.
- **`gc.collect()` mid-class-body in `client.py`** (before the MQTTClient class): -17 blocks.  The `import gc` statement mid-file disrupted the class body's heap layout.
- **Double `gc.collect()` calls at each kept site:** no improvement.  MP's single-pass collector is already fully effective for non-cyclic compile scratch.
- **`gc.collect()` at start of `__init__.py`:** redundant with the probe's pre-import sweep.
- **Eager import of `chumicro_timing`** in `chumicro_mqtt/client.py`: -11 blocks.  The lazy DI-fallback path was actually fine here.
- **`gc.collect()` in small libraries that load LAST in the chain** (runner, timing): no measurable benefit because the consumer's next gc.collect catches it.  Kept for cross-chain defensive symmetry but don't expect measurement gains.

**Building the harness.** `projects/frag_probe_runtime/app.py` is the reference shape — wifi connect, defer chumicro imports inside `run()`, call `dump("post_import")` etc. at each phase, use `chumicro-workspace deploy --tail 30 --non-interactive`, grep for `max free sz` from `micropython.mem_info(1)`.  Track iterations in `.scratch/frag-iter-<NN>-<slug>.log` + a markdown table.  Re-run any candidate twice before deciding — single-run variance is ±10 blocks at this scale.

## MicroPython instance attribute storage — one allocation, not N

The intuition "each `self.foo = X` is one small allocation, so consolidating N attrs into a tuple saves N-1 allocations" is **wrong on MicroPython**.

Source: `.tools/micropython-v1.26.0/py/objtype.h:33` defines `mp_obj_instance_t` as `{ mp_obj_base_t base; mp_map_t members; mp_obj_t subobj[] }`.  The `mp_map_t` (`py/obj.h:481`) is a hash map with **one** allocated table array (`mp_map_elem_t *table; size_t alloc`).  When `__init__` writes N attrs, MP allocates one instance struct + one members table sized for ~32 or ~64 slots (next power-of-2 above used).  Removing 5 attrs leaves the same table — slots become empty in the existing allocation, nothing frees.  Adding a tuple ADDS one object.  Net allocation count: same or slightly worse.

Bench evidence: packing 6 connect-args (`username`, `password`, `will_topic`, `will_message`, `will_qos`, `will_retain`) from MQTTClient into a single `_connect_args` tuple — expected -5 1-blocks per instance, **measured 0**.  Free heap moved +64 bytes (noise).  Don't propose tuple consolidation as an MP/CP allocation-reduction pattern at small N.

**The pattern that *does* save allocations**: removing an unused class entirely.  Eliminating `MQTTPublisher` (one class + one method + one `__all__` export) freed **7 1-blocks** and **+197 `max_free_sz` blocks (+3.15 KB contiguous)** on Pi Pico W MP.  Class machinery — the type object, qstr-interned name, method bytecode, `__init__` code object — costs far more per-class than per-attribute storage costs per-attr.  When auditing for footprint, **count classes and method counts, not attribute counts**.

## Eager adapter import perturbs downstream heap layout

Pattern that looked appealing: replace `chumicro_sockets`'s runtime-gated lazy `from chumicro_sockets._adapters import cp/mp/cpython` inside each entry-point function with a one-shot eager import at module load (`import sys; if sys.implementation.name == "circuitpython": from chumicro_sockets._adapters import cp as _eager_adapter`).  The hypothesis: the adapter's compile-scratch lands at post_import (where the end-of-init gc.collect can defragment it) instead of at post_connect (interleaved with connect-time transients).

Bench result on Pi Pico W MP: post_import held (`max_free_sz` unchanged at 6173 blocks) but **post_connect dropped to 5262 blocks — `-911` blocks = `-14.5 KB` contiguous capacity** lost.  Same shape as the trimming-docstrings / inlining-helpers anti-pattern: **moving allocations earlier in the import chain perturbs where downstream allocations land**.  The pre-existing layout was load-bearing without the change being obvious.

Don't propose eager adapter imports as a fragmentation fix.  The lazy pattern is the right one.

## Mid-module gc.collect — caveat: the file has to be imported

The pattern `gc.collect()` inserted mid-file between two large blocks (e.g. between encoder and decoder sections of a 400-line module) extends the gc.collect-at-boundaries idea — `import gc` lives at the top of the file with the other imports.  Iter 12 of the original chumicro_mqtt sweep showed +5 blocks on `_wire.py`; this session's iter 03 showed **+944 bytes free at post_import on Pi Pico W CP custom firmware** when applied mid-`chumicro_msgpack/_pure.py`.

The catch: `_pure` is **not** always imported.  `chumicro_msgpack/__init__.py` tries `from msgpack import pack, unpack` first on CircuitPython and only falls back to `_pure` when the native module is absent.  On stock CP firmware that ships native `msgpack`, the mid-module gc.collect inside `_pure` never executes (the file isn't loaded).  On MP and on CP builds that strip native `msgpack` (e.g. custom builds), `_pure` is imported and the gc.collect fires.

When evaluating "mid-module gc.collect as a defrag pattern", **verify the file is on the actual import path first** (deploy the probe with the change and check whether free/floor moves).  If a file isn't loaded in the test chain, the change is a no-op and the bench will show flat numbers regardless of how plausible the placement looks.

## Measuring contiguous floor on CircuitPython — bytearray probe

CircuitPython has no equivalent of MicroPython's `micropython.mem_info(1)` and no equivalent of `max_free_sz`.  `gc.mem_free()` only reports total free bytes — not how that free pool is split across the heap.  A 110 KB free pool with a 25 KB largest contiguous chunk and a 110 KB free pool with a 100 KB largest contiguous chunk are both "110 KB free" but the first will fail any single allocation above 25 KB.

The diagnostic substitute: `bytearray(N)` allocation probes at a stepped set of sizes after `gc.collect`, report the **largest N that succeeded** as the contiguous floor.  `projects/frag_probe_runtime_cp/app.py` ships the reference shape with probe sizes `(100_000, 75_000, 60_000, 50_000, 40_000, 30_000, 25_000, 20_000, 16_384, 12_000, 8_192, 4_096)`.  Each probe `del`s its buffer + `gc.collect`s before trying the next size, so probe pressure doesn't stack.

Set the probe ceiling tighter than free heap (probing at ~free-heap fails on bookkeeping overhead even with zero fragmentation and yields a misleading floor).  Set granularity finer near the load-bearing threshold for the upstream consumer — for TLS handshake stress on `mqtt_tls_probe`, ~25 KB is the make-or-break point, so include 25_000 / 30_000 / 40_000 in the step set.

## publish / publish_raw wrapper-doubling

chumicro_mqtt's `client.py` exposed six methods where three would have sufficed: `publish` + `publish_raw`, `subscribe` + `subscribe_raw`, `unsubscribe` + `unsubscribe_raw`.  Each `_raw` variant has the identical signature, identical docstring shape, identical body — except the unsuffixed version makes one extra `self._prefixed_topic(topic)` call before delegating.  ~100 lines of `client.py` were pure duplication; three extra class-dict entries on every `MQTTClient` instance; three extra qstr-interned method names + bytecode objects in flash.

Four prior `/audit-embedded mqtt` passes (commits `3444f9e1`, `061c5850`, `423cbc31`, `ddcf2b9f`) caught real flash + RAM issues (InFlightTable→dict, Awaiting→strings, `__all__` trim, import-time fragmentation) but walked past the wrapper-doubling.  The skill's §1 *"Cargo-cult class methods"* bullet checks for *un-called* methods — `publish_raw` IS called by external consumers (system-topic publishes that need to bypass the `root_topic` prefix scheme), so it didn't trip that check.  Static lint doesn't flag it either — both methods have callers.  The pattern only shows up when you specifically diff each `*_raw` body against its unsuffixed sibling and notice the delta is a single helper call.

**Pattern:** when a library exposes a method pair where one calls the other after applying a single transform (prefix-resolver, normalizer, default-applier, encoder/decoder), the pair is wrapper-doubling.  Each pair costs N lines of duplicated body, N lines of duplicated docstring, and one extra class-dict entry on every instance.  Default fix: collapse to one method with a binary kwarg — `prefixed=True` / `normalize=False` / `encoded=True`.  The chumicro_mqtt `set_will(..., prefixed=False)` method already uses this shape; the public surface stays minimal.

**Audit move:** `grep -rE 'def \w+_raw\(|def \w+_unencoded\(|def \w+_unprefixed\(|def raw_\w+\('` across `libraries/<name>/src/`.  For every match, diff the body against the unsuffixed sibling — single-helper-call delta = collapse candidate.  Same gap likely applies to other libraries audit-embedded has previously cleared, so include the grep in any audit re-pass on a previously-audited library.

## Wrapper-doubling workspace re-pass

2026-05-23 re-pass of `sockets`, `websockets`, `requests`, `http_server`, `msgpack`, `runner`, `timing` with the new §1 wrapper-doubling check.  The literal-suffix grep (`def \w+_raw\(` etc.) returned zero — none of the 7 libraries used the `_raw` naming convention.  Structural search across method pairs surfaced 5 candidates; 2 collapsed, 3 left in place.  The exception classes are now codified in SKILL.md §1.

**Collapsed:**

- **`HttpServer.respond` → drop, callers use module-level `build_response`.**  `respond` was `return build_response(status, body=body, json=json, text=text, html=html, headers=headers)` — pure delegation.  Only caller was a test that asserted `respond == build_response`.  Method + test removed; module-level builder is the single entry point.  chumicro_http_server 0.12.0 → 0.13.0.
- **`Heartbeat.is_due` → `_is_due` (privatize).**  `is_due` was the query-only sibling of `.poll()` which called it.  Every real caller in the workspace (5 examples, runner runtime_control, bench paths) used `.poll()`; `is_due` was only exercised by tests that mirrored their `.poll()` neighbors.  Privatize beats collapse-to-kwarg here because the kwarg shape (`poll(now_ms, advance=False)`) would have invented an opt-out nobody had asked for.  chumicro_timing 0.3.7 → 0.4.0.

**Left in place (exception classes):**

- **`requests.HttpClient.get / post / put / patch / delete`** all forward to `_start_request("METHOD", ...)`.  Structural wrapper-doubling, but `requests.get(url)` is the universally-known PyPI-`requests` convention; collapse to `request(method, ...)` would trade ergonomics for one qstr per verb in flash.  Exception class 1 (PyPI convention).
- **`msgpack.pack` / `packb`, `unpack` / `unpackb`.**  `pack` is `stream.write(packb(obj))`; `unpack` is `unpackb(stream.read())`.  Matches the PyPI-`msgpack` API contract callers will reach for.  Exception class 1.
- **`Runner.add_periodic` vs `Runner.add(handler=..., period_ms=...)`.**  `add_periodic(handler, 500)` reads cleaner than the kwarg form because `add()`'s first positional slot is `task`.  ~25 call sites across docs / examples / tests would each gain kwarg noise.  Exception class 2 (positional/kwarg asymmetry).

**Lesson for the skill:** the structural match (two methods, one helper-call body delta) is necessary but not sufficient for a collapse recommendation.  Apply the three exception tests before recommending: is one method the established PyPI-library convention?  Does the kwarg-collapse force every caller to switch to kwarg syntax for a positional their callers prefer?  Is the lighter method actually used by anyone outside the wrapper itself (if not, privatize beats kwarg-merge)?
