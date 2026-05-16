# Handoff 2026-05-16 — deploy-mode unification Phase 4 + Decision 0069

## What this session was about

Resumed the `2026-05-15-deploy-mode-unification` handoff (Decision
0068).  Goal: land Phases 1–5.  Outcome: Phases 1, 2, 3, 4a, 4b +
Decision 0069 (new) shipped and CI-green; the on-device unit sweep
(Phase 4b) now exists and was driven on real hardware, which
root-caused the remaining Phase-4 work into two non-obvious design
questions now parked in `plans/open-questions.md`.

## What's in flight

Nothing uncommitted except the `plans/` edits committed *with* this
handoff (workstream 4b.2 precise-root-cause rewrite + the two
open-questions entries + this file + the next-up pointer).  Working
tree is otherwise clean; 13 commits pushed this session
(`0ca5c20a..` → `469f3e0b` and the handoff commit).

## What got done

- Decision 0068 Phases 1–3 (shared `resolve_deploy_mode` + `DeviceCaps`,
  pytest-device delegation, `devices.yml supports_ram_mode`), the
  runtime-agnostic switch-message reword, the 4-board TLS regression,
  and the RAM-stays-RAM proof — commits up to `0ac90d13`.
- Phase 4a (`cbc48ea9`): caller-scoped `staged_files` (own-src for the
  unit sweep, full closure for functional; `requires_flash` always
  full closure).
- Phase 4b (`df220788`): new `--target device-unit` collection mode +
  `scripts/run.py test-unit-on-device` (per-library mode resolve →
  group by mode → one single-mode session per (runtime, mode)) +
  `preflight --with-device-unit`.
- **Decision 0069** (`7804f31a` accept, `03311b1d` implement):
  `testing.py`'s false `__chumicro_runtimes__=("cpython",)` replaced
  with explicit `__chumicro_test_support__ = True` +
  `is_test_support_module()`; product/bundle always-exclude, the
  `device-unit` sweep includes via `stage(include_test_support=True)`.
  0037 §3/§5 + 0044 + AGENTS edited in place.  **Verified on
  hardware** (Pi Pico W CP `device-unit` flash: `timing` 29/29,
  `wifi` 41/41, `runner` 61/61 standalone — was a mass ImportError
  before).
- Phase 4b.2 root-caused (`3dcf1193`, `469f3e0b`) — see below.

## What was learned

The "Phase 4 multi-library sweep is broken" symptom resolved into two
**independent** problems, both now in `plans/open-questions.md` with
full detail and both recorded in `workstreams/deploy-mode-unification.md`
4b.2.  One-line each so the next session has the gestalt:

- **(i)** The sweep's scope assumption (every `tests/test_*.py`
  non-`_pytest` is a device test) is wrong for the 6
  `test_{mp,cp}_{adapter,*backend}.py` files — they import a
  runtime-specific source module the 0044 filter correctly strips on
  a non-matching board.  The tests are *correct for unix-port*; the
  sweep scope is the bug.
- **(ii)** A real, deterministic full-scale degradation: a 254 s /
  663-test Pico W CP flash sweep dies mid-run (`.FFFF` after ~67 %)
  even for libraries that pass standalone.

Every library passes standalone and in small combos on real silicon —
neither issue is a per-library test defect nor a 0069 regression.

## Decisions made (not yet captured in ADRs)

Both remaining problems are flagged as needing a design decision
*before* implementation (per the user's "don't fix if there's a valid
reason to discuss" standing guidance).  They are written up as the two
new entries in `plans/open-questions.md` — read those, not a summary
here.  (i) is likely its own ADR — a host-only/unix-port-lane
classification marker, shaped like Decision 0069's
`__chumicro_test_support__`.

## To re-research / verify next session

- The user must choose the (i) classification mechanism and the (ii)
  scale-degradation approach (options are enumerated in
  `open-questions.md`).  Both are blocked on that input — do not
  start implementing either without it.
- (ii) needs hardware iteration once an approach is chosen; the repro
  is deterministic (see rebuild section).

## Dead ends (do not re-walk)

- **"Host-only" framing flip-flopped twice.**  Settled: the 6
  `test_{mp,cp}_*` files are *correct for the unix-port/CPython lane*
  (verified green: MP unix-port 16/16, CP unix-port 16/16, CPython
  14/14).  They are not "wrong tests" and not fixable with a blanket
  `__chumicro_runtimes__` marker (that kills the deliberate
  `test_runtime_acquisition_raises_*_on_cpython` and a *matching*
  real board would fail it too — real `esp32` exists ⇒ no raise).
  The fix is a sweep-scope classification, full stop.
- **"The cascade is transient board state."**  Partly true — the
  *first* wifi mass-fail was a stale evicted-transport artifact and
  never reproduced.  But the deeper full-sweep degradation (ii) is
  deterministic (reproduced 2× identically).  Don't dismiss (ii) as
  transient again.
- **"~16-lib RAM session stages everything at once → OOM, sub-group
  it."**  Wrong mental model — retired.  Staging is per-library (RAM:
  per-file restage + soft-reset; flash: rsync `--delete` per library
  switch).  Nothing stages all libs at once.  (ii) is the
  flash-at-scale analogue, but it's churn/exhaustion over a long
  session, not a bulk-stage OOM.
