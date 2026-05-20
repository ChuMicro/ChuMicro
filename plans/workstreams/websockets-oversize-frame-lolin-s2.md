# Workstream: `websockets` oversize-frame length on Lolin S2

Status: **proposed.**  Surfaced 2026-05-16 during the four-board example campaign.

## Problem

`libraries/websockets/functional_tests/test_drop_with_event_drains_oversize_and_stays_open` reports an oversize-frame length of **600** bytes on Lolin S2 (deterministic on both MicroPython *and* CircuitPython); the test expects a length in `(0, 400]`.  The same test passes on Pi Pico W.

Real S2-specific websockets / buffer-chunking behaviour question, not environmental — the campaign's other findings closed cleanly:

- Fragmentation suites deleted.
- CP-RAM `ntp` ceiling characterized under [Decision 0072](../decisions/0072-large-test-modules-on-constrained-boards.md).
- Network-bench gap was an environmental subnet / `mosquitto` mismatch.

(All three closed in their target workstreams / git history.)

## Notes

The `(0, 400]` upper bound came from the test's design contract — the drain-with-event path is supposed to surface a *header-sized* length so the application can decide whether to keep reading.  600 bytes on S2 suggests an extra body-side chunk landing in the recv buffer before the drain decision fires.  Whether the right fix is on the test side (loosen the contract on S2) or the library side (tighten the drain accounting on the S2 substrate) is the open question.
