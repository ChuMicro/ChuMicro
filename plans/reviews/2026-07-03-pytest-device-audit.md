# Hunt: `workbench/pytest-device` correctness audit

Auditor: hunter role. Scope: backends, result parsing, collection/plugin, session/transport
plumbing, pr_summary. Excluded per brief: H37, M81, M82/M83/L88.

Baseline: `workbench/pytest-device/tests` — 303 passed (5.36s). Probes in
`.scratch/hunt-pytest-device/`.

The plugin's false-green defense is `_assert_summary_reconciles`
(`collection.py:65`): it requires a `SUMMARY` line (else "truncated") and requires
`summary.failed == parsed_failed` (else "dropped FAIL"). This correctly catches board
crashes, serial drops, and dropped FAIL lines. The findings below are the paths it does
**not** cover.

---

### P1 · critical · collection.py:95 (`_parse_test_functions`) vs runner.py:56 (`_iter_test_functions`) — device runs tests the host never collected; their FAILs are masked

**What happens.** Which pytest items exist is decided host-side by AST
(`_parse_test_functions`, `collection.py:95-129`): it walks *direct child nodes* only —
module-level `def test_*`, and `test_*` `FunctionDef` children of a `class Test*`. The
device/unix-port runner discovers tests at runtime via `dir()`
(`_iter_test_functions`, `runner.py:56-65`): any attribute whose name starts with
`test_` and is callable, and any `Test*` class's `test_*` via `dir(class)` — which
includes **inherited** methods and **dynamically created / imported** callables. When the
runner executes a `test_*` the AST never collected, there is no `DeviceTestItem` to map
its result onto. If that test **FAILs on the board, nobody reports it**:
`_assert_summary_reconciles` only checks `summary.failed == parsed_failed`, and both
counts include the orphan FAIL symmetrically, so the reconcile passes. The session exits
green.

Divergence sources, each a device `test_*` with no host item:
- a `test_*` method inherited by a `class Test*` from a base class (the base need not be
  named `Test*`; `dir(subclass)` surfaces it, AST's per-class child walk does not);
- a module-level `test_name = _factory()` / `from helpers import test_x` binding (an
  `Assign`/`ImportFrom` node, not a `FunctionDef`, so AST skips it; `dir(module)` sees the
  callable);
- a `test_*` defined inside an `if`/`try` block in the class or module body.

**Confirmed trigger.** `.scratch/hunt-pytest-device/probe_divergence.py`: a file with
`class TestFoo(BaseChecks)` (BaseChecks.test_inherited_fails raises) and a module-level
`test_from_factory = _make_test()`. AST collects only `TestFoo.test_own_passes`. The real
`run_module` executes and FAILs `TestFoo.test_inherited_fails` and `test_from_factory`,
emitting `SUMMARY total=3 failed=2`. `_assert_summary_reconciles` PASSES (parsed_failed=2
== summary.failed=2). The only pytest item passes → **2 device failures reported as a
green run.**

**Blast radius.** Currently latent: a grep of `libraries/*/tests` and
`libraries/*/functional_tests` finds no `Test*` inheritance, non-`Test*` base classes with
`test_*` methods, or module-level `test_* =` factory bindings today. But this is the exact
false-green class the reconcile exists to prevent, and its docstring
(`collection.py:70-79`) explicitly declines to reconcile `total` — reasoning only about the
*fewer-lines* direction (caught per-test as "not found"), never the *more-tests-than-
collected* direction. Any future cross-runtime test that shares assertions via a base class
(a normal pytest pattern) or builds tests via a factory (a normal substitute for
`@parametrize`, which the harness cannot use) silently masks its failures.

**Suggested fix.** Cross-check the device-run test names against the collected item names.
In `_require_batch_result` (or the `DeviceRunFileItem`), gather the `function_name`s of the
`DeviceTestItem`s for this `(device, file)` batch and `pytest.fail` the batch if
`result.tests` contains any name not in that set (a test the device ran but nobody
collected) — surfacing the orphan instead of dropping it. This is the mirror of the
existing per-test "not found in device output" guard.

---

### P2 · medium · result_parser.py:84 (`parse_output`) + collection.py:645 (`DeviceTestItem.runtest`) — a device output line that looks like a result injects a phantom TestResult and can mask a later FAIL

**What happens.** `parse_output` scans *every* line of captured device output and appends a
`TestResult` for any that matches `_PASS_FAIL_PATTERN` / `_SKIP_PATTERN` — including
free-form board prose, print-debugging, or an exception message printed by
`_print_exception` (`runner.py:89`). `DeviceTestItem.runtest` then takes the **first**
`result.tests` entry whose name matches (`collection.py:645-654`). A phantom `PASS test_b
(0.00s)` emitted before `test_b`'s real `FAIL` line makes the item report PASS. The
reconcile still passes: the phantom is an *extra* PASS, so `parsed_failed` still equals
`summary.failed`.

**Confirmed trigger.** `.scratch/hunt-pytest-device/probe_injection.py`: output where
`test_a`'s exception text contains a second physical line `PASS test_b (0.002s)`, followed
by `test_b`'s real `FAIL`. `result.tests` = [test_a FAIL, test_b PASS(phantom), test_b
FAIL]; the `test_b` item reads the phantom PASS first → reports PASS while the real result
was FAIL. `parsed_failed=2 == summary.failed=2`, reconcile OK.

