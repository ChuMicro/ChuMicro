# Decision 0068: Unified deploy-mode resolution + on-device unit sweeps

Status: `proposed`
Date: `2026-05-15`
Related: [Decision 0047](0047-deploy-mode-flash-default.md) (flash default + `requires_flash`; this decision unifies and extends its §3 auto-switch), [Decision 0028](0028-deploy-modes.md) (RAM/flash transport semantics), [Decision 0027](0027-device-testing-infrastructure.md) (device-test infra + `devices.yml` schema), [Decision 0016](0016-cross-runtime-unit-tests.md) (the cross-runtime unit suite this lets run on hardware).

## Context

Decision 0047 flipped the default to flash, added the `[tool.chumicro] requires_flash` library flag, and added a RAM→flash auto-switch.  Two gaps surfaced since:

1. **The auto-switch lives in only one of two deploy-mode resolvers.**  `Deployer._effective_device_for_source` (chumicro-deploy / CLI / production) applies force → device-not-ram → non-`.py` data file → `requires_flash` lib → configured mode.  The `chumicro-pytest-device` functional/on-device path uses a *separate* resolver, `resolve_effective_deploy_mode` (`_test_runner.py`): CLI override → devices.yml per-device → global default, with **no source inspection at all**.  CP RAM-mode source staging *silently skips* non-`.py` files, so a RAM functional run that stages a data file (e.g. `_ca_bundle.der`, pulled in transitively by any sockets-TLS-touching test) silently drops it — confusing failure, no hint.  Duplicated policy that drifted is exactly the bug.
2. **RAM mode's strongest justification has no first-class entry point.**  RAM mode's real value is bulk cross-runtime *unit* tests on real silicon — pure (no wifi, no data files, no `runtime_config`), high-volume, wear- and speed-sensitive (a full ~3800-test on-device sweep in flash = thousands of writes + `sync`s + flash wear per run).  Unit tests don't hit any of RAM mode's footguns.  But there's no command for it; it's only reachable ad hoc.

## Decision

### 1. One resolver, used by both subsystems

A single deploy-mode policy — `resolve_deploy_mode(configured_mode, *, context, staged_files, device_caps, requires_flash_libs, force) -> (mode, message | None)` — owned by `chumicro-deploy` and consumed by both `Deployer` and `chumicro-pytest-device`'s `_test_runner`.  `context` is `app-deploy`, `functional`, or `unit-sweep`; some triggers are context-scoped.  Resolution order (extends 0047 §3):

1. `force` set → that mode, no further policy (the "I know what I'm doing" escape hatch).
2. Device declares `supports_ram_mode: false` (see §2) and `ram` requested → flash.  *Universal* — a board that can't RAM can't RAM.
3. Configured mode is `ram` **and** a graph library declares `requires_flash = true` → flash.  *Universal* — the library OOMs on *import* in RAM on a small board (Decision 0047) regardless of unit-vs-functional; the import happens either way.
4. Configured mode is `ram` **and** the staged set contains a non-`.py` data file → flash.  ***`app-deploy` / `functional` context only.***  A unit test is pure by the Decision 0003 / 0016 runtime-boundary contract (no wifi, no on-device files); a data file that rides along in `src/` but is never `open()`-ed by a unit test is harmless if RAM-mode CP drops it, and forcing the sweep to flash for an unused file would defeat the whole point of the RAM unit sweep.  If a "unit test" genuinely needs an on-device file it is mis-categorized — it is functional.
5. Otherwise → the configured mode unchanged.

The *configured mode* (input to the policy) is itself resolved first by the existing precedence: CLI `--deploy-mode` → per-device `deploy_mode` → `devices.yml` global `defaults.deploy_mode` → `DEFAULT_DEPLOY_MODE`.  The policy above then gates that preference by capability (step 2) and context-appropriate requirements (steps 3–4).  So a `--with-device-unit` run honors the global default first, then the board capability, then (only because a heavy library imports) `requires_flash` — exactly the precedence intuition that prompted this refinement.

Whenever 2–4 override the request the resolver returns a human-readable message; the caller emits it and **continues** (no silent skip, no aborted run — same "do the safe thing, explain it" philosophy as 0047 §3).  This makes the pytest-device path loud where it is silent today and removes the duplicated, drift-prone policy.

### 2. Per-device capability in `devices.yml`

New optional per-device boolean.  There are exactly two modes (Decision 0028) and flash is always available (every board can write its FS — it is the production-shaped path), so the only real degree of freedom is whether the board can do RAM mode.  A boolean captures that with no invalid states; an array (`[flash]` / `[ram, flash]`) would invite nonsense combinations and a verbose default.

```yaml
- id: pi-pico-w-circuitpython-board
  # supports_ram_mode: false   # default true; set false for boards
  #                            # where RAM mode is unreliable (e.g.
  #                            # Pi Pico W CYW43 RAM-mode TLS wedging)
```