- Threading `include_test_support` was considered as a transport
  instance attr vs a param through every walk — instance attr won
  (set per `stage()` call); already implemented, don't redo.

## How to rebuild context fast

- Read **`plans/workstreams/deploy-mode-unification.md`** Status
  section end-to-end (4a/4b done; 4b.2(i)+(ii), 4c, 4d, Phase 5
  remain) + the two new **`plans/open-questions.md`** entries
  ("How does a unit-test file opt out…" and "How does the on-device
  sweep survive a full-scale run…").
- Read **Decision 0069** (the test-support marker — the model the
  (i) fix should mirror) and the in-place edits to **0037 §3/§5** +
  **0044**.
- `git --no-pager log --oneline 0ca5c20a..469f3e0b` — the full
  Phase 1→4b.2 arc; commit bodies carry per-step rationale.
- Key code: `chumicro_deploy.runtime_marker` (`is_test_support_module`,
  `file_targets_runtime`); `pytest-device/plugin.py`
  (`_target_is_device_unit`, `_device_is_unit_sweep`,
  `_session_effective_deploy_mode`, the two `transport.stage(...,
  include_test_support=)` call sites); `scripts/run.py`
  `test_unit_on_device`.
- Repro recipes (Pi Pico W CP, all 4 boards healthy):
  - (i) `.venv/bin/python -m pytest libraries/kvstore/tests/test_mp_nvs_backend.py --target device-unit --runtime circuitpython --circuitpython-device pi-pico-w-circuitpython-board --deploy-mode flash -x` → `ImportError: no module named 'chumicro_kvstore._backends.mp_nvs'`.
  - (ii) `.venv/bin/python scripts/run.py test-unit-on-device --runtime circuitpython --circuitpython-device pi-pico-w-circuitpython-board --deploy-mode flash` → ~193 failed / 470 passed, `runner/test_core` + `wifi/test_wifi` `.FFFF` from ~67 %.
  - Sanity (all green): same file/lib standalone, or `timing`+`runner`
    / `kvstore`+`runner` two-lib combos.

## Gotchas

- **All 4 boards are currently healthy.**  Lolin S2 CP self-recovered
  from the earlier safe-mode wedge (the `reset-board` FS-wipe removed
  the crashing payload; CDC came back after timeout).  `probe` all 4
  passes.
- **`wifi` under RAM on CircuitPython hard-crashes the board** (USB
  CDC drop → safe mode; this is the separate 4c item, "report before
  fixing").  Until 4c: run **CP** sweeps with `--deploy-mode flash`
  only.  MP RAM (= mount) did not crash.  The default
  `test-unit-on-device` (RAM-preferred) WILL group `wifi` into a CP
  RAM session and crash a CP board — use `--deploy-mode flash` on CP
  for now, or scope `--library`.
- A wedged CP board: `chumicro-workspace reset-board --yes --device
  <id>` wipes the FS (clears the boot-loop payload); CDC may need a
  replug or a timeout to re-enumerate.  Don't manually
  unmount/eject (AGENTS rule).
- Within one `pytest` invocation, once the transport is evicted
  (recover failed), every subsequent file in that run fails
  `Device not configured` — a within-run cascade distinct from (ii).
  When triaging, re-run the suspect file *alone* to separate real
  failures from cascade noise.
- `scripts/run.py test-unit-on-device` flash group runs **before** the
  RAM group by design (slower/wear-incurring session first).
