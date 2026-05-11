---
name: audit-embedded
description: On-device audit of a single device library through an embedded-systems lens — flash footprint, RAM-at-import, heap allocation in hot paths, fragmentation, runtime branches, `const()` / `memoryview` / `__slots__` reality on MicroPython and CircuitPython, FAT cluster overhead, docs-match-code validation, and dynamic instrumentation when static review can't answer the question. Complements (does not replace) `/audit-library`. Use when a library is bound for boards with 256 KB RAM and 4 MB flash and you want a focused pass on whether it pulls its weight there.
---

# Embedded-library audit

Audit one device library (`libraries/<name>/`) through the **on-device lens**: does the code respect the realities of MicroPython and CircuitPython on a 256 KB-RAM / 4 MB-flash microcontroller? Output a prioritised punch-list, then execute the high-confidence items with the user's go-ahead.

Argument: the library name (matches the folder under `libraries/`). Example: `/audit-embedded mqtt`, `/audit-embedded wifi`, `/audit-embedded sockets`.

## Scope

Device libraries only. `workbench/<name>/` is host-only CPython — none of these dimensions apply there. `support/test_harness/` is borderline (it does run on devices); if you point this skill at it, only the device-side modules count.

This skill runs **orthogonally to `/audit-library`**. They look for different things and both can be useful on the same library at different times.

| Skill | Lens | Cares about |
|-------|------|-------------|
| `/audit-library` | Reader / maintainer | Honesty, dead code, method shape, duplication, top-to-bottom readability, peer-LOC outliers |
| `/audit-embedded` | The board running the code | Flash bytes, import-time RAM, hot-path allocation, fragmentation, runtime branches, `const()` / `memoryview` / `__slots__` reality, FAT overhead, doc-vs-code drift |

Tag a finding `cross-skill` and escalate when it really belongs in the other audit.

## Audit philosophy

Minimum board class is 256 KB MCU RAM + 4 MB flash ([Decision 0015](../../../plans/decisions/0015-board-architecture-support.md)). Everything below follows from that:

* **Less code is better than more code.** Flash is a hard cap and `.py` source ships verbatim under `mip` and `circup`. Class explosion and helper-bucket modules cost flash bytes, FAT cluster waste, and parse-time RAM. Form is good; size is the constraint. Don't add abstractions without a caller demanding them.
* **The heap fragments under the kind of work libraries do.** Long-lived state interleaved with short-lived buffers leaves the small-block tier full of holes. A 100-byte allocation can fail with 20 KB free if every free slot is 40 bytes. Reserve buffers up front; reuse them; pass `memoryview` slices instead of copies. See [`plans/patterns.md` "Static recv buffer + memoryview window"](../../../plans/patterns.md).
* **CPython habits leak.** `from typing import Optional`, `from __future__ import annotations`, eager top-of-file imports, `dataclasses.dataclass`, f-strings inside hot loops — all benign on a laptop, all costly or broken on-device. Pyright suggestions that improve a host program may regress a library.
* **The code is the source of truth.** When docs or docstrings disagree with the code, the code wins by default — but ask the user when ambiguous (the doc may encode the original intent).
* **CPU matters less than memory.** A 250 MHz dual-core RP2350 is plenty for scripted networking work *unless* a tight loop allocates per iteration. Then the GC pause dominates. The audit cares about allocation-per-tick more than raw cycles.

## Audit dimensions

Run through each. Note findings as a punch-list with `file:line` + one-line description + dimension tag. Tag taxonomy is listed in **Output format** at the bottom.

### 1. Flash footprint — every byte ships

Source files land on a small FAT filesystem; `.mpy` ships from the same source. Less surface = less flash, less parse-time RAM, less bytecode.

