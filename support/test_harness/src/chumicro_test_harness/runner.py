"""Minimal test runner for cross-runtime and on-board tests.

Discovers ``test_*`` callables on a module-like object, runs each one,
and reports per-test timing plus an optional memory summary.  Works on
CPython, MicroPython, and CircuitPython — including on real boards.
"""

import sys
import time

try:
	import traceback
except ImportError:  # pragma: no cover - MicroPython and CircuitPython may omit traceback.
	traceback = None

try:
	import gc as _gc
except ImportError:  # pragma: no cover - gc may be absent on some CPython configs.
	_gc = None

# Cross-runtime monotonic seconds: CPython/CircuitPython expose
# time.monotonic(); MicroPython only has time.ticks_ms().
if hasattr(time, "monotonic"):
	_now_seconds = time.monotonic
else:  # pragma: no cover — MicroPython fallback; time.monotonic always exists on CPython.
	def _now_seconds():
		"""Return monotonic seconds from MicroPython's ``ticks_ms``."""
		return time.ticks_ms() / 1000


def _has_mem_free():
	"""Return whether ``gc.mem_free`` is available (MicroPython/CircuitPython)."""
	return _gc is not None and hasattr(_gc, "mem_free")


_MEM_FREE_AVAILABLE = _has_mem_free()


def _iter_test_functions(module: object):
	"""Yield `(name, function)` pairs for callable module attributes named `test_*`.

	Args:
		module: Module-like object to scan for test functions.
	"""
	for name in dir(module):
		if not name.startswith("test_"):
			continue

		candidate = getattr(module, name)
		if callable(candidate):
			yield name, candidate


def _print_exception(exception):
	"""Print an exception using the best runtime-specific mechanism available.

	Three tiers, in priority order:

	1. ``sys.print_exception`` — MicroPython/CircuitPython native hook.
	2. ``traceback.print_exception`` — CPython standard library fallback.
	3. Bare class-name + message — always works, no traceback.

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

	Prints per-test duration and PASS/FAIL status.  When ``gc.mem_free``
	is available (MicroPython / CircuitPython boards), automatic GC is
	disabled for the run and ``gc.collect()`` is called explicitly between
	tests.  This gives per-test heap deltas that reflect only that test's
	retained allocations, plus a module-level summary.

	Args:
		module: Module-like object containing ``test_*`` callables.
		name_filter: Optional substring filter.  When set, only
			``test_*`` functions whose name contains this string
			are executed.  Enables single-test runs from the IDE.

	Returns:
		Shell-style exit code: 0 for all-pass, 1 for any failure.
	"""
	total = 0
	failed = 0

	run_start = _now_seconds()

	# Disable automatic GC so collections happen only at explicit points
	# between tests.  Manual gc.collect() still works.  This makes per-test
	# heap deltas deterministic: each delta reflects only that test's
	# retained allocations, not debris from a prior test that happened to
	# become collectible mid-run.
	gc_tracking = _MEM_FREE_AVAILABLE
	if gc_tracking:
		_gc.collect()
		_gc.disable()
		module_heap_before = _gc.mem_free()

	for name, function in _iter_test_functions(module):
		if name_filter is not None and name_filter not in name:
			continue
		total += 1

		# Allocate the timing float *before* the heap baseline so it
		# does not count towards the test's delta.
		test_start = _now_seconds()
		if gc_tracking:
			_gc.collect()
			test_heap_before = _gc.mem_free()

		try:
			function()
		except Exception as error:  # pragma: no cover - exercised indirectly by tests.
			# Take the heap snapshot *before* computing duration so the
			# duration float does not inflate the delta.
			heap_suffix = ""
			if gc_tracking:
				_gc.collect()
				test_delta = _gc.mem_free() - test_heap_before
				sign = "+" if test_delta >= 0 else ""
				heap_suffix = f", heap {sign}{test_delta}"
			duration = _now_seconds() - test_start
			failed += 1
			print(f"FAIL {name} ({duration:.3f}s{heap_suffix})")
			_print_exception(error)
		else:
			heap_suffix = ""
			if gc_tracking:
				_gc.collect()
				test_delta = _gc.mem_free() - test_heap_before
				sign = "+" if test_delta >= 0 else ""
				heap_suffix = f", heap {sign}{test_delta}"
			duration = _now_seconds() - test_start
			print(f"PASS {name} ({duration:.3f}s{heap_suffix})")

	if gc_tracking:
		_gc.collect()
		module_heap_after = _gc.mem_free()
		_gc.enable()
		delta = module_heap_after - module_heap_before
		sign = "+" if delta >= 0 else ""
		print(f"HEAP {module_heap_after} bytes free (delta {sign}{delta} bytes)")

	total_duration = _now_seconds() - run_start

	if total == 0:
		print("NO TESTS FOUND")


	print(f"SUMMARY total={total} failed={failed} time={total_duration:.3f}s")
	return 1 if failed else 0
