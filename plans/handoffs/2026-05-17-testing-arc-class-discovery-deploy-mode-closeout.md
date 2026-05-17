# Handoff 2026-05-17 — testing-arc closeout: class discovery, Decision 0072, deploy-mode-unification complete

## What this session was about

Opened from "we did a lot of iteration on testing, find out where we are
and where we need to go." It became a long multi-hour arc that resolved
the entire cross-runtime-testing thread the previous days had left
half-open, plus closed the deploy-mode-unification workstream. The user
steered actively throughout (chose chunked-exec over mpy-cross, refined
the per-file policy away from a rigid cap, requested the audit + split,
asked for 4c). Boards were physically connected and healthy for the
bench portions.

## What got done (all committed + pushed)

Commit chain `7346a949 → bd0195cd` (12 commits). Highlights:

- **Cross-runtime harness class discovery** (`7346a949`, `36cac07a`):
  the gap was host-side only — the on-device runner already discovered
  `class Test*`; `_parse_test_functions` was function-only. Extended to
  emit identical `ClassName.test_method` names; 17 interim markers
  reverted; one real defect fixed (`sockets cp.ssl_context_with_ca`
  imported ssl before its PEM/DER validation), `sockets` 0.6.2→0.6.3.
  4-board on-device validated: PSRAM boards 288/0/0 CP+MP.
- **Decision 0072** (`5bb0a737`) — the two-wall OOM contract:
  wall 1 compile transient → **chunked exec** (`4fef7f63`); wall 2
  resident co-residency → opt-in **`--per-file`** reset (`265e3442`)
  + a documented non-mechanized reactive-split caution. Edited 0016 +
  0071 in place; resolved open-questions thread 1.
- **`requests` test-quality audit** (Opus sub-agent) → suite **not**
  over-tested (redundancy ~2); comment-hygiene fixed (`239217ed`); then
  the **split** (`bd0195cd`): `test_requests.py` → `test_wire.py`
  (89 tests) + `test_client.py` (83), 172 preserved byte-identical.
- **deploy-mode-unification 4c falsified + 4d done + Phase 5**
  (`1ea94cf0`, `4eb4e670`): the workstream is **COMPLETE** (all phases
  1–5; 4b.2 via 0070/0071, 4c falsified, 4d done).

## Mental model snapshot (the load-bearing frame)

The 264 KB-board OOM is **two independent walls**, do not conflate:

1. *Compile transient* — MP/CP compile a whole `exec()` arg at once; a
   ~1200-LOC module's compile peak alone exceeds 256 KB. Fixed by
   chunked exec (host AST-segments, device execs per-statement chunks
   into one shared namespace).
2. *Resident co-residency* — one large test module's defs + the library
   + the harness, all alive at once, exceeds 256 KB **even on a freshly
   reset board running that file alone**. This is NOT Decision 0071's
   cumulative `sys.modules` (single-file-fresh still OOMs). Chunked
   *compile* cannot fix a *resident* ceiling. Levers: `--per-file`
   reset (mechanism) + split the file to mirror its source module
   (policy). Both are needed together; either alone is insufficient.

`--per-file` is the *enabling mechanism*; its visible payoff only
appears paired with the reactive splits. On mqtt/websockets it shows no
pass-count change because their failures are single files individually
over the ceiling — that is the documented 0072 case, not a bug.

## Riskiest assumption

**4c "falsified" rests on:** `wifi --deploy-mode ram` on CP passing
**41/0** alone on both Lolin S2 (PSRAM) and Pi Pico W (264 KB) and
**39/0** in the cumulative Pico W RAM sweep, with zero
hard-fault/safe-mode signatures and a healthy post-run probe.
[VERIFIED: this session, `scripts/run.py test-unit-on-device --library
wifi --runtime circuitpython --deploy-mode ram` on each board +
full-sweep log grep showing only `MemoryError`, never hard-fault; the
"28 fault matches" were all `PASS TestIsEagain.test_errno_*`
false-positives]. The belief that could still be wrong
[HYPOTHESIS: cheapest test = re-run the full CP RAM sweep on Pico W and
re-probe; if it ever safe-modes (vs a clean recoverable `MemoryError`)
4c reopens]: that the *original* "USB-CDC drop → safe mode" symptom was
purely the pre-0069 `testing.py` ImportError artifact and not a rare
cumulative/firmware-state condition. The evidence strongly favors
"artifact" (a real defect would fault on both boards; it faults on
neither), but the original severe symptom was real to whoever filed it.

## What was learned (durable signal already routed — pointers only)

- Two-wall model + per-file mechanism + reactive-split policy →
  **[Decision 0072](../decisions/0072-large-test-modules-on-constrained-boards.md)**
  (the authoritative record).
