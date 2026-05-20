# Troubleshooting

Operational recovery guides — paste-this-command fixes for failures that take more than a one-line inline hint to resolve.

Not everything belongs here.  A lot of troubleshooting in ChuMicro is inline where it's needed: the `chumicro-deploy` CLI coaches users through `PORT_UNAVAILABLE`, `RAW_REPL_UNRESPONSIVE`, `CIRCUITPY_DRIVE_MISSING`, and most other failure kinds with 2–3 bullet fix-steps at the point of failure.  Lint, test, and coverage errors do the same via their own messages.  The cheat-sheet has a one-line pointer per common failure.

Content lands here only when:

- The recovery is **multi-step and context-heavy** (a sudo chain with rationale for each piece; a reproduction protocol that's hard to compress).
- The symptoms are **cross-component** — confusing because the proximate error doesn't name the root cause.
- The inline coaching would have to say more than ~3 bullets to be actionable.

## Guides

- [**macOS CIRCUITPY deploy troubleshooting**](macos-circuitpy.md) — the FSKit / DiskArbitration wedge, stale-mount EACCES after Finder eject, multi-board drive disambiguation, and the Finder-sidebar regression caveat.
- [**CircuitPython unix-port RingIO build failure**](circuitpython-ringio.md) — why a `VARIANT=standard` build fails (compile vs linker, by CP version), why CP's CI never catches it, and why RingIO is dead code in CircuitPython.

## Related

- [`docs/contributing/cheat-sheet.md`](../contributing/cheat-sheet.md) — one-line fixes for common lint / test / coverage / device-setup failures.
- [Device testing guide](../contributing/device-testing.md) — configuring `devices.yml` and running `functional_tests/`.
