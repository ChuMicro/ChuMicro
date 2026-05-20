# Decision 0068: Unified deploy-mode resolution + on-device unit sweeps

Status: `accepted`
Date: `2026-05-15`
Related: [Decision 0047](0047-deploy-mode-flash-default.md) (flash default + `requires_flash`; this decision unifies and extends its §3 auto-switch), [Decision 0028](0028-deploy-modes.md) (RAM/flash transport semantics), [Decision 0027](0027-device-testing-infrastructure.md) (device-test infra + `devices.yml` schema), [Decision 0016](0016-cross-runtime-unit-tests.md) (the cross-runtime unit suite this lets run on hardware).

## Context

Decision 0047 flipped the default to flash, added the `[tool.chumicro] requires_flash` library flag, and added a RAM→flash auto-switch.  Two gaps surfaced since:

1. **The auto-switch lives in only one of two deploy-mode resolvers.**  `Deployer._effective_device_for_source` (chumicro-deploy / CLI / production) applies force → device-not-ram → non-`.py` data file → `requires_flash` lib → configured mode.  The `chumicro-pytest-device` functional/on-device path uses a *separate* resolver, `resolve_effective_deploy_mode` (`_test_runner.py`): CLI override → devices.yml per-device → global default, with **no source inspection at all**.  CP RAM-mode source staging *silently skips* non-`.py` files, so a RAM functional run that stages a data file (e.g. `_ca_bundle.der`, pulled in transitively by any sockets-TLS-touching test) silently drops it — confusing failure, no hint.  Duplicated policy that drifted is exactly the bug.
2. **RAM mode's strongest justification has no first-class entry point.**  RAM mode's real value is bulk cross-runtime *unit* tests on real silicon — pure (no wifi, no data files, no `runtime_config`), high-volume, wear- and speed-sensitive (a full ~3800-test on-device sweep in flash = thousands of writes + `sync`s + flash wear per run).  Unit tests don't hit any of RAM mode's footguns.  But there's no command for it; it's only reachable ad hoc.

## Decision

### 1. One resolver, one rule, no context flag

A single deploy-mode policy — `resolve_deploy_mode(configured_mode, *, staged_files, device_caps, requires_flash_libs, resolution_unit, force) -> (mode, message | None)` — owned by `chumicro-deploy` and consumed by both `Deployer` and `chumicro-pytest-device`.  It is applied per **resolution unit**: a single deploy for `Deployer`; a single library's test suite for the sweep (§3).  There is no context parameter and the rule is byte-identical everywhere.  Three inputs are caller-scoped, and that — not a branch — is the whole subtlety:

- `requires_flash_libs` is **always the full transitive import/dependency closure**, never just the resolution unit's own library (step 3).
- `staged_files` is **caller-scoped** — full closure for functional/app-deploy, own-src for the unit sweep (step 4).
- `resolution_unit` is the library a "declare `requires_flash`" recommendation should name (step 3), or `None` when there is no single owning library (an app deploy — the `Deployer` passes `None`, so its message is the plain switch with no recommendation).  It carries no mode logic; it only selects the message variant, which is why it is a caller input rather than something the resolver can infer.

1. `force` set → that mode, no further policy (the "I know what I'm doing" escape hatch).
2. Device declares `supports_ram_mode: false` (§2) and `ram` requested → flash.  A board that can't RAM can't RAM.
3. Configured mode is `ram` **and** `requires_flash_libs` is non-empty (any library in the transitive closure declares `requires_flash`) → flash.  `requires_flash` means "OOMs on *import* in RAM on a small board" (Decision 0047), and the import happens regardless of test shape — so this is transitive: if library X imports `chumicro-requests`, X cannot run RAM even if X's own tests are pure, because importing requests alone OOMs (AST-walking the test cannot prune the import).  When the closure forces flash but the resolution unit's *own* library does not declare `requires_flash`, emit a warning recommending it add the declaration — that library effectively requires flash and its `pyproject.toml` should say so, so future runs skip the discovery (this is the durable record; the resolver does not auto-edit pyproject).
4. Configured mode is `ram` **and** `staged_files` contains a non-`.py` file → flash.

`staged_files`'s caller-scoping (step 4) is how the unit/functional distinction is handled without a branch in the rule — note this is the *opposite* scoping rule from `requires_flash_libs` (always full closure, step 3), because the two triggers fail differently: `requires_flash` is import-OOM (transitive, happens regardless of test purity) while a non-`.py` data file is only consumed by a runtime code path a pure unit test won't reach:

