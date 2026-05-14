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

A chumicro_mqtt bench session burned an hour theorising wifi-settle timing for an `ECONNABORTED`.  Four `print()` lines added to `connect_tcp` on-device immediately showed `host=test.mosquitto.org` (from `secrets.toml`) instead of the expected `host=172.16.1.15`, and the broker-side mosquitto log confirmed the connections-and-immediately-closes pattern.

**Pattern:** when a network call fails inconsistently across contexts (succeeds from REPL, fails from `main.py`), it's tempting to explain as a wifi-settle / lwIP-TIME_WAIT / cyw43-power-save race.  None of those are usually it.  The fastest path is to instrument the function — `print()` statements around `socket.getaddrinfo`, `sock.connect`, the factory closure — printing the **arguments it's actually receiving**.  The diagnosis you can't theorise into is usually "the arguments aren't what you think they are."  Static review and theorising can't substitute for "what value is this function actually called with right now."  Tag the finding as `cpu` or `runtime` depending on where the fix lands.

## Prior-art side-by-side compare

A chumicro_mqtt audit took 30 minutes for a side-by-side against `~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` — a previous-generation implementation the user pointed at.  Surfaced: the missing intact-delivery tier (the current library treated every PUBLISH > rx_buffer_size as oversized; the reference distinguished "fits in heap, deliver intact" from "way too big, discard via rolling sink"), the missing fixed `DEGRADED_BUFFER_SIZE` constant, and the missing SUBACK 0x80-rejection auto-fault.  None of those had been flagged in three prior audit passes.

**Pattern:** reference comparison is the single highest-yield move when prior art exists.  Read the reference top-to-bottom under the same audit lens; compare along three axes: (a) **missing concepts** — what tiers / modes / lifecycle phases does the reference distinguish that the current library has collapsed? (b) **buffer sizing** — what fixed-size buffers does the reference reserve where the current library allocates dynamically, and vice versa? (c) **error pathways** — does the reference raise / disconnect / fault on inputs the current library silently accepts?  Cite the reference path in punch-list findings so the user can verify the comparison.