`supports_ram_mode` (default `true`, absent ⇒ `true` — back-compatible) is a *capability*, orthogonal to the existing `deploy_mode` *preference*: preference says what you'd like, capability says what's possible.  `supports_ram_mode: false` + `ram` requested yields `device <id> does not support RAM mode — running in flash` and continues.

### 3. On-device unit sweep is a first-class command

A new `scripts/run.py` task runs the cross-runtime *unit* suite (the suite that otherwise runs on unix-port) on real boards.  **Not** in default preflight.  `preflight --with-device-unit` is an opt-in flag that appends it, parallel to the existing `--with-functional`.  RAM mode is the recommended mode for this sweep (pure tests, no assets, wear-sensitive at volume); flash is also supported per `devices.yml`.

The sweep resolves deploy mode **per library**, not once for the whole run (consistent with Decision 0009 per-library test runs).  Otherwise step 3 (`requires_flash`) fires the moment the staged graph includes any of the four heavy libraries (`chumicro-mqtt` / `requests` / `http-server` / `websockets`), forcing the *entire* sweep to flash and defeating the RAM value for the ~17 light libraries.  Per-library resolution lets light libraries ride RAM (fast, zero wear) while only the `requires_flash` libraries fall back to flash on small boards — the granularity that makes the RAM unit sweep worth having.  Without it the feature is inert: the full unit suite *always* contains a `requires_flash` library, so a single-global-mode sweep is *always* flash and the RAM sweep never happens.

This does **not** reintroduce within-a-deploy mixing.  A single deploy is always all-or-nothing — RAM-mode CP exec's the whole staged set or none of it; flash writes the whole set.  The Decision 0009 per-library model means the sweep is *N sequential, independent deploys* (the same shape `scripts/run.py test` already uses: per-package subprocess + per-library coverage), each internally single-mode.  Mode varies *across* the per-library deploys of one sweep; it never varies *within* a deploy.  These are different axes — the "no half-flash/half-RAM" rule (within a deploy) is unchanged; per-library mode selection (between deploys) is the structure that delivers the feature.  The exact batching granularity (strict per-library vs. a light-libs-RAM / heavy-libs-flash two-bucket split — coarser, fewer connect/stage cycles, but a 17-library RAM staging may itself OOM) is an implementation tradeoff for the workstream, not locked here; the ADR locks only the principle (resolve finer than whole-sweep; never mix within a deploy).

### 4. The supported matrix is explicit

| Shape | unix-port | on-device flash | on-device RAM |
|---|---|---|---|
| **unit** | default (no deploy) | supported (new command) | supported, **blessed for the new sweep** |
| **functional** | n/a | default (0047) | only when the suite stages no data files; otherwise the resolver loudly switches to flash |

"functional + RAM + staged data files" is **not** a supported combination — the unified resolver switches it to flash with an explanation, never silently drops the file.

## Consequences

- Resolves the `plans/open-questions.md` two-resolver divergence: one policy, loud not silent.  That open question is chartered here and removed from the file (this ADR + the workstream are the record).
- RAM mode keeps its strongest justification (on-device unit sweeps) and sheds its footgun (silent data-file drop on CP RAM).  The "rip RAM mode out" option is rejected: it is the only practical path to bulk on-device unit validation — unix-port misses real-silicon divergences (rp2 absent `MBEDTLS_PEM_PARSE_C`, non-compacting GC fragmentation, real `gc.mem_free`), and flash-cycling a board for a ~3800-test sweep is slow and wears flash.
- New `devices.yml` key, back-compatible (absent ⇒ both modes).  `chumicro-deploy` + `chumicro-pytest-device` minor bumps when implemented; the shared resolver lives in `chumicro-deploy` (pytest-device already depends on it).
- 0047 §3's "pre-flight check in chumicro-deploy" is superseded by the unified resolver; 0047 §3 is edited in place to cross-link here, its `requires_flash` schema decision unchanged.
- Phased implementation tracked in [`plans/workstreams/deploy-mode-unification.md`](../workstreams/deploy-mode-unification.md).

### Alternatives considered

- **Keep two resolvers, just add the missing check to the test one.**  Rejected: duplicated policy is what drifted into the silent-drop bug in the first place; a second copy will drift again.
- **Rip RAM mode out entirely.**  Tempting (a whole CP raw-REPL bootstrap subsystem, recurring footguns).  Rejected: it is the enabling mechanism for on-device unit sweeps, whose value this very TLS work demonstrated (unix-port hid the rp2 mbedTLS and fragmentation behaviors).  The footguns are all functional-test-with-assets concerns; unit tests are pure and don't trip them.  Narrow the blessed surface instead of removing the capability.
- **Make "functional + RAM + data files" a hard error.**  Rejected: inconsistent with 0047's established "classify, do the safe thing, explain" precedent (mirrors the `chumicro_deploy.recovery` layer).  Auto-switch + loud message is the house style.
