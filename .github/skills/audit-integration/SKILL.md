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

**Sideways propagation — when one library in a family just finished an audit pass.**  A different shape of trigger, equally common in practice: library X just landed a series of `/audit-library` or `/audit-embedded` improvements, and the patterns that pass validated for X are candidates to fold sideways to its peers.  Concrete example from 2026-05-12: `chumicro_mqtt` finished a multi-commit `/audit-embedded` pass (encoder `_append_packed` helpers, `str(view, "utf-8")` for utf-8 decode, `bytes()`-wrap drops on `struct.unpack`, encoder body collapse), and `/audit-integration mqtt,requests,http_server,websockets` ran next to compare each peer `_wire.py` against the now-validated mqtt patterns.  Three of the four patterns applied to `chumicro_websockets`; one applied to `chumicro_requests` + `chumicro_http_server` (text-protocol peers don't use `struct`).  Frame this trigger explicitly when proposing the audit so the user knows the input is "fold X's wins to peers", not "the boundary feels off."

## Audit philosophy

Cross-library code reveals integration-level problems that single-library audits miss:

* **Leaky abstractions** — library A exposes a concept that only library B understands.
* **Parallel implementations** — both libraries solve the same sub-problem differently.
* **Wrong-side work** — library A does work that conceptually belongs to library B, or vice versa.
* **Handoff churn** — the same value gets reshaped 3× as it crosses 3 libraries.
* **Coupling without cohesion** — libraries depend on each other but for unrelated reasons; the boundary needs a re-cut.
* **Same problem, three layers** — when one layer of an integration drifts from the documented shape, the other two usually drifted too, because they reinforce each other.  A divergent constructor API makes the shared test fake awkward to use, so a parallel test fake gets built; the divergent shape also encourages a different internal pattern for the same operation.  Finding one is a strong signal to hunt the other two.  Concrete instance from the 2026-05-11 timing/runner audit: five libraries diverged from the documented `ticks: object` DI shape *and* refetched `ticks_ms()` mid-tick *and* (in one case) shipped a parallel `TickClock` fake instead of using `chumicro_timing.testing.FakeTicks`.

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
* **Declared deps can be runtime-optional via constructor injection — and the absence of a top-level import is often load-bearing.**  A library can list `chumicro-X` in `pyproject.toml` `dependencies` and still keep its `src/<name>/` *.py* files free of any top-level `chumicro_X` import.  The substrate gets installed (so opt-in submodules like `<lib>.sockets_factory` and protocol annotations work when imported) but stays out of the runtime import graph for a BYOS consumer that passes a custom protocol-shaped object to the constructor.  That keeps the substrate off the [deploy walker](../../../workbench/deploy/src/chumicro_deploy/sources.py)'s bundle and out of board RAM.  Two common shapes: (a) duplicated trivial helpers per consumer (each library carries its own `_is_eagain` / `_force_non_blocking` instead of importing from the substrate); (b) lazy in-function imports (`from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback`).  Both are mechanism, not bloat.  **Audit move:** before proposing a dedup that adds `from chumicro_<X> import <util>` to library B, grep B's pre-edit `src/` for top-level `chumicro_<X>` imports.  Zero imports + declared dep = intentional optionality, not a missing import.  Field-tested instance: `_is_eagain` (5 libraries) + `_force_non_blocking` (4 libraries) across mqtt / requests / http_server / websockets / ntp.  The hoist into `chumicro_sockets` was attempted 2026-05-23 and reverted: it would have forced every BYOS user to load `chumicro_sockets` into RAM and into the on-device flash bundle, breaking the substrate-optional contract every networking library carries.
* **Decision 0042 check:** per `plans/decisions/0042-library-dependency-policy.md`, certain libraries (e.g., `chumicro-events`) are zero-dep by design.  Verify the audit doesn't propose changes that break that.

### 3. Duplicated logic across the boundary

* **Same operation implemented twice.**  E.g., wifi has a "wait for IP" loop; sockets has a "wait for connection" loop with the same retry-backoff logic.  Either consolidate, or accept the duplication if the loops genuinely diverge in the future — or if the duplication is the mechanism that keeps a constructor-injected substrate optional at runtime (see §2 "Declared deps can be runtime-optional").  Trivial duplicated helpers in libraries that accept BYOS dependencies are usually the latter; check before proposing a hoist.
* **Parallel state machines.**  Both libraries track "connecting / connected / failed" with slightly different vocabulary.  Pick one vocabulary; the other library translates at the boundary.
* **Re-validation of values that were already validated.**  Library A's output went through validation; library B re-validates the same value.  Trust the producer, or move validation to where it's needed.
* **Doc-comment-says-X-but-code-says-Y is a high-signal divergence smell.**  Grep the boundary code for forward-looking phrasing: *"until a third X consumer arrives"*, *"when X happens"*, *"callers like Y already pass a view"*.  Each is a claim about a *trigger condition*; check whether the trigger has been hit (concrete from the 2026-05-11 wire.py audit: websockets' `_wire.py` claimed callers "already pass a view" while `_session.py:551` actually returned `bytes(...)` — the comment was right, the code drifted away from it; a separate websockets comment named "a third HTTP/1.1-aware consumer" as the trigger for extraction, and the third consumer — chumicro-http-server — had been shipped a year earlier).  When two of these stack, you have systemic drift, not isolated bugs.
* **Same library, multiple drifts.**  Once you find one divergence in library B from the documented shape, widen the lens within that library before moving on.  Concrete from the wire.py audit: websockets diverged on (a) the recv-chunk return type, (b) the recv-buffer cap policy, (c) the dict insertion-order preservation — three independent drifts from the requests/http_server peer shape, none alone obvious.  After finding one, grep the library for the *other* dimensions before claiming "done."

* **Parallel test fakes: build a three-column parity table (live interface | producer fake | duplicate fake), not two-column fake-vs-fake.**  When library B ships a "focused" or "hot-path" version of library A's `testing.py` fake, the easy framing is "should the duplicate merge into the producer?" — but the load-bearing question is *which of the three is right on each row*.  Two patterns the two-column view misses.  **The producer fake drifts behind its own Protocol / ABC**: the duplicate, usually built recently against the *current* interface, inherits the right kwargs; the producer fake silently doesn't, because no producer-side test combines the new kwarg with the fake.  The duplicate is a bug detector for the producer — but only when the live interface is a column.  **The duplicate is usually narrower-with-features, not richer**: smaller surface (skips methods the consumer never calls) plus 2-3 specific affordances the producer lacks (per-call output queues, raise-injection hooks, extra config knobs).  Once the table makes that visible, the merge mechanic falls out — add the 2-3 features to the producer fake additively and delete the duplicate, *not* "lift the duplicate over" (its narrower surface would be a liability for other producer-fake consumers).  Field defaults belong in the table too: a `None` default on the producer where the duplicate has `[]` is a load-bearing distinction at every consumer assertion site that does `is not None`.

* **Per-library `__init__.py` quickstart examples drift sideways too.**  When one library gets a fix to its package-docstring example (missing import, wrong API call, runner-contract violation like calling `ticks_ms()` twice per tick), walk peer libraries' equivalent `__init__.py` examples for the same shape.  These examples were usually written by the same person at the same time and share the same bug.  Concrete from the 2026-05-12 wire.py audit: mqtt's example got `now = ticks_ms()` once-per-tick + missing `import` lines fixed (`66f96b88`); requests + http_server peer examples had the *same* two bugs (one ticks twice per tick; the other ticks twice AND used `wifi.radio` without `import wifi`).  Third-most-common drift surface after recv-buffer shapes and parser-state vocabulary.

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
* **Are there silent contracts?**  Things like "must call `.connect()` before `.send()`" enforced only by behavior, not types.  Document or enforce.

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

* **Workbench / library boundary** (Decisions [0032](../../../plans/decisions/0032-workbench-host-tools.md), [0052](../../../plans/decisions/0052-workbench-no-library-imports.md)) — host-side `workbench/*` packages must NOT `import chumicro_<libname>` from `libraries/`.  Strict.  Workbench tools that need on-device-shaped logic embed it as payload bytes (templates, scaffolds), never imports.  Audit any audit pair that crosses workbench↔library for this rule.

* **Streaming-parser conformance: shape, compaction, zero-copy hand-off.**  When two or more libraries each ship a streaming wire parser fed by `recv_into` on a shared scratch buffer, four sub-shapes diverge silently: push vs pull API, compaction strategy (realloc-and-rebind vs in-place memmove), the CPython BufferError gotcha on in-place resize, and zero-copy hand-off (`parser.feed(self._recv_view[:got])` vs the `bytes(...)`-wrap that defeats `recv_into`).  See [field-reality → streaming-parser conformance](field-reality.md#streaming-parser-conformance--shape-compaction-zero-copy-hand-off) for each sub-shape's portable pattern, runtime-source citations, and the gotcha details.

* **Runtime-source verification when behavior decisions hinge on allocator shape.**  When an audit finding rests on "this operation is zero-alloc on MP/CP" (or "this is supported on MP/CP"), don't guess from CPython behavior — read the runtime source under `.tools/micropython-vX.Y.Z/` and `.tools/circuitpython-NN.M.P/`.  Concrete from the wire.py audit: deciding between `del bytearray[:n]` and `bytearray[:n] = b""` for in-place compaction was settled by reading `py/objarray.c:array_subscr` and confirming the `del` branch returns `MP_OBJ_NULL` while the slice-assign branch reaches `mp_seq_replace_slice_no_grow` (no alloc).  Cite the file:line of the verifying read in the commit message — future audits will save the trip.

* **Three-tier inbound size model — family-pattern check for any peer-controlled-bytes consumer.**  Every library that decodes peer-controlled inbound bytes (frame parsers, body absorbers, packet decoders) faces the same hostile-payload question: a peer announces a length and the decoder allocates that size before checking against any cap.  Three tier shapes worth comparing across the family:
  * **Tier 1 (steady)** — fixed-size pre-allocated buffer reused across messages.  Zero alloc per message when the inbound fits.
  * **Tier 2 (intact-but-bigger)** — message exceeds the steady buffer but ≤ the documented cap; one-shot `bytearray(payload_length)` alive for the duration of the message, freed after delivery.
  * **Tier 3 (oversized rolling-discard)** — message > cap; payload bytes drain through the steady-state buffer as a rolling sink, no payload-sized allocation.  Connection survives, payload is gone (event-only delivery: headers / topic / size, not bytes).
  
  Family agreement is a structural choice, not a per-library implementation detail.  Two-tier libraries (steady + raise-and-disconnect) are *correct* against the heap-DoS attack as long as the cap-check fires *before* the allocation — but the failure mode differs under hostile load: one bad peer kills the connection, vs. one bad message gets dropped under three-tier.  When the audit spans wire-format peers, build the table:
  ```
  library         tier model                                cap-checked-before-alloc?    drain-tier?
  mqtt            steady (256 B) + intact + rolling-discard ✓                            ✓
  websockets      steady (256 B) + one-shot                 ✓                            ✗ (raise-and-disconnect)
  requests        external buffer + grow                    ✓                            ✗ (raise-and-disconnect)
  http_server     external buffer + grow                    ✓                            ✗ (raise-and-disconnect)
  ```
  Divergence is a feature-additive call (per-library `/audit-embedded` follow-up), not necessarily a bug — but the tier-3 question belongs in the audit-integration table because it's the cross-library structural lens that single-library audits won't pose.  Concrete from the 2026-05-12 wire.py pass: mqtt landed three-tier the same week; the other three peers stayed two-tier intentionally (HTTP semantics: a partial body is unusable anyway, so raise-and-disconnect is the right choice for requests; websockets has the strongest tier-3 case because one connection delivers many messages, queued for `/audit-embedded websockets`).

## Process

1. **Read each library's `src/<name>/` top-to-bottom** (lighter than `/audit-library`'s deep read, but enough to know the shapes).
2. **Group the libraries by wire-format kind first when the audit spans wire-format peers.**  Binary (length-prefixed records, struct-packed fields, fixed headers — `chumicro_mqtt`, `chumicro_msgpack`) vs text (line-oriented, CRLF-terminated, ASCII headers — `chumicro_requests`, `chumicro_http_server`) vs hybrid (binary frames over a text-handshake — `chumicro_websockets`) each admit a different pattern set.  Half of the mqtt audit-embedded patterns (`_append_packed`, drop `bytes()` wrap on `struct.unpack`, pre-encoded packet literals) are structurally inapplicable to text-only peers.  Classify before mapping the boundary so the audit only evaluates each pattern against peers where it can apply — and so the punch list doesn't flag text libraries with binary-encoder findings the user has to dismiss.
3. **Map the boundary — and check for a documented-shape statement first.**  Before mapping, check `plans/patterns.md` and `plans/decisions/` for an existing statement of the shape this boundary should take.  If one exists, the audit flips from *discovery* (find the right shape) to *conformance* (compare every consumer to the documented shape, flag divergers).  Then map every public function each library exposes that the others call — capture as a small table.  When the audit is duck-typed / N-way, add a `conforms?` column right then:
   ```
   producer    consumer    function                shape                   conforms?
   timing      runner      ticks (object | None)   ticks: object DI        ✓
   timing      mqtt        ticks_ms / add / diff   3× func kwargs          ✗
   timing      ntp         ticks_ms / add / diff   3× func kwargs          ✗
   timing      wifi        ticks (object | None)   ticks: object DI        ✓
   ```
   Three `✓` next to five `✗` is the entire audit insight in one table — every divergence row becomes a finding, and the divergers usually share the same shape, which collapses the punch-list to one rename per library.
4. **Run the audit dimensions** through that map.  The map is the reference; deviations from clean shapes get flagged.
5. **Score by confidence** — same High / Medium / Low / Escalate as `/audit-library`.  Escalate to `/audit-workspace` if the finding implies a cross-cutting infrastructure concern.
6. **Present the punch-list to the user.**
7. **Execute high-confidence items as one cohesive commit per fix.**  Cross-library changes need to land atomically — don't ship a half-renamed function.  Run *every sibling package* that imports either side after each batch, not just the two libraries in scope.  E.g., a rename in `chumicro_deploy` that flows into `chumicro_workspace`'s CLI also needs `workbench/repl/tests` + `workbench/pytest-device/tests` run, because both packages have transitive imports.  Run `python scripts/run.py test --libraries <name1>,<name2>,... --coverage-threshold 94` and grep `from chumicro_<n>` across every other `workbench/*/src` and `libraries/*/src` to find consumers that the named-library scope missed.  If the change touches device-runtime behavior, also run `python scripts/run.py test-libraries-functional --library <name1>` against `devices.yml` defaults (Pi Pico W CP / MP).  Read the `git-commit` skill before each commit.
8. **Pre-existing lint / test failures: confirm and flag, don't sneak fixes.**  If preflight reports a failure unrelated to the boundary in scope, `git stash` + re-run preflight + `git stash pop` to verify it's pre-existing.  Flag in the punch-list so the user can scope a fix into the same session or a follow-up — don't silently fold it into a cross-library commit.
9. **Stage explicit paths only — hooks may auto-stage unrelated files.**  Multi-agent sessions and pre-commit hooks can introduce unrelated changes into the working tree mid-audit (other agents committing in parallel, linters auto-fixing siblings, hooks auto-staging "related" files).  Mitigation: `git add <explicit-paths>` listing only the files you edited, then `git --no-pager diff --cached --stat` immediately before `git commit` to verify staged set matches intent.  Concrete from the 2026-05-11 wire.py audit: an audit-scoped commit pulled in an unrelated `libraries/kvstore/src/chumicro_kvstore/core.py` docstring change because a pre-commit hook auto-staged it; the kvstore change was benign but mixed two distinct audit passes' work.  Avoid `git add -A` / `git add .` in audit commits — if a hook needs to do its job, let it operate on the explicit set you staged, not the whole working tree.

## Anti-patterns

* **Don't merge libraries during an audit pass.**  Library boundaries are workspace-level decisions; flag the merge candidate but don't execute.
* **Don't propose new public API.**  If a finding says "the boundary needs a new function," confirm with the user before adding it.
* **Don't move tests across libraries.**  Each library owns its tests; cross-library tests live in `functional_tests/` or a separate integration suite.
* **Don't break the dependency graph.**  Per Decision 0042, some libraries have explicit zero-dep policies.  Check before proposing a new import.
* **Don't introduce test-cater scaffolding when promoting a helper across a boundary.**  When a finding extracts a shared helper to a third module (or `support/`), call it through the module attribute (`from . import shared_module` + `shared_module.helper()`), not by bare name — so test monkeypatching has one honest patch site.  Don't add `__all__` placeholders, re-exports, or "kept around so monkeypatch paths keep working" comment blocks to the producing library.  Update test patch paths to follow the new home.  Mockability surfaces belong in each library's `testing.py`; back-compat re-exports for tests don't belong in shipped boundary code.  (See `/audit-library`'s "Extraction patterns" section.)
* **Don't update only one side of a renamed handoff.**  When the boundary contract changes a function name, return type, or callback signature, both sides land in the same commit + every transitive sibling test suite gets re-run.  Half-landed renames create silent runtime failures that the named-library test scope won't catch.

* **Don't add per-change inline comments justifying the audit edit.**  Audit-pass diffs CAN add comments — but only general "what this work is doing" framing, placed sparingly and once.  Per-change "this skips the bytes() copy" / "bench-validated -25% on MP 1.26" / "matches the mqtt pattern" notes are commit-message material, not source.  They rot fast (the bench number is true at audit time, not three audits later), they multiply across sites, and they cost flash on the supported boards (~800 KB total; the same explanation repeated 5× across one library times 15 libraries is real flash bytes for nothing).  An inline comment is warranted only when a future reader of just-the-code would be confused without it: a hidden constraint, a runtime quirk, a workaround for a specific bug, a non-obvious invariant.  Family-wide rules belong in `plans/patterns.md` so the code can be silent.

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
