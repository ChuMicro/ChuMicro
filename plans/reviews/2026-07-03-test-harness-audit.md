# Hunt — support/test_harness (correctness audit)

Scope: the on-device / cross-runtime test runner in
`support/test_harness/src/chumicro_test_harness/` and the result lines the host
(`workbench/pytest-device`, `chumicro_workspace.device_orchestration`) parses.

Environment used: `.venv/bin/python`, MP unix-port
`.tools/micropython-v1.26.0/ports/unix/build-standard/micropython`, CP unix-port
`.tools/circuitpython-10.2.0/ports/unix/build-standard/micropython`. Probes in
`.scratch/hunt-harness/`. Excluded per brief: L77, H37, plans/next-up.

Baseline: `pytest support/test_harness/tests -q` = 63 passed.

Confirmed-good (checked, not findings): the `_exec_chunked` decorator handling
and `__future__` guard are correct (`chunk_boundaries_for` returns `None` on a
`from __future__` import; decorator boundary = `min(node.lineno, deco.lineno)`);
chunked vs whole-file exec produce identical PASS/FAIL/SUMMARY on MP+CP
(probe_chunky). Source minification is deliberately line-number-preserving
(`source_minify.strip_source` blanks lines in place), so host-computed chunk
boundaries stay aligned with the minified on-device file. The host reconcile
(`_assert_summary_reconciles` / `_assert_collected_reconciles`) is strong: it
catches missing SUMMARY, dropped FAIL, phantom lines, ambiguous duplicates, and
orphan (uncollected) test names. Most harness escape paths therefore surface as
a loud batch failure, not a false pass.

---

### T1 · high · runner.py:171 (also :59) — Generator/coroutine-bodied test is reported PASS without running its body; survives the host reconcile green

What happens: `run_module` discovers any `test_*` attribute that is `callable`
(runner.py:59) and executes it with a bare `function()` (runner.py:171). If the
test function contains a `yield` it is a *generator function*: `function()`
returns a generator object and the body — including its assertions — never runs.
No exception is raised, so the runner takes the `else` branch and prints `PASS`.
Same for a `test_*` method on a `Test*` class (bound generator method).

Why the host can't catch it: the AST collector
`chumicro_pytest_device.collection._parse_test_functions` collects a generator
test as a normal `ast.FunctionDef` (a `yield` in the body does not change the AST
node kind), so the name IS collected — it is not an orphan. The run emits exactly
one PASS line, `failed=0`, `total == len(collected)`, one match per name. Every
guard in `_assert_summary_reconciles` and `_assert_collected_reconciles` passes.
The batch is green.

Confirmed trigger/probe:
- `.scratch/hunt-harness/genonly/test_gen.py` (`test_broken_generator` with
  `assert 2+2==5; yield`). Driven end-to-end through
  `_parse_test_functions` + `parse_output` + both reconcile asserts:
  `[micropython] broken_generator -> PASS ; RECONCILE PASSED (batch is GREEN)`,
  same for circuitpython.
- Generalizes to class methods: `.scratch/hunt-harness/probe_genmethod.py` →
  `PASS TestThing.test_should_fail_but_is_generator`, `SUMMARY total=1 failed=0`,
  exit 0.
