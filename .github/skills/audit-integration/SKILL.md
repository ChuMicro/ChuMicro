---
name: audit-integration
description: Code-quality audit across two or more libraries that interact. Looks for duplicated handoff logic, leaky abstractions, dependency-direction issues, parallel implementations that should converge. Use when two libraries' boundary feels awkward, or when a feature spans multiple libraries and the seam is showing.
---

# Cross-library integration audit

Audit the boundary between two or more libraries.  Where `/audit-library` looks *inside* one package, this skill looks *between* packages — at the shapes that flow across the boundary, the assumptions each side makes about the other, and the places where the seam is leaking.

## Scope

Argument: comma-separated library names.  Examples:

* `/audit-integration wifi,sockets` — when wifi hands off to sockets
* `/audit-integration mqtt,sockets,timing` — three-library chain
* `/audit-integration deploy,workspace` — workbench packages crossing

This skill does not deeply audit any single library's internals (use `/audit-library` for that) and does not propose architectural changes that span the whole mono-repo (use `/audit-workspace`).  The lens here is: **the interface between these libraries, and only that interface.**

**Duck-typed contracts naturally expand the scope.**  If the "boundary" is a duck-typed protocol — a method shape that multiple libraries implement without a shared ABC / Protocol class — list every implementer in the workspace before starting and treat them as the audit's natural scope.  `/audit-integration mqtt,timing` looks like a pair, but if the real boundary is `check(now_ms) -> bool` / `handle(now_ms)` and seven libraries implement it, the audit is N-way.  The pair-wise framing hides the systemic problem: divergence is *silent* without a shared type to enforce the shape, so all you can do is enumerate consumers and compare.

## Audit philosophy

Cross-library code reveals integration-level problems that single-library audits miss:

* **Leaky abstractions** — library A exposes a concept that only library B understands.
* **Parallel implementations** — both libraries solve the same sub-problem differently.
* **Wrong-side work** — library A does work that conceptually belongs to library B, or vice versa.
* **Handoff churn** — the same value gets reshaped 3× as it crosses 3 libraries.
* **Coupling without cohesion** — libraries depend on each other but for unrelated reasons; the boundary needs a re-cut.
* **Same problem, three layers** — when one layer of an integration drifts from the canonical shape, the other two usually drifted too, because they reinforce each other.  A divergent constructor API makes the canonical test fake awkward to use, so a parallel test fake gets built; the divergent shape also encourages a different internal pattern for the same operation.  Finding one is a strong signal to hunt the other two.  Concrete instance from the 2026-05-11 timing/runner audit: five libraries diverged from the documented `ticks: object` DI shape *and* refetched `ticks_ms()` mid-tick *and* (in one case) shipped a parallel `TickClock` fake instead of using `chumicro_timing.testing.FakeTicks`.

The goal isn't to merge libraries (that's `/audit-workspace`'s call); it's to make the boundary **honest** — each side does the work it conceptually owns, with a clean shape flowing across.

## Audit dimensions

### 1. Type / value flow across the boundary