* **Speculative classes.** A class with one instance, no subclasses, and 4-5 small methods is often a module with extra ceremony. If callers only need 2-3 functions, propose the dataclass-and-namespace shape (module-level state if there's truly one instance, or top-level functions if state can be parameter-passed).
* **Excess `__init__.py` content.** Re-export-only `__init__.py` files are the convention; an `__init__.py` over ~100 lines doing real work hides the actual modules from grep and inflates the always-loaded top of the package. Compare across the repo: `wc -l libraries/*/src/chumicro_*/__init__.py` (most sit at 11–100 lines; the outlier is the candidate). The 458-line `chumicro_sockets/__init__.py` is the current outlier — flag if there's nothing similar in the cohort.
* **Many small files.** CIRCUITPY's FAT filesystem rounds every file up to the cluster size (typically 512 B or 1024 B; verify with `os.statvfs("/")` from REPL). Five tiny modules at 200 B each cost ~2.5 KB of cluster waste on top of the 1 KB of source. The `chumicro_mqtt._wire` module's own header documents the historical merge ("shipping them as four files cost ~16 KB of FAT cluster waste on Pi Pico W") — that's the reference precedent. **Threshold:** if the library has 4+ modules each under ~1 KB of real code and the dependency graph between them is tight (one calls the next which calls the next), propose consolidation.
* **Long docstrings and comments.** `.mpy` compilation drops docstrings and comments, so on-device bytecode is unaffected. But `.py` source ships under `mip` and the FAT cluster math applies. Multi-paragraph docstrings re-explaining the obvious, or block comments narrating history ("previously this did X"), are flash bytes for nothing. The AGENTS.md "code comments" rule already forbids history-comments; the audit catches docstrings that re-state the signature in prose.
* **Cargo-cult class methods (peer-LOC trigger).** Same check as `/audit-library §8` — flag here when the method-set is wider than this library's own callers need *and* the un-called methods drop flash if removed.

### 2. RAM at import time — module top-level work

"Executing this code [module top level] creates objects in the MicroPython heap … these allocations constitute the RAM cost of loading a module" ([MicroPython constrained-runtime docs](https://docs.micropython.org/en/latest/reference/constrained.html)).

* **Top-level `import` of heavy modules.** `import ssl` materialises a substantial chunk of TLS code; `import json` and `import struct` are smaller but non-zero. If a symbol is reached from one cold-path function (firmware-update path, error-formatting path), push the import inside the function — module body stays lean, the import only happens when that path actually runs. Don't lazy-import primitives used on every tick (`struct`, `time`) — per-call dict lookup costs more than the load.
* **Top-level computed dicts / list literals / `.encode()` chains.** A `STATUS_MAP = {0: "OK", 1: "...", ...}` allocates the dict at import. If used in one cold path, push into the function. If used in a hot path, keep at module level.
* **Module-level eager hardware init.** `import board, busio` + `_DEFAULT_I2C = busio.I2C(...)` at module top instantiates hardware on import. Banned by [Decision 0010](../../../plans/decisions/0010-library-testability.md); flag if present.
* **Speculative pre-allocation at module top.** A 4 KB module-level scratch buffer that's used by exactly one rarely-called function pins RAM forever. Move into the function or into the consuming class's `__init__`.

### 3. Heap allocation in hot paths — the most common defect

Hot paths are: any `runner.tick()` callback, any `check(now_ms)` / `handle(now_ms)`, any inner loop in a decoder / parser / state machine, any per-message / per-frame / per-byte processing.

* **f-strings and `.format()` inside hot loops.** Every f-string allocates a new `str`. `log.info(f"got {n} bytes")` inside `handle()` allocates per tick even when log level filters the message. Replace with `log.info("got %d bytes", n)` (logger interpolates only on emit) or guard with `if log.is_enabled(INFO):`.
* **`dict(...)` / `{...}` / `[...]` literal inside a hot loop.** Reuse a module-level constant or a cleared scratch container.
* **`bytes(memoryview_slice)` to satisfy an API.** Forces a copy and defeats the point of holding the memoryview. Inspect the consumer — does it really need `bytes`, or does `unpack_from(fmt, buf, off)` / passing `memoryview` work?
* **`struct.unpack(fmt, view[a:b])` on MicroPython.** Has historically been patchy ([micropython#8747](https://github.com/micropython/micropython/issues/8747)); current chumicro-supported builds accept it (mqtt's `_wire.py` uses the pattern in production). If a finding turns up an MP build that rejects it, `struct.unpack_from(fmt, buf, offset)` is the portable fallback — no slice memoryview construction, no allocation either.
* **Per-byte loops where per-chunk works.** Same check as `/audit-library §5`. MicroPython frame allocation per call is real; on a 1024-byte recv buffer, per-byte processing is 1024 frames per tick. Restructure to per-chunk consumption (`view[start:start + needed]`).
* **`self.x.y.z.method()` chains used >2× in a loop body.** Cache to a local: `cb = self._state.callbacks.on_publish` before the loop, then call `cb(...)`. [MicroPython speed_python](https://docs.micropython.org/en/latest/reference/speed_python.html) is explicit about this.
* **`gc.collect()` in library code is a smell.** Legitimate use is *between* major state changes (post-handshake, post-bulk-decode, post-`connect()`) where pre-emptive collection is cheaper than letting the next allocation trigger one. `gc.collect()` inside `tick()` or `handle()` indicates the real fix is pre-allocation. Flag any `gc.collect()` and ask: does this hide a pre-allocation bug?

### 4. Heap fragmentation prevention

Fragmentation manifests as "100 bytes won't fit even though 20 KB is free." The cure is structural, not reactive.

* **Pre-allocated long-lived buffers** — recv buffers, parser accumulators, scratch buffers — should be constructed in `__init__` once. See [`patterns.md` "Static recv buffer + memoryview window"](../../../plans/patterns.md) and "_buf + cached _buf_view." Cross-check: every long-lived `bytearray` should have a sibling cached `memoryview` if it's sliced more than once.
* **`bytearray.extend` in a hot path** — three allocations per call (alloc bigger, copy old, copy new, free old). Audit the use site: does a fixed buffer with slice-assign (`buf[a:b] = data`) and a write cursor work instead?
* **Front-of-bytearray consumption** — `self._buffer = bytearray(self._buffer[N:])` churns the small-tier. Use the read-cursor pattern from `chumicro_requests._wire.ResponseParser._consume` instead. Flag if seen.
* **Per-iteration `bytearray(N)`** — the worst case. Reuse a steady-state buffer and only allocate fresh when the size genuinely exceeds capacity ([`patterns.md` "Reuse buffers; only allocate fresh"](../../../plans/patterns.md)).
* **String concatenation in a loop** — `result = result + chunk` allocates a new string each iteration. Use `"".join(parts)` after collecting into a list, or write into a pre-allocated bytearray.

### 5. Runtime-specific branches — CP vs MP vs CPython

Three runtimes ([Decision 0049](../../../plans/decisions/0049-three-runtime-trinity.md)), three behaviour profiles, multiple correct patterns.

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

### 6. Import hygiene

* **Relative imports in `libraries/*/src/`.** Banned — CircuitPython RAM-mode deploys `exec()` modules without a `__package__` binding, so `from .helpers import x` raises `ImportError`. Use `from chumicro_<name>.helpers import x`. Enforced by ruff TID252 but the audit catches edge cases (deep relative imports, parent-package imports).
* **Dotted-deep imports inside a package.** `from chumicro_<name>._wire._codec import encode_string` is fine if `_codec` is a real module, suspicious if the dotted path navigates through compatibility re-exports. Trace the resolution; if there's a shim layer, propose flattening.
* **Unused imports.** Cheap to spot via `ruff check`; cheap flash + RAM savings.
* **Top-level imports that should be lazy** — see dimension 2.
* **Lazy imports that should be top-level** — `struct`, `time`, `gc`, `sys`, `errno` are called from many sites; lazy-importing them adds per-call dict lookup with no offsetting benefit.

### 7. Code shape for embedded

Audit each of these patterns honestly against the actual MicroPython / CircuitPython behavior, not folklore:

* **`micropython.const()` use.**
  * `_FOO = const(7)` — underscore-prefixed constants are *hidden* by the MicroPython parser; not stored as module globals, "does not take up any memory during execution" ([MicroPython `micropython` module docs](https://docs.micropython.org/en/latest/library/micropython.html)). Implemented in CircuitPython too (gated on `MICROPY_COMP_CONST`; see [circuitpython/tests/micropython/const.py](https://github.com/adafruit/circuitpython/blob/main/tests/micropython/const.py)). The CPython fallback (`def const(v): return v`) makes the pattern safe everywhere.
  * **Audit checks:**
    * Module-level uppercase int literals that look like constants — `MAX_RETRY = 5` — should usually be `_MAX_RETRY = const(5)` if the name is internal-only. If the name is in `__all__` and external callers read it, keep the public-name form (no underscore, no `const()` — they pay an external-API cost).
    * `const(some_func())` or `const(other_constant + 1)` where the argument isn't a compile-time-foldable literal — defeats folding silently. Inline the literal or compute once at module top without `const()`.
* **`memoryview` use.**
  * Verified gotchas: `bytes(mv)` copies; `mv.decode()` doesn't exist on MP; cached views over a bytearray must be released before the bytearray resizes (see [`patterns.md` "_buf + cached _buf_view"](../../../plans/patterns.md)).
  * **Audit checks:**
    * Every long-lived bytearray sliced more than once should have a cached sibling `memoryview` constructed in `__init__`. Per-access `memoryview(self._buf)[:n]` allocates a fresh view-object each time.
    * `bytes(view[a:b])` passed to `struct.unpack` — replace with `unpack_from(fmt, buf, offset)`.
    * `memoryview` returned from a public method whose lifetime extends past the underlying buffer's next mutation — recipe for garbage reads. Document the lifetime contract or return a `bytes()` copy at the boundary.
* **`__slots__` reality.**
  * **MicroPython does not implement `__slots__`** ([discussion #13745](https://github.com/orgs/micropython/discussions/13745)). The syntax parses but the instance still gets a dict — no RAM saving on-device. CircuitPython inherits this. CPython does implement it (saves the dict, locks attributes).
  * **Audit answer:** `__slots__` is a *CPython-test* feature in this codebase, not an on-device feature. Keep it only where CPython tests benefit from attribute-locking semantics (catches typos in mock setup, freezes the public attribute set). Drop it where it's noise. **Don't add new `__slots__` to a class with one instance** — costs source lines, saves nothing on-device, locks attribute set on CPython for no benefit.
  * Existing `__slots__` in `chumicro_mqtt._wire.PacketPublish` / `client.MQTTClient` are the reference precedent (high-instance-count or attribute-discipline classes); audit on the same basis.
* **Descriptive names everywhere (Decision 0022).** Already enforced by `CHU001`; the audit-embedded angle is that `buf` / `mv` / `_pv` / `_bv` (cached-view shorthand) are *not* in the whitelisted abbreviation set despite appearing in patterns. If the audit sees one-letter view variables in library code, flag — `_payload_view` over `_pv`.
* **Pre-encoded byte literals.** `PACKET_PINGREQ = b"\xc0\x00"` (module-level pre-encoded constant) beats encoding on demand. Look for `bytes([0xc0, 0x00])` or `struct.pack(...)` for fixed packets — usually a candidate for module-level pre-encoding.

### 8. Comments and docstrings — flash bytes for nothing

The "code comments" rule in AGENTS.md says comments document the *why* of current code. The embedded angle adds: source ships under `mip`, so every comment line is a flash byte. `.mpy` strips them; the source distribution doesn't.

* **Multi-paragraph docstrings that re-state the signature in prose.** Flag — collapse to one sentence (or drop, if the name is self-evident).
* **Block comments narrating history.** "Previously this returned a list, we switched to deque for…" — belongs in the commit message. Delete.
* **Stale TODO / FIXME / XXX.** Same. Delete unless actionable now.
* **Docstring examples that drift from the API.** A docstring `>>> client.subscribe("topic")` while the method is now `client.subscribe("topic", qos=0)` — fix the example or drop it. Doctests don't run on-device anyway.

### 9. Docs match code — code is the source of truth

The library's `docs/guide.md`, the library's `README.md`, the docstrings in `src/`, and any examples under `examples/` make claims about the API. Each claim is a candidate for drift.

* **Every CLI command / flag mentioned in docs:** does it still exist in the code with the documented shape? Grep the code for the flag name; if absent, the doc is wrong. Default: fix the doc to match the code.
* **Every public symbol mentioned in docs:** still exported from `__all__`? Same parameter list? Same return-shape?
* **Every error class / exception mentioned in docs:** still raised by the code path described? `git log -S "ExceptionName"` to see if it was renamed.
* **Every config key / option mentioned in docs:** still read by the code with the same default?
* **Every code example in docs:** does it import successfully against the current code? Can it run on at least CPython without modification?
* **Ambiguous case:** doc says X is supported but code is silent on X. Could be an aspirational claim never implemented, or a regression that removed the feature. **Ask the user** which way to resolve — don't silently delete documented features.

### 10. Validation via instrumentation — when static review isn't enough

Some claims can only be verified dynamically. The audit should propose (and, with sign-off, execute) temporary instrumentation to validate or refute:

* **"This is a hot-path allocation"** — wrap the suspect section with `before = gc.mem_alloc(); … ; after = gc.mem_alloc(); print(after - before)` and run a representative load. If the per-iteration delta is non-zero, the finding is real. Remove the instrumentation before committing.
* **"This loop misses the runner tick budget"** — wrap with `t0 = ticks_ms(); … ; t1 = ticks_ms(); print(ticks_diff(t1, t0))`. Compare against the configured tick budget (often 10 ms).
* **"This buffer fragments the heap"** — record `gc.mem_free()` before and after N iterations; trend over many iterations exposes fragmentation. Bench against an alternative that pre-allocates.
* **"This `__init__.py` re-export costs RAM on import"** — `before = gc.mem_alloc(); import chumicro_<name>; after = gc.mem_alloc(); print(after - before)` in a fresh REPL.
* **Instrumentation lives in a temporary branch** — never commit `print(gc.mem_alloc())` to library source. The validation is for the audit; the diff for the user is whatever cleanup the validation justifies.

### 11. Reference-implementation reading — `.tools/`

When a behavior is uncertain (does CircuitPython actually no-op `__slots__`? does this MP build accept `unpack(memoryview)`?), check the runtime source under `.tools/` (gitignored, populated by `python scripts/run.py prepare-circuitpython` / `prepare-micropython`). The runtime source is authoritative when the docs are silent. Cite the path in the punch-list finding (`.tools/circuitpython/py/objslot.c` or similar) so the user can verify.

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
5. **Run the audit dimensions.** Note findings in a list.
6. **Where static review is inconclusive, propose instrumentation.** Don't execute without sign-off — instrumentation runs change the running code temporarily and the user may have a deploy in flight.
7. **Score each finding by confidence:**
   * **High** — banned syntax (`from __future__`, bare `TimeoutError`, missing runtime marker), unused imports, `bytes(view[a:b])` to `unpack`, dead constants. Safe to fix without further discussion.
   * **Medium** — `__init__.py` consolidation proposals, file-count consolidations, lazy-import recommendations, `__slots__` drops, structural memoryview-caching changes. Benefit from a second opinion.
   * **Low** — doc-vs-code ambiguities where the user must decide which side is correct. Escalate via the punch-list.
8. **Present the punch-list to the user.** Group by dimension. Flag taste calls separately.
9. **Execute high-confidence items as one cohesive commit.** Run the library's tests + every sibling package that imports from it after each batch. Hardware-verify if the change touches a deploy / probe / transport path (Pi Pico W CP / MP boards from `devices.yml` defaults).
10. **Execute medium-confidence items as separate commits, one per finding.** Per the user's preference: small reversible commits beat one big merge.
11. **For doc-vs-code drift:**
    * If the code is clearly right and the doc is stale — fix the doc, no question to user.
    * If the doc encodes intent the code lost (a feature that regressed silently) — surface as a separate finding for user decision, don't auto-resolve.
12. **For instrumentation findings — three commits:**
    * Commit 1: instrumentation added (so the validation is reproducible).
    * Commit 2: the fix justified by the instrumentation.
    * Commit 3: instrumentation removed.
    Or, equivalent: instrumentation lives only in a stash that the audit log references in the commit message of the fix.
13. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.** Same rule as `/audit-library`.

## Anti-patterns

* **Don't apply embedded micro-optimizations to workbench packages.** `workbench/<name>/` is CPython-only; flash and heap don't apply there. The `--coverage-threshold` math is the only carryover.
* **Don't `gc.collect()` everywhere to fix a fragmentation finding.** The fix is pre-allocation; `gc.collect()` is a thermometer, not a treatment.
* **Don't add `__slots__` "for performance" without measuring.** Verified: no on-device benefit on MP/CP. The on-CPython benefit is attribute-locking, not RAM. Keep existing instances; don't proliferate.
* **Don't consolidate modules just to win the file-count game.** If two modules legitimately have separate roles (e.g. wire-protocol code vs orchestration code), the cluster cost is the price of clarity. Consolidate when the dependency graph is a chain (A → B → C and nothing else calls B or C); leave when modules serve distinct purposes with multiple consumers.
* **Don't lazy-import primitives used on every tick.** `struct`, `time`, `gc`, `sys`, `errno`, `socket` (when used) belong at module top in their consuming module — the per-call dict lookup of a function-scoped import costs more than the load.
* **Don't commit instrumentation.** `print(gc.mem_alloc())` in library source ships to devices. Remove before committing.
* **Don't override the user on doc-vs-code ambiguity.** Code-as-source-of-truth is the *default*; the user's judgment overrides when an aspirational doc claim represents an intentional roadmap.
* **Don't break public API to win an audit dimension.** A symbol exported from `__all__` and imported by sibling libraries / workbench / examples is out-of-scope for renames in this pass; flag separately.
* **Don't ignore the `/audit-library` lens.** A finding that's really about code shape, dead code, or readability belongs in `/audit-library`. Cross-tag and escalate.

## After the audit

If the audit produced commits:

* Bump the library's `VERSION` file *once* at the end of the audit pass — not per commit (same rule as `/audit-library`).
* Run the `task-checkpoint` skill: `python scripts/run.py preflight --coverage-threshold 94` to confirm the full sweep passes.
* If the change touched device libraries that own time / I/O, also run `python scripts/run.py test-libraries-functional --library <name>` to hardware-verify against `devices.yml` defaults.
* If the change touched a hot path, run a real-board sanity check — `chumicro-workspace deploy --device <board>` + observe in `chumicro-workspace repl --tail` for at least one minute under load.
* Run `python scripts/run.py check-version` and `python scripts/run.py check-api` if the library has a public API surface.
* Update any docstrings the user-facing API rewrites invalidated. The audit's own §9 found these; don't re-introduce them.

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
* `ram-imp` — RAM consumed at module import time (top-level work, eager initialisation).
* `heap` — heap allocation in hot paths.
* `frag` — fragmentation prevention (pre-allocation, cached views, buffer reuse).
* `runtime` — runtime-specific code (CP/MP/CPython branches, runtime markers, missing-builtin handling).
* `imports` — import hygiene (relative imports, unused, wrong-direction lazy).
* `shape` — embedded-specific code shape (`const()`, `memoryview`, `__slots__` reality, pre-encoded literals, attribute-chain caching).
* `docs` — docs-match-code drift (default: fix doc to match code).
* `cpu` — tight-loop CPU budget under runner ticks.
* `cross-skill` — finding belongs in `/audit-library`; escalate.

The goal: same library, fewer flash bytes, less import-time RAM, no hot-path allocations, no runtime-branch surprises, docs that match the code as-shipped. Tests still pass, preflight green, project-policy invariants enforced.