- **Functional / app-deploy callers pass the full dependency closure.**  They must: a `chumicro-requests` *functional* test does real HTTPS through `chumicro-sockets` and genuinely needs `sockets/_ca_bundle.der` on the device — if RAM silently drops it, that is the exact bug this decision fixes.  Functional/app code exercises dependency code paths.
- **The unit-sweep caller passes only the library-under-test's own package src** (not the chumicro dependency closure).  Pure unit tests cannot reach a dependency's data-file code path by the Decision 0003 / 0016 runtime-boundary contract, so a dependency's data file silently dropped on RAM is harmless; scoping to own-src stops dependency-closure over-poisoning.  Without this, every sockets-dependent suite (`ntp` and any future light sockets user — the heavy ones are `requires_flash` anyway) would wrongly flip to flash merely because `sockets/src` ships `_ca_bundle.der`.  Only `chumicro-sockets`'s *own* unit suite flips (its own src ships the file) — the narrow, accepted cost.

The staging path stages whole `src/` directories (library + chumicro dependency closure), not an AST-minimised file set, and a data file is `open()`-ed not `import`-ed so an import walker can't discover it anyway — which is why the scope is a caller decision, not something the resolver can infer.

5. Otherwise → the configured mode unchanged (a RAM preference stays RAM).

`configured_mode` is resolved first by precedence: CLI `--deploy-mode` → per-device `deploy_mode` → `devices.yml` global `defaults.deploy_mode` → a **caller last-resort default**.  That last-resort differs by caller and is the one place caller identity matters for the *preference* (not the rule): `Deployer` / functional fall back to `flash` (Decision 0047's beginner-footgun rationale — an app deploy that silently doesn't persist is the trap 0047 fixed); the **on-device unit sweep falls back to `ram`** (its entire purpose is RAM-capable on-device validation; 0047's footgun reasoning does not apply to a deliberate dev sweep, and most libraries are RAM-capable so RAM is the right default *for this command*).  The rule then gates that preference by board capability (2) and the unit's requirements (3–4): a `ram` preference *stays RAM* for every library that supports RAM on a board that supports RAM, and only the specific library suites that trip 2–4 fall to flash.

Whenever 2–4 override the request the resolver returns a human-readable message; the caller emits it and **continues** (no silent skip, no aborted run — the "do the safe thing, explain it" philosophy of 0047 §3).  This makes the pytest-device path loud where it is silent today and removes the duplicated, drift-prone second policy.

### 2. Per-device capability in `devices.yml`

New optional per-device boolean.  There are exactly two modes (Decision 0028) and flash is always available (every board can write its FS — it is the production-shaped path), so the only real degree of freedom is whether the board can do RAM mode.  A boolean captures that with no invalid states; an array (`[flash]` / `[ram, flash]`) would invite nonsense combinations and a verbose default.

```yaml
- id: some-board
  # supports_ram_mode: false   # default true; set false ONLY for a
  #                            # board that genuinely cannot run RAM
  #                            # mode at all (no known board today —
  #                            # the field exists for when one appears)
```

`supports_ram_mode` (default `true`, absent ⇒ `true` — back-compatible) is a *capability*, orthogonal to the existing `deploy_mode` *preference*: preference says what you'd like, capability says what's possible.  `supports_ram_mode: false` + `ram` requested yields `device <id> does not support RAM mode — running in flash` and continues.

This is reserved for a board that *cannot* RAM at all — **not** a board where RAM is merely *tight* (e.g. Pi Pico W's 256 KB).  RAM tightness is a per-*library* concern handled by the OOM→`requires_flash` learning in §3, not by disabling RAM for the whole board (which would needlessly force every light library's suite to flash on that board).  No board is known to need `false` today; the field is declared now so the schema is stable when one appears, consistent with not retrofitting `devices.yml` later — but it ships with zero current consumers and that is acknowledged, not hidden.

### 3. On-device unit sweep is a first-class command

A new `scripts/run.py` task runs the cross-runtime *unit* suite (the suite that otherwise runs on unix-port) on real boards.  **Not** in default preflight.  `preflight --with-device-unit` is an opt-in flag that appends it, parallel to `--with-functional`.

The sweep applies the §1 rule **per library suite**, then groups libraries by resolved mode and runs each group as **one single-mode device session**.  With a `ram` preference on a RAM-capable board: a RAM session over the libraries that resolved to RAM, then a flash session over those that resolved to flash (`requires_flash`-closure libs + libraries shipping a data file).  With a `flash` preference, or a board that can't RAM: one flash session over everything.  Each session reuses the **existing** per-library staging untouched — flash re-stages per library with rsync `--delete` cleaning the prior library off (`plugin.py` ~L816-821); RAM re-stages per file with a soft-reset between (`plugin.py` ~L1254-1265, which exists precisely so the previous file's RAM doesn't stack and OOM the next).  No new isolation machinery, no mid-session mode switching: a session is one mode, the grouping is computed once up front.  This is why a single global `ram` preference still gets RAM speed + zero wear for the ~16 light libraries while only the heavy/data-file ones fall to flash — without it the feature is inert (the full suite always contains a `requires_flash` library, so a single-mode sweep is always flash).

Two sessions on one board in one run is supported by the existing per-device-per-mode transport cache (it already keys `get_transport(device, mode)`, so RAM-group and flash-group are two cache entries / two transports).  The only implementation-verify item is that the board tolerates the RAM-group transport teardown followed by a flash-group reconnect on the same serial port in one run — expected fine (the functional suite already reconnects per device across runs), confirmed during implementation, not a design blocker.

**OOM→`requires_flash` learning.**  RAM resolution is a *prediction* (`requires_flash` declared, board capability, data file); a library can still OOM during the RAM session's stage/import despite resolving to RAM (e.g. a library that should have declared `requires_flash` but didn't, or a transitive case the closure scan missed).  When that happens the sweep does not fail the library: it flips *that library's suite* to flash for the rest of the run and emits a loud message recommending the library declare `requires_flash` in its `pyproject.toml`.  The durable fix is that declaration (the same transitive-warning channel as §1 step 3) — the resolver never auto-edits pyproject; the OOM is a discovery that the static signal was wrong, surfaced so a human records it once instead of every run re-hitting the OOM.

