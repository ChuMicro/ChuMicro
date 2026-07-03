"""Minimal test runner for cross-runtime and on-board tests.

Discovers ``test_*`` callables on a module-like object, runs each one,
and reports per-test timing plus an optional memory summary.  Works on
CPython, MicroPython, and CircuitPython, including on real boards.
"""

import gc
import sys
import time

from chumicro_test_harness.skip import _SkipException

try:
	import traceback
except ImportError:  # pragma: no cover - MicroPython and CircuitPython may omit traceback.
	traceback = None

# Cross-runtime monotonic clock. ``_now`` returns an opaque tick sample;
# ``_elapsed_seconds`` turns two samples into a float of elapsed seconds.
# CPython/CircuitPython expose time.monotonic() (float seconds, plain
# subtraction). MicroPython has only time.ticks_ms(), whose counter wraps
# at ~2**30 ms (~12.4 days uptime); raw subtraction across that wrap goes
# negative, so durations must be diffed with time.ticks_diff.
if hasattr(time, "monotonic"):
	_now = time.monotonic

	def _elapsed_seconds(start, end):
		"""Return seconds between two ``time.monotonic`` samples."""
		return end - start
else:  # pragma: no cover - MicroPython path, exercised on real boards.
	_now = time.ticks_ms

	def _elapsed_seconds(start, end):
		"""Return seconds between two ``time.ticks_ms`` samples, wrap-safe."""
		return time.ticks_diff(end, start) / 1000


_MEM_FREE_AVAILABLE = hasattr(gc, "mem_free")


def _iter_test_functions(module: object):
	"""Yield `(qualified_name, callable)` pairs for tests in *module*.

	Discovers two shapes, matching pytest's default collection rules:

	1. Module-level functions whose name starts with ``test_``.
	2. Methods named ``test_*`` on classes whose name starts with
	``Test``.  The class is instantiated with no arguments, then
	each method is bound to the instance.  Each test gets its own
	instance, so per-test mutation can't leak between tests.

	Args:
		module: Module-like object to scan for test functions.
	"""
	for name in dir(module):
		candidate = getattr(module, name)

		if name.startswith("test_") and callable(candidate):
			yield name, candidate
			continue

		if name.startswith("Test") and isinstance(candidate, type):
			yield from _iter_test_methods_on_class(name, candidate)


def _iter_test_methods_on_class(class_name, test_class):
	"""Yield `(qualified_name, bound_method)` pairs for ``test_*`` methods.

	Each method is collected against a fresh instance of *test_class*,
	mirroring pytest's per-test instance behavior and ensuring that
	state mutated in one test doesn't carry into the next.

	Args:
		class_name: The class's name as it appeared on the module.
		test_class: The class object itself.
	"""
	for attr in dir(test_class):
		if not attr.startswith("test_"):
			continue
		method = getattr(test_class, attr, None)
		if not callable(method):
			continue
		# Fresh instance per test. Match pytest semantics.
		instance = test_class()
		yield f"{class_name}.{attr}", getattr(instance, attr)


def _print_exception(exception):
	"""Print an exception using the best runtime-specific mechanism available.

	Three tiers, in priority order:

	1. ``sys.print_exception``: MicroPython/CircuitPython native hook.
	2. ``traceback.print_exception``: CPython standard library fallback.
	3. Bare class-name + message: always works, no traceback.

	Args:
		exception: Exception instance to print.
	"""
	print(f"{exception.__class__.__name__}: {exception}")

	# Tier 1: MicroPython / CircuitPython native hook.
	if hasattr(sys, "print_exception"):
		sys.print_exception(exception)
		return

	# Tier 2: CPython's traceback module (may have been set to None at
	# import time if the module was unavailable).
	if traceback is not None:
		traceback.print_exception(exception.__class__, exception, exception.__traceback__)

	# Tier 3: the bare print() at the top of this function already ran,
	# so the caller at least sees the exception class and message.


def run_module(module, name_filter=None):
	"""Run all ``test_*`` callables on a module-like object.

	Prints per-test duration and PASS/FAIL/SKIP status. When ``gc.mem_free``
	is available (MicroPython / CircuitPython boards), per-test heap
	deltas and a module-level HEAP summary are also emitted.

	Auto-GC stays enabled during tests so each test workload sees the
	same heap-management behavior as production code. The per-test heap
	delta brackets ``function()`` itself with explicit collects on either
	side. Those collects stay outside the timed region so a slow
	PSRAM-backed collect cannot inflate a fast test's duration.

	Args:
		module: Module-like object containing ``test_*`` callables.
		name_filter: Optional substring filter. When set, only ``test_*``
			functions whose name contains this string are executed.
			Enables single-test runs from the IDE.

	Returns:
		Shell-style exit code: 0 for all-pass, 1 for any failure.
	"""
	total = 0
	failed = 0

	run_start = _now()

	# Auto-GC stays enabled (default).  Each test is bracketed by an
	# explicit ``gc.collect()`` for the per-test delta measurement, but
	# the test body itself runs under production-realistic auto-GC.
	gc_tracking = _MEM_FREE_AVAILABLE
	if gc_tracking:
		gc.collect()
		module_heap_before = gc.mem_free()

	for name, function in _iter_test_functions(module):
		if name_filter is not None and name_filter not in name:
			continue
		total += 1

		# GC calls stay *outside* the timed region.  On boards with large
		# heaps (ESP32-S2 with PSRAM in particular) a full ``gc.collect``
		# can take hundreds of ms, which would swamp the runtime of a
		# sub-100 ms test.  The heap baseline is captured before the
		# timer starts. The post-test collect happens after the timer
		# stops.  ``test_delta`` is still an accurate "bytes retained
		# by this test" measurement because both ``mem_free`` samples
		# straddle only ``function()`` itself.
		if gc_tracking:
			gc.collect()
			test_heap_before = gc.mem_free()

		test_start = _now()
		try:
			function()
		except _SkipException as skip_error:
			# Drain heap tracking so the next test's baseline is fresh,
			# but don't print a heap suffix: a skipped test didn't run
			# any allocations worth reporting.
			if gc_tracking:
				gc.collect()
			print(f"SKIP {name} ({skip_error})")
		except Exception as error:  # pragma: no cover - exercised indirectly by tests.
			test_end = _now()
			heap_suffix = ""
			if gc_tracking:
				gc.collect()
				test_delta = gc.mem_free() - test_heap_before
				sign = "+" if test_delta >= 0 else ""
				heap_suffix = f", heap {sign}{test_delta}"
			duration = _elapsed_seconds(test_start, test_end)
			failed += 1
			print(f"FAIL {name} ({duration:.3f}s{heap_suffix})")
			_print_exception(error)
		else:
			test_end = _now()
			heap_suffix = ""
			if gc_tracking:
				gc.collect()
				test_delta = gc.mem_free() - test_heap_before
				sign = "+" if test_delta >= 0 else ""
				heap_suffix = f", heap {sign}{test_delta}"
			duration = _elapsed_seconds(test_start, test_end)
			print(f"PASS {name} ({duration:.3f}s{heap_suffix})")

	if gc_tracking:
		gc.collect()
		module_heap_after = gc.mem_free()
		delta = module_heap_after - module_heap_before
		sign = "+" if delta >= 0 else ""
		print(f"HEAP {module_heap_after} bytes free (delta {sign}{delta} bytes)")

	total_duration = _elapsed_seconds(run_start, _now())

	if total == 0:
		print("NO TESTS FOUND")


	print(f"SUMMARY total={total} failed={failed} time={total_duration:.3f}s")
	return 1 if failed else 0
