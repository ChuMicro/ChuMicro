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

## Audit philosophy

Cross-library code reveals integration-level problems that single-library audits miss:

* **Leaky abstractions** — library A exposes a concept that only library B understands.
* **Parallel implementations** — both libraries solve the same sub-problem differently.
* **Wrong-side work** — library A does work that conceptually belongs to library B, or vice versa.
* **Handoff churn** — the same value gets reshaped 3× as it crosses 3 libraries.
* **Coupling without cohesion** — libraries depend on each other but for unrelated reasons; the boundary needs a re-cut.

The goal isn't to merge libraries (that's `/audit-workspace`'s call); it's to make the boundary **honest** — each side does the work it conceptually owns, with a clean shape flowing across.

## Audit dimensions

### 1. Type / value flow across the boundary

* **What types flow across?**  Map every public function each library exposes that the other(s) call.  Note each call site's input + output shape.
* **Are simple values being shaped into complex types just to cross the boundary?**  E.g., a function takes a `WifiConfig` dataclass when it really only uses one field.  Pass the field directly.
* **Are complex types being decomposed at every boundary?**  E.g., wifi returns a `Connection` object that sockets immediately unpacks into `(host, ip, dns)` and discards the object.  Either the object isn't earning its keep, or the unpacking should move into wifi.
* **Are there Optional[X] + None-checks repeated on both sides?**  Often the producer should validate-or-raise; the consumer shouldn't have to re-handle absent.

### 2. Dependency direction

* **Is the dependency direction sensible?**  `chumicro-mqtt` depending on `chumicro-sockets` makes sense (MQTT is a sockets consumer).  `chumicro-sockets` depending on `chumicro-mqtt` would not.
* **Are there cycles?**  Direct cycles fail import; subtle cycles work but signal a layering problem.  Check `pyproject.toml` `dependencies =` plus actual `import` statements.
* **Are dependencies declared accurately?**  A library that imports `chumicro_X` but doesn't list it in `dependencies` is a future packaging bug.  Run a quick grep: every `import chumicro_*` should appear in `pyproject.toml`.
* **Decision 0042 check:** per `plans/decisions/0042-library-dependency-policy.md`, certain libraries (e.g., `chumicro-events`) are zero-dep by design.  Verify the audit doesn't propose changes that break that.

### 3. Duplicated logic across the boundary

* **Same operation implemented twice.**  E.g., wifi has a "wait for IP" loop; sockets has a "wait for connection" loop with the same retry-backoff logic.  Either consolidate, or accept the duplication if the loops genuinely diverge in the future.
* **Parallel state machines.**  Both libraries track "connecting / connected / failed" with slightly different vocabulary.  Pick one vocabulary; the other library translates at the boundary.
* **Re-validation of values that were already validated.**  Library A's output went through validation; library B re-validates the same value.  Trust the producer, or move validation to where it's needed.

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

* **Runner contract: one `now_ms` per tick** (Decision [0014](../../../plans/decisions/0014-runner-pattern.md)).  When library B calls into library A's `check(now_ms)` / `handle(now_ms)` method, B must pass the *same* `now_ms` the runner gave it — never call `ticks_ms()` mid-tick to get a "fresh" value.  Mixing tick sources between libraries (e.g., one consumer uses `chumicro_timing.ticks_ms` while another rolls its own `time.monotonic()`-based shim) causes clock-domain misalignment, which manifests as deadlines firing on the wrong tick or never firing.  Audit checklist:
  * Does each tick-receiver use the supplied `now_ms` rather than re-fetching?
  * If two libraries share a tick budget, do they get the same `now_ms` value at every dispatch?
  * Are tests rolling their own timer instead of using `chumicro_timing.ticks_ms`?

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

## Process

1. **Read each library's `src/<name>/` top-to-bottom** (lighter than `/audit-library`'s deep read, but enough to know the shapes).
2. **Map the boundary.**  Every public function each library exposes that the others call.  Capture as a small table:
   ```
   producer    consumer    function                shape
   wifi        sockets     get_radio()             radio: Adapter
   wifi        mqtt        WifiService.is_up       bool
   sockets     mqtt        connect_tcp(host,port)  Socket
   ```
3. **Run the audit dimensions** through that map.  The map is the reference; deviations from clean shapes get flagged.
4. **Score by confidence** — same High / Medium / Low / Escalate as `/audit-library`.  Escalate to `/audit-workspace` if the finding implies a cross-cutting infrastructure concern.
5. **Present the punch-list to the user.**
6. **Execute high-confidence items as one cohesive commit per fix.**  Cross-library changes need to land atomically — don't ship a half-renamed function.  Run `python scripts/run.py test --libraries <name1>,<name2>,... --coverage-threshold 94` after each batch.  If the change touches device-runtime behaviour, also run `python scripts/run.py test-libraries-functional --library <name1>` against `devices.yml` defaults (Pi Pico W CP / MP).  Read the `git-commit` skill before each commit.

## Anti-patterns

* **Don't merge libraries during an audit pass.**  Library boundaries are workspace-level decisions; flag the merge candidate but don't execute.
* **Don't propose new public API.**  If a finding says "the boundary needs a new function," confirm with the user before adding it.
* **Don't move tests across libraries.**  Each library owns its tests; cross-library tests live in `functional_tests/` or a separate integration suite.
* **Don't break the dependency graph.**  Per Decision 0042, some libraries have explicit zero-dep policies.  Check before proposing a new import.

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