### 4. The supported matrix is explicit

| Shape | unix-port | on-device flash | on-device RAM |
|---|---|---|---|
| **unit** | default (no deploy) | supported | supported; light library suites ride RAM, heavy/data-file suites grouped into a flash session |
| **functional** | n/a | default (0047) | honored unless the §1 rule forces a deploy to flash (then loud, never a silent file drop) |

## Consequences

- Resolves the `plans/open-questions.md` two-resolver divergence: one policy, loud not silent.  That open question is chartered here and removed from the file (this ADR + the workstream are the record).
- RAM mode keeps its strongest justification (on-device unit sweeps) and sheds its footgun (silent data-file drop on CP RAM).
- **The on-device unit sweep is behavioral pass/fail only — it does NOT gate coverage.**  `coverage.py` cannot trace MicroPython / CircuitPython bytecode, so per-library coverage gating (Decisions 0009 / 0025, the 94 % agent threshold) stays exclusively the unix-port / CPython responsibility and is unchanged.  The sweep answers "does this behave on real silicon" (catching rp2 absent `MBEDTLS_PEM_PARSE_C`, non-compacting GC fragmentation, real `gc.mem_free` — divergences unix-port hides), not "is it covered."  `--with-device-unit` therefore takes no coverage-threshold argument.
- New `devices.yml` key, back-compatible (absent ⇒ both modes).  `chumicro-deploy` + `chumicro-pytest-device` minor bumps when implemented; the shared resolver lives in `chumicro-deploy` (pytest-device already depends on it).
- 0047 §3's "pre-flight check in chumicro-deploy" is superseded by the unified resolver; 0047 §3 is edited in place to cross-link here, its `requires_flash` schema decision unchanged.
- Phased implementation tracked in [`plans/workstreams/archive/deploy-mode-unification.md`](../workstreams/archive/deploy-mode-unification.md).

### Alternatives considered

- **Keep two resolvers, just add the missing check to the test one.**  Rejected: duplicated policy is what drifted into the silent-drop bug in the first place; a second copy will drift again.
- **Rip RAM mode out entirely (flash-only on-device, drop the unit sweep).**  Seriously considered — the CP raw-REPL bootstrap subsystem is RAM-only and *not* entangled with `chumicro-repl` (verified: repl has its own session/recovery), so deletion would be a relatively clean excision and a large code reduction.  Rejected after working it through: (a) most libraries *are* RAM-capable — only the four `requires_flash` networked libs aren't — so RAM mode serves the majority, not a fringe; (b) the subsystem is already written and working, so deletion trades a functioning capability for a one-time simplicity win; (c) on-device unit sweeps are the validation path that catches real-silicon divergences unix-port hides (rp2 absent `MBEDTLS_PEM_PARSE_C`, non-compacting GC fragmentation, real `gc.mem_free` — all surfaced by *this* TLS work); (d) the footguns are functional-test-with-assets concerns, and §1's caller-scoped `staged_files` + the OOM→`requires_flash` learning neutralize them.  The earlier framing that the only cost of keeping RAM was a preflight regression was wrong (the slow `sync` is an unrelated unit-test-isolation defect; preflight never deploys to a board) — removing that phantom cost made *keeping* RAM the clearer call.  Narrow and harden the surface; don't delete a working capability.
- **Make "functional + RAM + data files" a hard error.**  Rejected: inconsistent with 0047's established "classify, do the safe thing, explain" precedent (mirrors the `chumicro_deploy.recovery` layer).  Auto-switch + loud message is the house style.
- **Per-library mode resolution with the transport switching mode mid-sweep + a `context` parameter on the resolver.**  An earlier draft of this ADR.  Rejected: deploy mode is session-scoped today (the transport is cached per device), so per-library mode would mean tearing down and re-standing the transport between libraries, plus a `context` flag to scope which triggers apply.  Computing each library's mode up front and grouping same-mode libraries into one single-mode session per group delivers the identical outcome with no mid-session switching, no context flag, and zero changes to the existing per-library staging — strictly simpler.  The "within-deploy vs across-deploy mixing" distinction the earlier draft had to spell out simply disappears: every session is one mode.
