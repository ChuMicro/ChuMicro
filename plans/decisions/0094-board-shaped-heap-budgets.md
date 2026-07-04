# Decision 0094: Board-shaped heap budgets for the unix-port lanes

Status: `accepted`
Date: `2026-07-03`
Summary: Unix-port lanes spawn with -X heapsize budgets from target-runtimes.toml [heap], measured on a real Pico W; MP runs statement-chunked, CP whole-file; overrides need measured justification.
Related: Decision 0047 (flash-mode default), Decision 0090 (deploy strips docstrings), audit finding H37

## Context

The unix-port lanes ran with the host's multi-MB heap, so a library whose import chain or test
workload could never fit a 264 KB board passed every preflight gate and MemoryError'd on first
flash — the "RAM-only dev loop" gap (H37).  Measured reference: a real Pico W frees 201,360 B
(MicroPython) and 126,288 B (CircuitPython) after boot.

## Decision

1. **Budgets live in `target-runtimes.toml [heap]`** — per-runtime defaults (MP `192K`,
   CP `120K`, both under the measured ceilings) plus `[heap.overrides]` per-library entries.
   `UnixPortBackend` spawns every worker with `-X heapsize=<budget>`; `--unix-port-heapsize`
   overrides for one run (`0`/`off` disables).  A missing `[heap]` table means no ceiling.
2. **Execution shape follows each runtime's production reality.**  MicroPython workers exec
   statement-chunked (boundaries computed host-side, delivered via the
   `CHUMICRO_CHUNK_BOUNDARIES` environment variable — the MP unix port FATALs on argv elements
   longer than a few hundred bytes), matching how real MP sweeps stage files.  CircuitPython
   workers exec whole-file, matching CP's flash-mode default (Decision 0047), and therefore pay
   the whole-file compile transient a real CP deploy pays.
3. **An override requires a measured justification in the commit adding it.**  Overrides are
   test-suite weight, not production claims: the lanes run unstripped sources while real deploys
   strip docstrings/comments (Decision 0090), and every library's bare production import measures
   ≤ 44 KB under the MP default.  A worker that MemoryErrors before its SUMMARY fails with the
   budget named and the override path coached.

## Consequences

- Import-time and test-time OOM against board-shaped heaps now fails preflight instead of the
  first flash deploy.
- The override table doubles as a debt register.  The 2026-07-03 slimming pass paid the
  file-shaped debt down: runner's override is gone entirely (its 1971-line `test_core.py`,
  split six ways, now fits both defaults), mqtt dropped to 256K/256K, websockets to
  240K/208K, requests to 224K/224K.  The remaining entries are measured floors, not fat —
  import chains alone need 192K (mqtt) / 144K (requests), and single tests legitimately
  hold large buffers (mqtt's bounded-recv drain, requests' 7-hop redirect chain).  Override
  convention: measured suite minimum plus one 16K step (heap layout flickers
  non-monotonically across 16K boundaries).
- Rejected: keeping the host heap and relying on real-board sweeps (opt-in, hardware-gated —
  exactly how H37 stayed invisible), and a single flat budget for both runtimes (CP frees 37%
  less than MP on identical hardware; one number would be wrong for both).
