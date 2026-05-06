# Workstream: Lolin S2 CP wedges on multi-file `--library wifi` sweep — regression bisect

Status: **proposed** (filed 2026-05-05 from on-device hardware validation during the [`on-device-config-dogfooding`](on-device-config-dogfooding.md) close-out).

> **This is a regression.**  CircuitPython on the Lolin S2 (ESP32-S2) used to be a reliable target for the full `--library wifi` functional-test sweep.  It now wedges deterministically (or near-deterministically — see "What didn't reproduce" below).  Several recent sessions have not re-validated this board's full-sweep path; the regression has been latent across 60+ commits.

## What's broken

Running the full functional-test sweep for any one library on `lolin-s2-circuitpython-board`:

```bash
python scripts/run.py test-libraries-functional \
    --library wifi \
    --runtime circuitpython \
    --deploy-mode flash \
    --circuitpython-device lolin-s2-circuitpython-board
```

Wedges the device's USB stack mid-run.  Symptoms:

* `Setup — CircuitPython` synthetic item **passes** (rsync to CIRCUITPY drive completes).
* `Run overhead — CircuitPython` for the **first** test file (alphabetically `test_acceptance.py`) **fails** with `[Errno 6] Device not configured` on a host CDC write inside `transport.execute(bootstrap)`.
* Every subsequent test item fails with `[Errno 6]` (initially) or `[Errno 2] No such file or directory: '/dev/cu.usbmodem...'` (~7 s later) as the host kernel removes the now-dead serial nub.
* The board's USB-CDC interface stays dead until physical power-cycle.
* Host-side `/dev/cu.usbmodem487F301F02241` typically remains visible for several seconds *after* the device-side CDC has died, then disappears.  This is consistent with macOS IOKit lazily reaping a serial nub whose USB endpoint has stopped responding.

## Reproducer (intermittent)

**The wedge is intermittent, not deterministic.**  Direct observation in
the filing session: the same `--library wifi --runtime circuitpython
--deploy-mode flash --circuitpython-device lolin-s2-circuitpython-board`
command produced **two wedge runs** (~35–45 s, 18 failed + 1 passed,
USB stack dies) and **at least one clean PASS run** (12 s, 19 passed,
port PRESENT throughout) within the same hour, on the same board, with
the host environment unchanged between attempts.

So the bug requires *some additional condition* beyond "run the
multi-file sweep" — possibly recent device state, recent host state,
or some external factor (USB-hub negotiation, kernel scheduling,
thermal) we haven't yet pinned down.  This is the single biggest
blocker for the bisect: **without a reliable reproducer, every "fix"
candidate is a coin flip.**  Step 1 of the investigation plan is
explicitly to lock that down before any code changes.

When the wedge does fire, the failure shape is consistent:

* `Setup — CircuitPython` synthetic item passes.
* `Run overhead — CircuitPython` for the first test file
  (alphabetically `test_acceptance.py`) fails with
  `[Errno 6] Device not configured` on a host CDC write inside
  `transport.execute(bootstrap)`.
* All subsequent items fail with `[Errno 6]` initially, then
  `[Errno 2] No such file` once the host kernel removes the dead
  serial nub (~7 s later).
* The board's USB-CDC stays dead until physical power-cycle.

Single-file runs of every wifi test file pass cleanly on Lolin S2 CP.
Multi-file runs sometimes wedge, sometimes pass.

## What's been isolated

Each test file in the wifi suite **passes individually** on Lolin S2 CP:

* `pytest libraries/wifi/functional_tests/test_acceptance.py ...` — passes 5/5 in ~25 s, including the real-AP connect.
* `pytest libraries/wifi/functional_tests/test_cp_adapter_on_device.py ...` — passes 8/8 in ~5–18 s.
* `pytest libraries/wifi/functional_tests/test_lazy_loading_on_device.py ...` — passes 6/6 in ~8 s.

So **no single file's contents are the trigger**.  The wedge correlates with running multiple test files through the plugin's batch-execute pattern in one pytest invocation.

## What pytest-device does in the multi-file path that single-file doesn't