* **What types flow across?**  Map every public function each library exposes that the other(s) call.  Note each call site's input + output shape.
* **Are simple values being shaped into complex types just to cross the boundary?**  E.g., a function takes a `WifiConfig` dataclass when it really only uses one field.  Pass the field directly.
* **Are complex types being decomposed at every boundary?**  E.g., wifi returns a `Connection` object that sockets immediately unpacks into `(host, ip, dns)` and discards the object.  Either the object isn't earning its keep, or the unpacking should move into wifi.
* **Are there Optional[X] + None-checks repeated on both sides?**  Often the producer should validate-or-raise; the consumer shouldn't have to re-handle absent.
* **Awkward construction in tests = constructor-API smell.**  When every test does `ticks_ms_func=fake.ticks_ms, ticks_add_func=fake.ticks_add, ticks_diff_func=fake.ticks_diff` at the call site (or any other multi-line unpacking that's identical at every site), the production constructor is the wrong shape — the test is paying the cost of the bad API every time, and downstream consumers will too.  Cleaner: a single `ticks` object passed in.  Read each library's `tests/` setup helpers; awkward construction is a high-signal smell because tests are the first place a bad API hurts.

### 2. Dependency direction

* **Is the dependency direction sensible?**  `chumicro-mqtt` depending on `chumicro-sockets` makes sense (MQTT is a sockets consumer).  `chumicro-sockets` depending on `chumicro-mqtt` would not.
* **Are there cycles?**  Direct cycles fail import; subtle cycles work but signal a layering problem.  Check `pyproject.toml` `dependencies =` plus actual `import` statements.
* **Are dependencies declared accurately?**  A library that imports `chumicro_X` but doesn't list it in `dependencies` is a future packaging bug.  Run a quick grep: every `import chumicro_*` should appear in `pyproject.toml`.
* **Decision 0042 check:** per `plans/decisions/0042-library-dependency-policy.md`, certain libraries (e.g., `chumicro-events`) are zero-dep by design.  Verify the audit doesn't propose changes that break that.

### 3. Duplicated logic across the boundary

* **Same operation implemented twice.**  E.g., wifi has a "wait for IP" loop; sockets has a "wait for connection" loop with the same retry-backoff logic.  Either consolidate, or accept the duplication if the loops genuinely diverge in the future.
* **Parallel state machines.**  Both libraries track "connecting / connected / failed" with slightly different vocabulary.  Pick one vocabulary; the other library translates at the boundary.
* **Re-validation of values that were already validated.**  Library A's output went through validation; library B re-validates the same value.  Trust the producer, or move validation to where it's needed.
* **Doc-comment-says-X-but-code-says-Y is a high-signal divergence smell.**  Grep the boundary code for forward-looking phrasing: *"until a third X consumer arrives"*, *"when X happens"*, *"callers like Y already pass a view"*.  Each is a claim about a *trigger condition*; check whether the trigger has been hit (concrete from the 2026-05-11 wire.py audit: websockets' `_wire.py` claimed callers "already pass a view" while `_session.py:551` actually returned `bytes(...)` — the comment was right, the code drifted away from it; a separate websockets comment named "a third HTTP/1.1-aware consumer" as the trigger for extraction, and the third consumer — chumicro-http-server — had been shipped a year earlier).  When two of these stack, you have systemic drift, not isolated bugs.
* **Same library, multiple drifts.**  Once you find one divergence in library B from the canonical shape, widen the lens within that library before moving on.  Concrete from the wire.py audit: websockets diverged on (a) the recv-chunk return type, (b) the recv-buffer cap policy, (c) the dict insertion-order preservation — three independent drifts from the requests/http_server peer shape, none alone obvious.  After finding one, grep the library for the *other* dimensions before claiming "done."

### 4. Wrong-side work

The hardest pattern to spot.  Look for:

* **Library A does X for library B's benefit, but X has nothing to do with A's job.**  E.g., wifi formatting MQTT topic strings.
* **Library B reaches into A's internals.**  Importing `chumicro_<a>._internal` or relying on undocumented attributes.  The boundary is the public API; if B needs more, A should expose more (or B should do less).
* **Configuration that crosses the boundary in awkward shapes.**  E.g., wifi accepts a dict of MQTT options just to forward them to MQTT.  Either MQTT should be configured directly, or wifi shouldn't be the configuration entry point for MQTT.

### 5. Handoff churn

* **Same value reshaped multiple times.**  `(host, port)` → `Endpoint(host, port)` → `dict(host=, port=)` → `(host, port)` across three libraries.  Pick one shape and propagate.
* **Adapter / converter functions at every layer.**  When 3+ adapters in a single chain do nothing but reshape, the shapes are wrong.

### 6. Boundary contract clarity

* **Is there a Decision ADR for this boundary?**  Check `plans/decisions/` for the relevant numbers.  If no ADR exists for a boundary that has gotten complicated, propose one as a finding.
* **Are the libraries' README / public-API sections aligned?**  If wifi's README says it returns `IpAddress` but sockets expects `tuple[int, int, int, int]`, one of them is wrong.
* **Are there silent contracts?**  Things like "must call `.connect()` before `.send()`" enforced only by behaviour, not types.  Document or enforce.

### 7. chumicro-specific cross-library checks

These are non-negotiables that *only* surface at the boundary between libraries.

* **Runner contract: one `now_ms` per tick** (Decision [0014](../../../plans/decisions/0014-runner-pattern.md), enforced by `CHU013`).  When library B calls into library A's `check(now_ms)` / `handle(now_ms)` method, B must pass the *same* `now_ms` the runner gave it — never call `ticks_ms()` mid-tick to get a "fresh" value.  Mixing tick sources between libraries (e.g., one consumer uses `chumicro_timing.ticks_ms` while another rolls its own `time.monotonic()`-based shim) causes clock-domain misalignment, which manifests as deadlines firing on the wrong tick or never firing.  Audit checklist:
  * Does each tick-receiver use the supplied `now_ms` rather than re-fetching?
  * If two libraries share a tick budget, do they get the same `now_ms` value at every dispatch?
  * Are tests rolling their own timer instead of using `chumicro_timing.ticks_ms`?
  * **Optional-`now_ms` helper pattern** — when a helper is shared between user-entry callers (outside the tick loop, no `now_ms` available) and handle-path callers (inside the tick loop, `now_ms` in scope), it takes an optional `now_ms` kwarg that defaults to `None`: handle-path callers pass it through, user-entry callers leave it out and the helper captures a fresh `ticks_ms()` once.  Existing instances: `MQTTClient._deadline(offset_ms, *, now_ms=None)`, `_BaseSession._arm_pong_deadline(now_ms=None)`.  Don't fight this shape in audits — it's the codified solution to "two callers, two contexts" and `CHU013` recognizes the `if now_ms is None:` guard as the legitimate refetch.

* **chumicro-config manifest declarations** (Decision [0036](../../../plans/decisions/0036-chumicro-config-library.md)).  Every library that calls `chumicro_config.load_section(<name>)` or has a `<X>Config.from_dict()` method should declare `[tool.chumicro.config.sections.<name>]` in its `pyproject.toml` listing required + optional keys.  At deploy time, `chumicro_workspace.config_manifest` aggregates these and validates the merged config before bytes hit the device.  Audit any pair of libraries that consume runtime config; if either is missing a manifest, flag it.

* **Per-runtime adapter parity** (Decision [0049](../../../plans/decisions/0049-three-runtime-trinity.md)).  Each device library should ship CP + MP + CPython adapters / fakes with the same surface.  When auditing a pair of libraries:
  * Does each library have a `_adapters/{cp,mp,...}.py` (or `_adapters/base.py` + per-runtime subclass)?
  * Does the testing.py fake match the public surface?  Per Decision [0010](../../../plans/decisions/0010-library-testability.md).
  * Are runtime-specific files marked `__chumicro_runtimes__` (Decisions [0037](../../../plans/decisions/0037-runtime-file-marking.md), [0044](../../../plans/decisions/0044-deploy-time-runtime-filtering.md)) so they don't ship to the wrong runtime?

* **Decision [0042](../../../plans/decisions/0042-library-dependency-policy.md) compliance** — some libraries have explicit zero-dep policies (e.g., `chumicro-events` has zero chumicro deps and no library imports it).  Verify any cross-library imports the audit proposes don't violate that decision.

* **Pyproject deps match imports.**  Every `import chumicro_<name>` in `src/<libname>/` should appear in `<libname>/pyproject.toml` `dependencies = [...]`.  Run a quick grep to surface missing declarations — they're future packaging bugs.

* **Per-runtime divergence** — when CP + MP behave differently for the same library operation (e.g., DNS resolution, exclusive serial-port access), is that documented in the README *and* covered by both runtimes' functional tests?  Cross-runtime API drift surfaces at integration boundaries first.

* **Shared types crossing the boundary.**  When library A returns a chumicro-defined type (e.g., `chumicro_wifi.WifiState`), library B's import of that type creates a direct dep.  Verify the dep is intentional and declared.  Anonymous dicts / tuples crossing the boundary are usually fine; named types add coupling.

* **Workbench / library boundary** (Decisions [0032](../../../plans/decisions/0032-workbench-folder-promotion.md), [0052](../../../plans/decisions/0052-workbench-no-library-imports.md)) — host-side `workbench/*` packages must NOT `import chumicro_<libname>` from `libraries/`.  Strict.  Workbench tools that need on-device-shaped logic embed it as payload bytes (templates, scaffolds), never imports.  Audit any audit pair that crosses workbench↔library for this rule.

* **Streaming-parser conformance: shape, compaction, zero-copy hand-off.**  When two or more libraries each ship a streaming wire parser fed by `recv_into` on a shared scratch buffer, three sub-shapes diverge silently:
  * **Push vs pull API.**  Pull-style (mqtt PacketDecoder: parser owns the buffer + exposes `fill_buffer()` / `advance()` / `read_next()`, recv writes directly into it — zero-copy at the recv boundary) vs push-style (HTTP-shaped parsers in requests / http_server / websockets: client/connection owns the buffer + calls `parser.feed(view[:n])` — extra layer but more flexible when one recv may straddle multiple parser states).  Both are defensible; flag *unintentional* divergence within a library family.
  * **Compaction strategy on read-cursor parsers.**  Realloc-and-rebind (`self._buffer = bytearray(self._buffer[off:])`) vs in-place memmove.  The in-place shape is strictly better on MP/CP allocators (no per-compaction alloc).  Portable in-place patterns:
    * Fixed-size buffer + cached `memoryview` (the mqtt PacketDecoder shape) — compact via `view[:live] = view[off:length]`.  Best when the buffer never grows.
    * Growing buffer (HTTP parsers fed by `.extend()`) — compact via `self._buffer[:off] = b""` (slice-assign-empty).  Verified against `.tools/micropython-v1.26.0/py/objarray.c` + `.tools/circuitpython-10.2.0/py/objarray.c`: the non-grow path goes through `mp_seq_replace_slice_no_grow`, no `m_renew`.  `del bytearray[:n]` is NOT supported on MP/CP (returns `MP_OBJ_NULL` / "op not supported") — slice-assign-empty is the portable shape.
  * **CPython BufferError check before recommending in-place memmove.**  CPython refuses to resize a bytearray with active memoryview exports.  Before flagging "switch from realloc to in-place," grep the parser for sites that take a memoryview *on the buffer being resized* — if any caller holds the view across the resize (e.g., a `source = memoryview(self._buffer)[off:off+n]` used to hand zero-copy bytes to another method before `_consume`), the in-place change fails BufferError on CPython.  Fix: release the view (`source = None`) before the in-place op.  MP/CP don't track exports, so this is a CPython-specific concern but it's caught by host-side tests, so the fix is mandatory.
  * **Zero-copy hand-off across module boundaries.**  When library A reads via `socket.recv_into(self._recv_view[:cap], cap)` and hands the result to a parser, the hand-off shape matters.  `parser.feed(self._recv_view[:got])` (memoryview slice) is zero-copy; `parser.feed(bytes(self._recv_buffer[:got]))` allocates a fresh bytes object per recv and defeats the recv_into win.  The parser usually accepts either via `chunk_view = chunk if isinstance(chunk, memoryview) else memoryview(chunk)`, but the upstream `bytes(...)` copy already happened — the smell is at the caller, not the parser.  Grep for `return bytes(self._recv` / `parser.feed(bytes(` patterns in recv loops.

* **Runtime-source verification when behavior decisions hinge on allocator shape.**  When an audit finding rests on "this operation is zero-alloc on MP/CP" (or "this is supported on MP/CP"), don't guess from CPython behavior — read the canonical runtime source under `.tools/micropython-vX.Y.Z/` and `.tools/circuitpython-NN.M.P/`.  Concrete from the wire.py audit: deciding between `del bytearray[:n]` and `bytearray[:n] = b""` for in-place compaction was settled by reading `py/objarray.c:array_subscr` and confirming the `del` branch returns `MP_OBJ_NULL` while the slice-assign branch reaches `mp_seq_replace_slice_no_grow` (no alloc).  Cite the file:line of the verifying read in the commit message — future audits will save the trip.

## Process

1. **Read each library's `src/<name>/` top-to-bottom** (lighter than `/audit-library`'s deep read, but enough to know the shapes).
2. **Map the boundary — and check for a canonical-shape statement first.**  Before mapping, check `plans/patterns.md` and `plans/decisions/` for an existing statement of the canonical shape this boundary should take.  If one exists, the audit flips from *discovery* (find the right shape) to *conformance* (compare every consumer to the documented shape, flag divergers).  Then map every public function each library exposes that the others call — capture as a small table.  When the audit is duck-typed / N-way, add a `conforms?` column right then:
   ```
   producer    consumer    function                shape                   conforms?
   timing      runner      ticks (object | None)   ticks: object DI        ✓
   timing      mqtt        ticks_ms / add / diff   3× func kwargs          ✗
   timing      ntp         ticks_ms / add / diff   3× func kwargs          ✗
   timing      wifi        ticks (object | None)   ticks: object DI        ✓
   ```
   Three `✓` next to five `✗` is the entire audit insight in one table — every divergence row becomes a finding, and the divergers usually share the same shape, which collapses the punch-list to one rename per library.
3. **Run the audit dimensions** through that map.  The map is the reference; deviations from clean shapes get flagged.
4. **Score by confidence** — same High / Medium / Low / Escalate as `/audit-library`.  Escalate to `/audit-workspace` if the finding implies a cross-cutting infrastructure concern.
5. **Present the punch-list to the user.**
6. **Execute high-confidence items as one cohesive commit per fix.**  Cross-library changes need to land atomically — don't ship a half-renamed function.  Run *every sibling package* that imports either side after each batch, not just the two libraries in scope.  E.g., a rename in `chumicro_deploy` that flows into `chumicro_workspace`'s CLI also needs `workbench/repl/tests` + `workbench/pytest-device/tests` run, because both packages have transitive imports.  Run `python scripts/run.py test --libraries <name1>,<name2>,... --coverage-threshold 94` and grep `from chumicro_<n>` across every other `workbench/*/src` and `libraries/*/src` to find consumers that the named-library scope missed.  If the change touches device-runtime behaviour, also run `python scripts/run.py test-libraries-functional --library <name1>` against `devices.yml` defaults (Pi Pico W CP / MP).  Read the `git-commit` skill before each commit.
7. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.**  If preflight reports a failure unrelated to the boundary in scope, `git stash` + re-run preflight + `git stash pop` to verify it's pre-existing.  Flag in the punch-list so the user can scope a fix into the same session or a follow-up — don't silently fold it into a cross-library commit.
8. **Stage explicit paths only — hooks may auto-stage unrelated files.**  Multi-agent sessions and pre-commit hooks can introduce unrelated changes into the working tree mid-audit (other agents committing in parallel, linters auto-fixing siblings, hooks auto-staging "related" files).  Mitigation: `git add <explicit-paths>` listing only the files you edited, then `git --no-pager diff --cached --stat` immediately before `git commit` to verify staged set matches intent.  Concrete from the 2026-05-11 wire.py audit: an audit-scoped commit pulled in an unrelated `libraries/kvstore/src/chumicro_kvstore/core.py` docstring change because a pre-commit hook auto-staged it; the kvstore change was benign but mixed two distinct audit passes' work.  Avoid `git add -A` / `git add .` in audit commits — if a hook needs to do its job, let it operate on the explicit set you staged, not the whole working tree.

## Anti-patterns

* **Don't merge libraries during an audit pass.**  Library boundaries are workspace-level decisions; flag the merge candidate but don't execute.
* **Don't propose new public API.**  If a finding says "the boundary needs a new function," confirm with the user before adding it.
* **Don't move tests across libraries.**  Each library owns its tests; cross-library tests live in `functional_tests/` or a separate integration suite.
* **Don't break the dependency graph.**  Per Decision 0042, some libraries have explicit zero-dep policies.  Check before proposing a new import.
* **Don't introduce test-cater scaffolding when promoting a helper across a boundary.**  When a finding extracts a shared helper to a third module (or `support/`), call it through the canonical module path (`from . import shared_module` + `shared_module.helper()`) so test monkeypatching has one honest patch site.  Don't add `__all__` placeholders, re-exports, or "kept around so monkeypatch paths keep working" comment blocks to the producing library.  Update test patch paths to follow the new home.  Mockability surfaces belong in each library's `testing.py`; back-compat re-exports for tests don't belong in shipped boundary code.  (See `/audit-library`'s "Extraction patterns" section.)
* **Don't update only one side of a renamed handoff.**  When the boundary contract changes a function name, return type, or callback signature, both sides land in the same commit + every transitive sibling test suite gets re-run.  Half-landed renames create silent runtime failures that the named-library test scope won't catch.

## Special concern: library-to-library handoffs that should be unified

The user flagged this explicitly: "library to library handoffs that should be done as one library or have a better unified solution."  This is an `audit-workspace`-level concern (whether two libraries should merge) but the *evidence* often surfaces at the integration layer.

If during an integration audit you spot:

* Two libraries with overlapping responsibilities (one does X, the other does X-prime).
* Libraries that always ship together (no consumer uses one without the other).
* Boundary code that's the bulk of either library.

— flag those as **escalate-to-workspace** findings.  Don't propose the merge; surface the evidence so `/audit-workspace` can weigh it.

## Output format

```
Integration audit: chumicro_<a> ↔ chumicro_<b>
==============================================

Boundary map:
  <a> → <b>: <function>(<args>) -> <return>
  ...

HIGH-CONFIDENCE:
  flow      <file>:NN — <description>
  ...

MEDIUM-CONFIDENCE:
  shape     <file>:NN — <description>
  ...

ESCALATE:
  workspace <description> (route to /audit-workspace)
```

The goal: each library does the work it conceptually owns, the boundary carries clean shapes, and the integration can be understood by reading the boundary alone.