**Blast radius.** Requires a failing test to emit a line matching `^(PASS|FAIL)\s+\S+\s+
\(\d+\.\d+s...\)` for another, later-failing test — contrived (the harness's own
result-string self-tests live in `support/test_harness/tests` and are host-only pytest,
never routed through this backend, so they don't trigger it). Real but low-probability;
the fragility (trusting arbitrary matching lines; first-match lookup) is the substance.

**Suggested fix.** Two cheap guards, either of which closes the probe case: (a) assert
`summary.total == len(result.tests)` in `_assert_summary_reconciles` — an injected phantom
makes `len(result.tests) > summary.total` (probe: 3 vs 2), so this flags it; and it also
tightens the dropped-non-FAIL-line case. (b) In `DeviceTestItem.runtest`, treat a duplicate
name in `result.tests` as ambiguous and fail rather than first-match-wins. (a) alone is the
higher-value change since it also backstops other line-count divergences.

---

### P3 · medium · backends.py:258 (`UnixPortBackend.execute`) — unix-port subprocess spawned with no timeout; a hanging test stalls the lane indefinitely

**What happens.** `subprocess.run(command, cwd=..., capture_output=True, text=True,
check=False)` passes no `timeout=`. A test that infinite-loops or blocks (e.g. a real
`socket.recv()` / `select` regression that a fake would otherwise paper over) in the
unix-port worker hangs the call forever. No `pytest-timeout` plugin is installed
(`.venv/bin/python -c find_spec('pytest_timeout')` → False) and `addopts` in the root
`pyproject.toml` sets none, so there is no backstop. The device backend gets its timeout
from the transport (a hang there raises → recover → `BackendExecuteError` → `pytest.fail`);
the unix-port lane — which the audit brief and `test-all-runtimes` exercise — has no
equivalent.

**Confirmed trigger.** Code read: `backends.py:258-264` has no `timeout` argument; no
project-level pytest timeout is configured (verified). Not a false-green (a hang eventually
trips the CI job-level timeout and surfaces as failure), but it converts one wedged test
into a whole-lane stall with no per-test attribution.

**Suggested fix.** Pass a bounded `timeout=` to `subprocess.run` and raise
`BackendExecuteError` (naming the test file + runtime) on `subprocess.TimeoutExpired`, so a
single hanging file fails cleanly and the sweep continues.

---

### P4 · low · collection.py:1017 (`_deselect_items_missing_required_features`) — a transient feature-probe failure silently drops feature-gated tests from the run

**What happens.** When probing a device for `__chumicro_features__` fails for *any* reason
(offline board, transport glitch), the `except Exception` sets `cache[device_id] =
frozenset()` (`collection.py:1017-1025`) and every feature-marked item for that device is
**deselected** (`collection.py:1029-1033`) — removed, not skipped. A `warnings.warn` fires,
but in a non-interactive CI run warnings don't fail the build and don't show in the
pass/skip tally. So a flaky probe conflates "device unreachable" with "feature absent": the
gated tests vanish and the session still reports success with a quietly smaller test count.

**Blast radius.** Functional/feature-gated tests only (hardware lane), and a genuine
feature mismatch *should* deselect — but a probe *error* is a different condition and
deserves a visible skip (or a hard failure), not a silent drop. Low because it's
hardware-gated and warning-backed.

**Suggested fix.** On probe *failure* (as opposed to a successful probe that lacks the
feature), apply a `pytest.mark.skip("feature probe failed for <device>")` so the drop is
visible in the summary, or fail the affected items; reserve silent deselection for a
successful probe that genuinely lacks the feature.

---

### P5 · low · runtime_config.py:75 + collection.py:888 — session-global required-keys stash lets one library's conftest skip or under-validate another's device tests

**What happens.** `set_runtime_config` stores `required_keys` on a single session-wide
`config.stash` slot (`runtime_config.py:75`); `get_required_keys` returns the **latest**
write. `pytest_collection_modifyitems` (`collection.py:888-899`) then applies the resulting
skip to **every** `DeviceRuntimeItem` in the session. With two libraries' `functional_tests`
in one session, the conftest that runs `pytest_configure` last wins: either library B's
tests get skipped because library A declared a key A needs and B doesn't, or A's validation
is lost because B overwrote the stash with `required_keys=()`. The former over-skips
(loud), the latter drops A's guard so A's on-device test hits its own silent-skip/crash
path.

**Blast radius.** Low — functional sweeps usually run one library at a time
(`_bulk_stage_for_device` is per-library), and the failure mode is either a visible skip or
a fall-through to the pre-existing on-device miss handling, not a masked FAIL.

**Suggested fix.** Key the required-keys (and payload) stash per test file / per library
rather than one session-global slot, and scope the collection-time skip to that library's
items.

---

## Not findings (checked, defense holds)

- ImportError / non-import load error on a test file: `run_one_file` (`discovery.py:210`)
  and the device `build_bootstrap` path both produce output with **no** `SUMMARY` line, so
  `_require_batch_result` fails with "No test results" / reconcile "truncated". Red, correct.
- Board crash / OOM / segfault mid-run, serial truncation, `SystemExit` from a test:
  no `SUMMARY` → reconcile catches it. Red, correct.
- Dropped FAIL line: `summary.failed != parsed_failed` → reconcile catches it. Red, correct.
- `_SkipException` ordering / bare `return`-as-pass: harness semantics are sound
  (`skip.py`, `runner.py:172`).
- PR-summary pass/fail derives from the pytest `report`, not from the harness output
  independently, so it mirrors item results — it can't be an *independent* false-green
  source (it inherits P1/P2's masking but adds none).
- Non-zero unix-port exit with a valid all-PASS `SUMMARY` (e.g. an atexit/shutdown segfault
  after tests passed) is reported green — exit code is intentionally ignored once output is
  non-empty (`backends.py:271`). Judged acceptable: the tests did pass; noting only for
  completeness.