* Bulk-stages all test files for the library in one rsync (vs. just one file's worth of staging in single-file mode).  Difference is usually a few KB — small enough to be unlikely as the trigger on its own, but worth ruling out.
* Runs **multiple `transport.execute()` calls in the same persistent raw-REPL serial session**.  After test_acceptance.py's batch finishes, the same Python interpreter on the device is asked to load test_cp_adapter_on_device.py via `_exec_as_namespace`, then test_lazy_loading_on_device.py.  Module state, heap fragmentation, and radio state accumulate across batches; no soft-reset between them.

The production-deploy code path (`CircuitpythonTransport.deploy_files`) issues an explicit Ctrl-D soft-reboot after rsync; the functional-test path (`_stage_to_flash`) does NOT, by design — its docstring states "the harness expects the raw-REPL session to stay alive."

## What's been ruled out

These hypotheses were tested and **disproven** by direct experiment.  Don't restart investigation here:

* **Concurrent host processes / stale serial-port consumers.**  Once eliminated, single-file runs pass cleanly.  Multi-file still wedges.  So this isn't the dominant cause, despite the host-environment-contamination story being plausible.
* **WiFi radio starves USB-CDC.**  Direct test: bogus SSID forcing 30 s of continuous failed-association retries (max radio TX duty cycle) on Lolin S2 CP, single-file invocation, did **not** wedge the board.  Tests failed assertions cleanly with the port staying PRESENT throughout and after.
* **Brown-out from WiFi radio current spike.**  Same bogus-SSID test above demonstrates that even sustained radio activity over USB power doesn't wedge it.  No brown-out.
* **CIRCUITPY drive auto-reset on host write tipping the USB stack.**  The `Setup` phase (which is where the rsync to CIRCUITPY happens) passes consistently — including in runs that subsequently wedge.  So the rsync itself isn't the immediate trigger; the wedge is downstream, during `transport.execute()`.
* **Adding `print()` statements ("yielding to USB scheduler") fixes it.**  False correlation observed once; on retry without prints, the same file passed.  Print-vs-no-print is not deterministic for the wedge.  Don't pursue cooperative-scheduling-yield theories until a reliable reproducer exists.
* **Outdoor / weak signal.**  Tested.  Single-file `test_acceptance.py` passes outside in 24 s.

## Working hypothesis (informed but not proven)

The wedge is in **how `CircuitpythonTransport` handles a sequence of `execute()` calls against a single live raw-REPL session on Lolin S2 CP** specifically.  Pi Pico W CP runs the same multi-file flow without issue, and Lolin S2 MP runs the same multi-file flow without issue, so the bug is in the intersection of:

* CircuitPython runtime
* ESP32-S2 native USB
* Multi-batch raw-REPL session reuse without intermediate soft-reset

The fact that single-file runs work and the very first file in a multi-file run also (briefly) works points at *something accumulating across batches* — either:

* On-device interpreter state (`sys.modules`, heap fragmentation, lingering radio handles)
* Host-side transport state (raw-REPL framing, partial reads, autoreload-disabled flag effects)
* USB endpoint state on the ESP32-S2 controller as it cycles through CDC ↔ MSC ↔ radio activity over consecutive batches

## Investigation plan

### Step 1 — Lock down a reliable reproducer

The single most-important deliverable.  Without a 100% reliable reproducer, every "fix" theory is a coin flip (this session burned several theories that way).

* Confirm whether the wedge fires on **every** first-after-power-cycle multi-file run, or whether some earlier interaction sequence is required.
* Confirm whether running just **two** test files (`test_acceptance.py + test_cp_adapter_on_device.py`) is sufficient, or whether all three are needed.  If two is enough, drop the third from the reproducer.
* Capture the **device-side stdout up to the wedge** by patching `CircuitpythonTransport._read_until` to tee every byte read from `self._port` to a debug file.  That'll show what the device's last printed line was before the CDC died — a critical data point this session never got.

### Step 2 — Bisect commit history

The user reports CircuitPython S2 used to be reliable for this sweep.  60+ commits between "last known good" and "now broken."  Areas to inspect (in rough order of suspicion):

1. **`workbench/pytest-device/`** — the plugin's batch-execute orchestration.  Specifically:
   * `_ensure_batch_result` and how it handles `transport.execute()` results across consecutive items.
   * The `_TransportCache` lifecycle — when invalidations happen, when transports are reused, soft-reset cadence.
   * The `_should_soft_reset_before_stage` logic — does it cover flash mode? does it ever fire between consecutive flash-mode batches on the same device?
2. **`workbench/deploy/src/chumicro_deploy/circuitpython_transport.py`** — the raw-REPL session lifecycle.
   * `_stage_to_flash` vs `deploy_files`: the production path soft-reboots after rsync; the functional-test path doesn't.  Was that always the case, or did a refactor introduce the divergence?
   * `_disable_autoreload_before_drive_writes` — was this added or modified recently?  The autoreload-off state persists across `execute()` calls within a session and might compound poorly with multi-batch runs on ESP32-S2 CP.
   * `execute()` and `_read_until` — any change to how the raw REPL response is parsed or how `\x04>` markers are detected could leave the transport mid-frame between batches.
3. **`support/test_harness/src/chumicro_test_harness/`** — the on-device runner.
   * `run_module` and `_exec_as_namespace` — anything that changed how modules are loaded across consecutive bootstraps (e.g. caching `sys.modules` entries that previously got cleaned up).
4. **`libraries/wifi/`** — the wifi adapter and service.
   * Any change to `CpWifiAdapter` that altered radio init or teardown semantics.
   * The `__chumicro_runtimes__` marker file-filtering interactions.
5. **The on-device-config-dogfooding commit itself** ([`31db165`](https://github.com/ChuMicro/ChuMicro/commit/31db165), 2026-05-05) — it added `runtime_config.msgpack` staging to the deploy graph (`extra_files=...` in `transport.stage`).  That's one extra file in the rsync per batch.  Unlikely to be the trigger (Pi Pico W CP runs the same code path fine), but worth ruling out by reverting just that commit and seeing if Lolin S2 CP recovers.

`git log --oneline workbench/pytest-device workbench/deploy libraries/wifi support/test_harness | head -100` is a reasonable starting view.

### Step 3 — Once the regression commit is identified, design the fix

Possibilities once root cause is known:

* **Soft-reboot between consecutive batches in functional-test mode.**  Match what `deploy_files` already does after rsync.  Costs ~2 s per file; may be the right trade.
* **Drop the persistent raw-REPL session in functional-test mode.**  Open a fresh session per batch.  Higher per-batch cost but most isolated.
* **Targeted fix at the regression site** if it turns out to be a specific change with a clean revert.

### Step 4 — Re-validate the four-board canonical matrix

After the fix:

* `pi-pico-w-circuitpython-board` — full `--library wifi` sweep
* `pi-pico-w-micropython-board` — full sweep
* `lolin-s2-circuitpython-board` — full sweep (the regression target)
* `lolin-s2-micropython-board` — full sweep

Plus mqtt + sockets + websockets + http_server + ntp + requests, since the same multi-file pattern likely affects them too.

## Out of scope

* Any "fix" that only addresses the symptoms without finding the regression commit.  The user explicitly noted that this used to work; the question is *what change broke it*, not "how do we work around it."
* Changes to the on-device-config-dogfooding commit itself.  That commit's code paths are validated on three of four boards under multi-file sweep and on the fourth board under single-file mode.  The regression isn't in those paths.

## Constraints

* **Hardware-in-the-loop required.**  Lolin S2 Mini CircuitPython board on the four-board canonical matrix.  No host-side test reproduces this; only real ESP32-S2 CP exhibits it.
* **The fix must not regress the other three boards.**  Pi Pico W CP, Pi Pico W MP, and Lolin S2 MP all run the multi-file sweep cleanly today; whatever the fix is, it has to keep working for them.
* **No `--no-verify` / hook-skip commits.**  Standard chumicro commit hygiene applies.

## What this session learned (for the next agent)

1. **Don't speculate about hardware/firmware mechanisms before isolating a reliable reproducer.**  This session produced four wrong-but-plausible-sounding theories (rsync-while-holding-CDC, chip-resource-contention, radio-starves-CDC, brown-out) — each spawned a followup task before being disproven.  None survived contact with controlled experiments.
2. **The "Errno 6 Device not configured" → "Errno 2 No such file" sequence is consistent with a USB endpoint dying on the device while the host kernel takes ~7 s to reap the IOKit nub.**  Useful for distinguishing "device just rebooted" (port disappears immediately) from "device's USB stack hung" (port lingers).
3. **`Setup` passing while `Run overhead` fails means the rsync is not the immediate trigger** — the wedge is downstream, during the bootstrap-execute phase.
4. **Single-file runs of every wifi test file pass on Lolin S2 CP** — narrows the bug to multi-file sequencing.
5. **Two stale spawn_task chips** were created earlier in this session ("Fix CP-on-ESP32-S2 wedge in functional-test flash deploy" and "CP+ESP32-S2 USB-CDC dies on wifi.radio.connect"); both are based on diagnoses that didn't survive verification and should be **dismissed**, not pursued.  This workstream document supersedes them.