- Plain CPython `pytest` DOES catch it (collection error: "'yield' keyword is
  allowed in fixtures, but not in tests"). So the mechanism is a *false green*
  only on the cross-runtime lanes.

Blast radius: for a `libraries/*/tests/test_*.py` file that also runs under the
plain CPython pytest lane, the mistake is caught there during a full preflight.
The genuine exposure is **device-only files** (functional_tests, or unit files
that top-level-import a device-only module and so never run under CPython
pytest): there, a generator-bodied test is an undetected false pass. No active
occurrences today — corpus scan found `yield` only inside `*_pytest.py`
(excluded from cross-runtime) and generator *helpers*, not in cross-runtime
`test_*` bodies. This is a latent truthfulness hole, not an active
mis-report.

Suggested fix: after `function()` returns, reject a non-None return that is a
generator/coroutine. E.g. detect `type(result).__name__ in ("generator",
"coroutine")` (works on MP/CP where `inspect`/`types` are thin) or check for a
`send`/`__next__` attribute, and print FAIL ("test function is a generator/async
coroutine; its body never ran") instead of PASS. Cheap, no per-test allocation
on the common path (result is `None`).

---

### T2 · high · runner.py:152 / :85 — Exceptions during discovery/instantiation escape run_module and truncate the whole suite (no FAIL, no SUMMARY, passed tests discarded)

What happens: the `try/except` in `run_module` wraps only `function()`
(runner.py:170-190). Discovery runs *outside* it: the `for name, function in
_iter_test_functions(module)` loop (runner.py:152) lazily drives the generator,
which calls `getattr(module, name)` (runner.py:57), `dir()`, and — for each
`Test*` method — `instance = test_class()` (runner.py:85). Any exception from
those propagates straight out of `run_module`. The run stops mid-suite: no FAIL
line for the offending test, no SUMMARY, and every test after it in `dir()` order
never runs. Tests that already printed PASS are discarded because the batch is
now a failure.

Two realistic triggers on a 264 KB board:
1. A `Test*` class whose `__init__` allocates (a fixture buffer, opens a
   peripheral) and raises `MemoryError` / hardware error during discovery.
2. A `Test*` class whose `__init__` requires arguments — `test_class()` is called
   with none, raising `TypeError` at discovery.

Confirmed trigger/probe: `.scratch/hunt-harness/probe_ctor_raise.py`
(`class TestBoom: __init__ raises RuntimeError`). MP and CP both print
`PASS test_aaa_first`, then a traceback through `_iter_test_methods_on_class`
line 85, then STOP — no `FAIL`, no `SUMMARY`, `test_zzz_last` never runs, exit 1.

Blast radius: the host's `_assert_summary_reconciles` sees the missing SUMMARY
and fails the batch, so this is reported as a failure (not a false pass). But: (a)
zero per-test attribution — the developer sees a truncated transcript, not
"TestBoom.test_method FAILED"; (b) every sibling test in the file is dropped from
the report, including ones that passed; (c) on-device the trigger (a heavy
`Test*.__init__` that OOMs) is plausible. No active required-arg `Test*` ctors
in the corpus today (the `__init__`s found are on `_`-prefixed helper classes and
nested classes, not on `Test*` classes).

Suggested fix: guard discovery/instantiation. Either wrap `_iter_test_functions`
consumption so an exception raised while producing/instantiating a test is
reported as a FAIL line for that test's qualified name (then continue), or at
minimum instantiate the class inside the per-test `try` so a ctor failure becomes
`FAIL Class.test_method (...)` rather than a suite-ending escape.

---

### T3 · medium · runner.py:59 / :171 — Async test functions are "passed" as un-awaited coroutines, and (being uncollectable by the host AST) poison the whole file's batch

What happens: an `async def test_*` is `callable`, so runner.py:59 accepts it and
runner.py:171 calls it; that returns an un-awaited coroutine and prints PASS (body
never runs). Meanwhile the host collector `_parse_test_functions` only matches
`ast.FunctionDef`, never `ast.AsyncFunctionDef`, so the async test is *not*
collected. On the device/unix-port lane this makes it an ORPHAN:
`_assert_collected_reconciles` fails the entire file batch ("Device ran test(s)
the host never collected …"), and `summary.total != len(collected)`.

Confirmed trigger/probe: `.scratch/hunt-harness/genfile/test_gen.py` (has
`async def test_async_broken`). Host reconcile output: `orphans:
['test_async_broken']`, `summary.total == len(collected)? False`. Plain CPython
pytest FAILS the async test outright (no pytest-asyncio).

Blast radius: two-fold. (1) The harness silently treats an async coroutine as a
pass — misleading if ever read directly. (2) Because the async test is
uncollectable, its mere presence in a file makes the *whole* file's cross-runtime
batch fail reconcile, taking every sibling test's result down with it (they can
never go green while the async test sits in the file). It fails loud (not a false
pass), but the failure is mis-attributed to "orphan / count mismatch" rather than
"async tests are unsupported here." Low frequency (0 async tests in the corpus).

Suggested fix: either explicitly reject async test functions in discovery with a
clear FAIL ("async test functions are not supported by the cross-runtime
harness"), or teach both sides to agree (collector recognizes
`AsyncFunctionDef` and the runner drives the coroutine to completion). At minimum
make the runner not report an un-awaited coroutine as PASS (shares the T1 fix).

---

### T4 · low · runner.py:56 (`_iter_test_functions`) — On-device discovery order is dir()-order (unsorted), diverging from the host collector's sorted order and the "mirrors pytest / deterministic" docstrings

What happens: `_iter_test_functions` iterates `dir(module)` and `dir(test_class)`.
On MicroPython and CircuitPython `dir()` is NOT sorted — it returns
definition/hash order, unlike CPython where `dir()` is sorted. The host collector
`_parse_test_functions` returns `sorted(names)`, and discovery.py's own
`_sorted_listdir` docstring plus collection.py claim the runner "mirrors pytest's
default collection rules" and deterministic ordering.

Confirmed probe: on both MP and CP,
`dir(class)` → `['test_b','test_a','test_c']` (definition order),
`dir(namespace)` → `['test_zebra','test_apple','test_mango']` (insertion order),
i.e. not alphabetized.

Blast radius: no truthfulness break — the host reconcile is set-based and per-test
mapping is name-based, so order is irrelevant to pass/fail attribution. Both real
execution paths (device dir()-order and plain CPython pytest) run in definition
order, so they mostly agree; only the host's *display* order (sorted) differs.
The residual risk is an order-dependent test that mutates shared exec-namespace
globals, plus the fact that MP `_Namespace.__dict__` iteration order for
module-level tests is dict-hash-dependent and not guaranteed stable across
builds. This is drift/doc-accuracy, not a correctness bug.

Suggested fix: sort inside `_iter_test_functions` (`for name in sorted(dir(...))`)
so device order matches the host's sorted collection and the docstring claim, or
soften the docstrings to state execution is dir()-order.

---

### T5 · low · assertions.py:61 — `raises(Exception)` (or a broad base) silently suppresses a `skip()` on device, diverging from the pytest host

What happens: on MP/CP (no pytest), `skip()` raises `_SkipException(Exception)`.
`raises.__exit__` suppresses any exception that `issubclass(exc_type,
self.expected)`. So a test body `with raises(Exception): ... skip(...)` treats the
skip as the expected exception and the test PASSES instead of SKIPPING. On the
CPython/pytest host, `_SkipException = pytest.skip.Exception` is BaseException-
derived and NOT a subclass of `Exception`, so `raises(Exception)` does not
suppress it and the skip propagates — opposite behavior.

Blast radius: requires the pathological pattern of an over-broad
`raises(Exception)`/`raises(BaseException-ish)` wrapping code that calls `skip()`.
Very unlikely in practice; noted for completeness as a cross-runtime divergence.

Suggested fix: have `raises.__exit__` special-case `_SkipException` (re-raise it
rather than suppress) so skip semantics are identical on host and device.

---

Minor notes (no separate finding): a `skip()` reason containing a newline, or an
exception message line beginning with `PASS/FAIL/SKIP/SUMMARY`, could inject a
line the parser misreads — but the host's phantom-line guard (`len(tests) >
total`), duplicate-name guard, and last-SUMMARY-wins parsing all make this a loud
failure, never a false pass. Left as defense-in-depth working as intended.