- Heavy `_wire`-backed libraries' fresh per-file ceiling ≈ **32–61
  tests/file** on Pico W CP [VERIFIED: coarse single-file ladder this
  session — `sockets/test_factories` 32 passes, `websockets/test_server`
  61 OOMs]. Library-weight-dependent, not universal — why there is no
  rigid cap. Recorded in open-questions thread 1 + 0072.
- 4c root cause + 4d grouping/non-poisoning verified on silicon →
  `plans/workstreams/deploy-mode-unification.md` Status (4c/4d marked
  done in place).
- The `requests` audit's punch-list lives in the conversation only
  (sub-agent output); its actionable conclusions are routed (split done,
  comment fix done, "not over-tested" recorded in the workstream + 0072).

## Dead ends

- **Hunting for an accumulation-flip case to "prove" `--per-file`
  works on hardware.** mqtt and websockets failures are single-file
  over-ceiling, not within-library accumulation, so `--per-file` shows
  identical pass counts there. This is *expected* per 0072 — don't
  re-spend bench time looking for a library whose mid-files
  accumulate-then-pass-fresh; the mechanism is unit-test-proven and the
  hardware confirms the predicted ceiling boundary. The visible payoff
  arrives only with the splits.
- **First chunked-exec implementation used `{1, *gen}` set unpacking
  (PEP 448)** → `SyntaxError` on CircuitPython at import. `discovery.py`
  runs on-device; device code must be MP/CP-safe (plain list ops). Cost
  a hardware round-trip. Fixed; noted as a gotcha below.

## To re-research / verify next session

- Nothing blocking. If touching the on-device sweep again, re-probe the
  4 boards first (state below is point-in-time).
- The remaining websockets/http_server/mqtt_client splits are
  **reactive, not preemptive** — only do them if/when they block a
  256 KB on-device sweep. Suite is audit-confirmed not over-tested, so
  do not split for tidiness.

## How to rebuild context fast

- `git --no-pager log --oneline -14` (the `7346a949..bd0195cd` chain).
- Read in order: [Decision 0072](../decisions/0072-large-test-modules-on-constrained-boards.md),
  `plans/workstreams/cross-runtime-harness-class-support.md` (Status +
  the "two memory walls" section), `plans/workstreams/deploy-mode-unification.md`
  (the COMPLETE banner + 4c/4d Status), `plans/open-questions.md`
  thread 1.
- Code touchpoints: `support/test_harness/src/chumicro_test_harness/discovery.py`
  (`_exec_chunked`), `workbench/pytest-device/src/chumicro_pytest_device/plugin.py`
  (`_session_per_file`, the `is_filesystem_mode` per-file branch,
  `_per_file_reset_done`), `workbench/pytest-device/src/chumicro_pytest_device/_test_runner.py`
  (`chunk_boundaries_for`), `scripts/run.py` `test_unit_on_device`.
- Split: `libraries/requests/tests/test_wire.py` + `test_client.py`
  (was `test_requests.py`); `git show bd0195cd` for the rationale.

## Next pickup (no bench needed)

The whole testing arc is resolved. The main remaining non-bench item is
**audit-remediation Phase 0** — 3 decisions already filed in
`plans/open-questions.md` (msgpack decode trust boundary; coverage-gate
honesty; prose-lockstep → mechanization), each blocking later phases of
the `audit-remediation-and-drift-mechanization` workstream. That, the
older `workspace-library-curation` handoff pointer (separate, untouched
this session), and the reactive splits are the open fronts.

## Gotchas

- **Boards: 4/4 healthy as of write — re-probe on resume.** Lolin S2 CP
  10.1.4, Pi Pico W CP 10.2.0, Lolin S2 MP 1.27.0, Pi Pico W MP 1.28.0.
- **Device code (`support/test_harness/`, `libraries/*/src/`) must be
  MP/CP-safe** — no PEP 448 set/dict unpacking, no CPython-only syntax.
  Cost a hardware round-trip this session. ruff doesn't catch this; the
  unix-port lanes do (`pytest ... --target unix-port --runtime
  micropython`). Run those before trusting on-device harness changes.
- **Verify sub-agent concrete claims before acting.** The `requests`
  audit (Opus sub-agent) over-claimed: 3 deleted-test references → only
  1 real (`_wire.py:549`); "test_wire.py needs no helpers" → wrong
  (`canned_response` used by one wire class); implied `make_factory`
  dead → `make_client` calls it. All caught by reading the code; none
  trusted blind. The audit's *judgments* (not over-tested, the split
  shape) held; its *line-level specifics* did not.
- **deploy-mode-unification.md is COMPLETE but left in place** (not
  moved to `workstreams/archive/`) to avoid churning the inbound links
  from Decisions 0068/0070/0071/0072. If archiving later, fix those
  links.
- The `requests` split duplicated the 10-line `canned_response` builder
  into both files rather than introduce a shared cross-runtime helper
  module (the on-device harness would have to stage it). Intentional;
  proportionate for a split.
