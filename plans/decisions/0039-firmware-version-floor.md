# Decision 0039: Firmware Version Floor

Status: `accepted`
Date: `2026-04-26`
Related: [Decision 0015](0015-board-architecture-support.md) (board support tiers), [Decision 0029](0029-project-workspace.md) (project workspace architecture), [`plans/workstreams/archive/beginner-onramp.md`](../workstreams/archive/beginner-onramp.md)

## Context

Phase 7 (2026-04-26) closed end-to-end on real hardware against current MicroPython 1.26 + CircuitPython 10.1 builds.  The post-Phase-7 audit surfaced that nothing in the workspace tooling validates the *firmware version* a board is running.  `chumicro_deploy.probe_device` returns a `DeviceImplementation` with `name` (`"circuitpython"` / `"micropython"`) and `version` (dotted string, e.g. `"10.1.4"` / `"1.26.0"`) — but no consumer compares it to a minimum.

A user buying an ESP32 online frequently lands on a board with **old firmware** (CP 7.x / MP 1.19) shipped from a vendor's pre-release run.  Today they would `add-device` cleanly, then hit confusing failures at deploy time when missing modules or runtime API gaps surface.  We need a floor that surfaces the mismatch up-front, ideally with the path to fix it.

The floors picked here come from the runtimes ChuMicro libraries actively target.  CircuitPython 10.x is the current stable line; 10.1.0 is the version where `microcontroller.cpu.uid` + the ESP32 wifi adapter shape used by `chumicro-wifi` stabilised.  MicroPython 1.27 is the next stable release (1.26 is current as of writing) — chosen because the `select.poll` + `socket.setblocking(False)` non-blocking contract used by `chumicro-sockets` and `chumicro-mqtt` is hardened in 1.27 across the rp2 + esp32 ports we test on.  1.26 will likely *also* work for most things; the floor is a "you're outside the tested matrix" signal, not a hard incompatibility wall.

## Decision

### Floors

- **MicroPython:** ≥ 1.27.0
- **CircuitPython:** ≥ 10.1.0

These floors are codified as constants in `chumicro_workspace.firmware_support`:

```python
MIN_MICROPYTHON_VERSION: tuple[int, ...] = (1, 27, 0)
MIN_CIRCUITPYTHON_VERSION: tuple[int, ...] = (10, 1, 0)
```

Floors are **per-runtime tuples**.  Bumping a floor is a non-breaking workspace-tool change — we accept the floor will move forward as the test matrix moves forward.

### Status enum

A `FirmwareSupportStatus` enum captures the four classifications the workspace needs to act on:

| Status | Meaning | UX |
|---|---|---|
| `SUPPORTED` | Probed runtime + version meet floor | Silent (registration / deploy proceeds) |
| `OLD` | Probed runtime matches CP/MP, version below floor | **Warn**, do not block.  Print the floor, the running version, and a pointer to `install-firmware`. |
| `UNKNOWN` | Probe parses but the runtime name isn't `circuitpython` / `micropython` | Warn, do not block.  Floors don't apply, but the user should know the workspace-tool's tested matrix doesn't cover this runtime. |
| `UNPARSEABLE` | Probe returned a `version` string that doesn't parse as dotted ints | Warn, do not block.  Likely a runtime that used a non-numeric version (rare) or a probe-output corruption. |

### Strictness: warn, do not block

The workspace tool **never refuses** to register or deploy a device based on the firmware floor.  Rationale:

1. False positives are likely (someone pinned to MP 1.26 for a board-specific patch — that should still work for most libraries).
2. The workspace tool already prints `next_steps` from `OnboardingDiagnosis` when probe fails outright; the floor warning is the same shape, lower severity.
3. A user who deliberately ignored the warning and hit a failure will still see the floor in the warning text + `install-firmware` as the documented fix.

A future Decision can promote OLD to a hard error per-runtime (e.g., if MP 1.26 turns out to break a library widely), but the default policy is warn.

### Wiring

The check is invoked at **probe time** — i.e., from `_cmd_add_device` after `probe_device` succeeds.  The probed `DeviceImplementation.version` is also persisted to `devices.yml` under the existing `firmware_version` probed-always field (it was registered in `PROBED_ALWAYS_FIELDS` at the schema level but never written before).  This lets future commands (a `bootstrap` wizard, future deploy preflight) read the floor compliance without re-probing.

The check is **not** wired into `_cmd_deploy` in this slice.  Deploy reads `devices.yml`'s stored `firmware_version` if present and *could* re-warn there, but that's UX surgery deferred until the bootstrap wizard lands — at which point the warning belongs in one place at the start of the chain, not redundant at every command.

### Wrong-runtime / no-firmware handling

These cases are already covered by `BoardState` in `chumicro_workspace.onboarding`:

- `UF2_BOOTLOADER` — board boot-mounted as a UF2 drive.  `add-device` already aborts with the install-firmware suggestion.
- `NO_PROBE_RESPONSE` — serial opens but probe doesn't return.  `add-device` already aborts; commonly an ESP32 in ROM bootloader with no Python firmware.
- `SERIAL_UNREACHABLE` — port can't open.  Cable / permissions issue; `add-device` already aborts.

This decision adds the *fourth* case — `REPL_REACHABLE` but the running firmware is below the supported floor — without touching the existing three.

### Alternatives considered

- **Hard error on OLD.**  Rejected: too many edge cases (vendor patch builds, contributors testing intentionally-stale firmware, users who genuinely can't upgrade).  Warn-with-explain captures the intent without trapping users.
- **Floors at the chumicro-deploy layer.**  Rejected: deploy is generic transport.  The "is this firmware in our tested matrix" question is workspace-tool concern (it depends on the libraries the user pip-installed, and the workspace knows that map; deploy doesn't).
- **Per-library floors.**  Rejected for now: would require every library to declare a floor, the workspace tool to aggregate them, and a UI to surface "lib X needs MP ≥ 1.28 but you're on 1.27".  Useful eventually, premature today.  The single workspace-wide floor covers the common case.
- **Storing the floor in `devices.yml`.**  Rejected: the floor is a property of the workspace tool's tested matrix, not the user's project.  Codifying it in the package keeps it versioned with the tool and bumpable in lockstep.

## Consequences

- New module `chumicro_workspace.firmware_support` owns the floor constants + status enum + check function.  Future bumps land here.
- `_cmd_add_device` gains a post-probe warning emit.  No new positional args, no flag changes — purely additive output.
- `devices.yml`'s `firmware_version` probed-always slot starts being populated.  Existing entries written before this change have an empty `firmware_version`; that's fine — re-running `add-device --force` populates it.  No migration needed.
- `plans/workstreams/archive/beginner-onramp.md` Step 1 closes with this decision + the implementation slice that ships alongside it.
- The bootstrap wizard (Step 4 of beginner-onramp) will reuse the same `check_firmware_supported` + `explain_status` pair to drive the "your board is too old, want me to upgrade?" prompt — no second copy of the policy.
