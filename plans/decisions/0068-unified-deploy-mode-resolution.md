# Decision 0068: Unified deploy-mode resolution + on-device unit sweeps

Status: `proposed`
Date: `2026-05-15`
Related: [Decision 0047](0047-deploy-mode-flash-default.md) (flash default + `requires_flash`; this decision unifies and extends its §3 auto-switch), [Decision 0028](0028-deploy-modes.md) (RAM/flash transport semantics), [Decision 0027](0027-device-testing-infrastructure.md) (device-test infra + `devices.yml` schema), [Decision 0016](0016-cross-runtime-unit-tests.md) (the cross-runtime unit suite this lets run on hardware).

## Context

Decision 0047 flipped the default to flash, added the `[tool.chumicro] requires_flash` library flag, and added a RAM→flash auto-switch.  Two gaps surfaced since:

1. **The auto-switch lives in only one of two deploy-mode resolvers.**  `Deployer._effective_device_for_source` (chumicro-deploy / CLI / production) applies force → device-not-ram → non-`.py` data file → `requires_flash` lib → configured mode.  The `chumicro-pytest-device` functional/on-device path uses a *separate* resolver, `resolve_effective_deploy_mode` (`_test_runner.py`): CLI override → devices.yml per-device → global default, with **no source inspection at all**.  CP RAM-mode source staging *silently skips* non-`.py` files, so a RAM functional run that stages a data file (e.g. `_ca_bundle.der`, pulled in transitively by any sockets-TLS-touching test) silently drops it — confusing failure, no hint.  Duplicated policy that drifted is exactly the bug.
2. **RAM mode's strongest justification has no first-class entry point.**  RAM mode's real value is bulk cross-runtime *unit* tests on real silicon — pure (no wifi, no data files, no `runtime_config`), high-volume, wear- and speed-sensitive (a full ~3800-test on-device sweep in flash = thousands of writes + `sync`s + flash wear per run).  Unit tests don't hit any of RAM mode's footguns.  But there's no command for it; it's only reachable ad hoc.

## Decision

### 1. One resolver, one rule, no context flag

A single deploy-mode policy — `resolve_deploy_mode(configured_mode, *, staged_files, device_caps, requires_flash_libs, force) -> (mode, message | None)` — owned by `chumicro-deploy` and consumed by both `Deployer` and `chumicro-pytest-device`.  It is applied per **resolution unit**: a single deploy for `Deployer`; a single library's test suite for the sweep (§3).  There is no context parameter — the same rule applies everywhere:

1. `force` set → that mode, no further policy (the "I know what I'm doing" escape hatch).
2. Device declares `supports_ram_mode: false` (§2) and `ram` requested → flash.  A board that can't RAM can't RAM.
3. Configured mode is `ram` **and** the resolution unit's library is `requires_flash` → flash.  It OOMs on *import* in RAM on a small board (Decision 0047); the import happens regardless of test shape.
4. Configured mode is `ram` **and** the resolution unit's staged set contains a non-`.py` file → flash.  Applied uniformly — no "is this a pure unit test that happens not to open it" analysis.  Conservative (a library shipping a data file, e.g. `chumicro_sockets`'s `_ca_bundle.der`, runs flash even where its unit tests wouldn't read it) but simple, safe, and the cost is borne only by the few libraries that ship data files — the rest still ride RAM.
5. Otherwise → the configured mode unchanged (a RAM preference stays RAM).

`configured_mode` is resolved first by the existing precedence: CLI `--deploy-mode` → per-device `deploy_mode` → `devices.yml` global `defaults.deploy_mode` → `DEFAULT_DEPLOY_MODE`.  The rule then gates that preference by board capability (2) and the unit's own requirements (3–4).  So a global `ram` preference *stays RAM* for every library that supports RAM on a board that supports RAM, and only the specific library suites that trip 2–4 fall to flash.

Whenever 2–4 override the request the resolver returns a human-readable message; the caller emits it and **continues** (no silent skip, no aborted run — the "do the safe thing, explain it" philosophy of 0047 §3).  This makes the pytest-device path loud where it is silent today and removes the duplicated, drift-prone second policy.

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

A new `scripts/run.py` task runs the cross-runtime *unit* suite (the suite that otherwise runs on unix-port) on real boards.  **Not** in default preflight.  `preflight --with-device-unit` is an opt-in flag that appends it, parallel to `--with-functional`.

The sweep applies the §1 rule **per library suite**, then groups libraries by resolved mode and runs each group as **one single-mode device session**.  With a `ram` preference on a RAM-capable board: a RAM session over the libraries that resolved to RAM, then a flash session over those that resolved to flash (`requires_flash` libs + libraries shipping a data file).  With a `flash` preference, or a board that can't RAM: one flash session over everything.  Each session reuses the **existing** per-library staging untouched — flash re-stages per library with rsync `--delete` cleaning the prior library off (`plugin.py` ~L816-821); RAM re-stages per file with a soft-reset between (`plugin.py` ~L1254-1265, which exists precisely so the previous file's RAM doesn't stack and OOM the next).  No new isolation machinery, no mid-session mode switching: a session is one mode, the grouping is computed once up front.  This is why a single global `ram` preference still gets RAM speed + zero wear for the ~16 light libraries while only the heavy/data-file ones fall to flash — without it the feature is inert (the full suite always contains a `requires_flash` library, so a single-mode sweep is always flash).

### 4. The supported matrix is explicit

| Shape | unix-port | on-device flash | on-device RAM |
|---|---|---|---|
| **unit** | default (no deploy) | supported | supported; light library suites ride RAM, heavy/data-file suites grouped into a flash session |
| **functional** | n/a | default (0047) | honored unless the §1 rule forces a deploy to flash (then loud, never a silent file drop) |

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
- **Per-library mode resolution with the transport switching mode mid-sweep + a `context` parameter on the resolver.**  An earlier draft of this ADR.  Rejected: deploy mode is session-scoped today (the transport is cached per device), so per-library mode would mean tearing down and re-standing the transport between libraries, plus a `context` flag to scope which triggers apply.  Computing each library's mode up front and grouping same-mode libraries into one single-mode session per group delivers the identical outcome with no mid-session switching, no context flag, and zero changes to the existing per-library staging — strictly simpler.  The "within-deploy vs across-deploy mixing" distinction the earlier draft had to spell out simply disappears: every session is one mode.
