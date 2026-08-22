# Decision 0124: `chumicro-buttons` and `chumicro-knobs`, no shared base

Status: `accepted`
Date: `2026-08-21`
Summary: Physical input ships as `chumicro-buttons` and `chumicro-knobs`, no base library and no cross-dep; each adapter captures edges however its runtime allows, with no user-facing knob.
Related: [Decision 0014](0014-runner-pattern.md) (runner contract, which named buttons), [Decision 0051](0051-runner-shaped-as-project-policy.md) (runner-shape as project policy), [Decision 0010](0010-library-testability.md) (constructor injection, `testing.py`), [Decision 0042](0042-library-dependency-policy.md) (dependency policy), [Decision 0037](0037-runtime-file-marking.md) / [Decision 0044](0044-deploy-time-runtime-filtering.md) (runtime marking + deploy filtering), [Decision 0065](0065-device-library-scaffolding-cost.md) (no pure-passthrough `@property`), [Decision 0015](0015-board-architecture-support.md) (supported board class), `plans/workstreams/library-pipeline.md` §"Tier B" (the implementation contract and its open hardware gates).

## Context

Decision 0014 named buttons as one of the libraries its `check(now_ms)` / `handle(now_ms)` contract was designed for, and `library-pipeline.md` §"Tier B" sketched a single `chumicro-input` covering buttons, matrix, encoder, and analog together.  Two facts argue against that shape.

The first is install cost.  Decisions 0044 and 0062 keep unreached modules off a device on the workspace deploy path, but `circup install` and `mip install` copy the whole package, so a one-button project on those paths would carry quadrature decode and ADC smoothing it never calls.

The second is that the runtimes diverge on what matters most for a button: catching a tap that lands between two passes of the loop.  CircuitPython's firmware scans keys in the background and stamps each edge with the time it happened.  MicroPython ships no equivalent, so the only mechanism that does not lose the tap is a pin interrupt, and getting one right means keeping debounce and every decision out of the handler.  That is the set of details a beginner gets wrong.

## Decision

### Two libraries, no base

`chumicro-buttons` owns every input that reads as on or off: `Button` and `Buttons` in `core.py`, `KeyMatrix` in `matrix.py`.  `chumicro-knobs` owns every input that holds a position: `Encoder` and `AnalogKnob`.  Both publish `delta` and are runner-shaped, but the reading itself is named for the device: an encoder reports `position` because it counts movement from wherever it started, an analog knob reports `value` because it points somewhere absolute.  Forcing one name across both would be false symmetry.

Neither library depends on the other, and no base library sits under them.  What a base would hold is a three-line settle-window compare, an adapter-selection ladder the workspace already duplicates by policy across `sockets`, `wifi`, and `kvstore`, and a duck-typed runner contract that needs no import at all.  `chumicro-timing` is the only shared dependency, declared per [Decision 0042](0042-library-dependency-policy.md) Class 1.

An encoder's push switch is a `Button` from the other library, wired together by the application and never by a cross-dep.

### The matrix is a source, not a library

A matrix key's events are button events; only the scan differs.  Splitting the matrix into `chumicro-keypad` would mean writing the long-press and repeat layer twice, or hoisting it into the base library this decision rejects.  It lives in `chumicro-buttons` as its own module, reached by an explicit `from chumicro_buttons.matrix import KeyMatrix`, so the deploy walker leaves it off boards that only have discrete buttons.

### The library owns the interrupt, the user never writes one

A press that outlives no pass of the loop is still a press the user made, so the library captures it.  Where the runtime captures in its own C, that is what the adapter uses and no Python interrupt is needed.  Where it does not, the library installs the interrupt itself and hides it, because the alternative is every user hand-rolling the same handler.

A library-owned capture interrupt is bound by four conditions:

1. **It stays cheap.**  Buffers are sized at construction and the handler stores into slots that already exist, so capture costs nothing on the hot path.
2. **It captures, it does not decide.**  Raw state and a timestamp go into the buffer.  Debounce and every event built on duration run on the shared tick, in normal context.
3. **No user code runs in interrupt context.**  Callbacks are dispatched from `handle`, so a callback that allocates, prints, or raises stays harmless.
4. **Overflow is bounded and flagged.**  A full buffer drops the newest edge and sets `overflowed`.  The condition binds handlers that queue; one that folds each edge into a counter has nothing to drop and publishes no such flag.

This narrows the blanket "No ISRs" line in `AGENTS.md` §"Library code rules".  What that rule protects is the cooperative model: no application control flow in interrupt context, nothing that can preempt the tick loop into an inconsistent state.  A handler meeting these four conditions takes nothing away from it.

There is no knob for any of this.  No `capture=` argument, no interrupt mode, no opt-out.  Catching the press someone actually made is the behavior of a button library, not a setting, and a switch would only hand the user back the question the library exists to answer.

Polling stays correct where an edge cannot be missed by definition: a matrix scan is inherently polled, and an ADC has no missed-edge concept at all.

### One debounce knob

`settle_ms=20` is the default and a lower value suits a signal that arrives already filtered.  There is no mode enum.  Wiring is documented in the library guide with schematics, and stops at a capacitor: arrangements that need logic gates are a different hobby from the one this library serves.

### Per-tick state is plain attributes

`check(now_ms)` updates the readings in place and `handle(now_ms)` dispatches the callbacks.  Readings are valid for the current tick, which costs no allocation and needs no consume semantics, and they are public attributes rather than properties per [Decision 0065](0065-device-library-scaffolding-cost.md).

## Consequences

`library-pipeline.md` §"Tier B" loses its `chumicro-input` row and gains these two, and carries the implementation contract, the measured sizes, and the open hardware gates.

The MicroPython adapter carries the weight in both libraries, and that is the point rather than a regret.  CircuitPython users are buying a thin pass over firmware that already exists; MicroPython users are buying the interrupt handler they would otherwise write wrong.  The asymmetry in the source is what makes the API symmetric for the user.

A knob with a push switch means two installs.  That is the price of keeping the dependency graph a DAG, and it teaches the right idea: the click is a button.
