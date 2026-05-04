# Decision 0004: Sample library first slice

Status: `accepted`
Date: `2026-03-29`
Related: Decision 0003 (test boundaries), Decision 0007 (cross-platform deps)

## Context

ChuMicro needs a first publishable library that proves the workspace design across CPython, MicroPython, and CircuitPython without pulling in too much embedded complexity too early.

## Decision

Use an Option B sample library: mostly pure logic plus one small hardware-facing seam.

The first seam will be timing / ticks. Digital I/O is the likely next seam once the timing contract is proven.

## Consequences

- the first sample package should stay small and readable
- the package should prove host-side `pytest` tests, compatibility-minded runtime code, and at least one device-aware test path
- networking, storage, and other higher-risk seams remain deferred until the smaller timing contract is stable
