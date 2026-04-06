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
else:
	def _now_seconds():
		"""Return monotonic seconds from MicroPython's ``ticks_ms``."""
		return time.ticks_ms() / 1000


def _mem_free():
	"""Return free heap bytes, or ``None`` if unavailable."""
	if _gc is not None and hasattr(_gc, "mem_free"):
		_gc.collect()
		return _gc.mem_free()
	return None


def _iter_test_functions(module: object):
	"""Yield `(name, function)` pairs for callable module attributes named `test_*`."""
	for name in dir(module):
		if not name.startswith("test_"):
			continue

		candidate = getattr(module, name)
		if callable(candidate):
			yield name, candidate


def _print_exception(exception):
	"""Print an exception using the best runtime-specific mechanism available."""
	print(f"{exception.__class__.__name__}: {exception}")

	if hasattr(sys, "print_exception"):
		sys.print_exception(exception)
		return

	if traceback is not None:
		traceback.print_exception(exception.__class__, exception, exception.__traceback__)


def run_module(module):
	"""Run all ``test_*`` callables on a module-like object.

	Prints per-test duration and PASS/FAIL status.  When ``gc.mem_free``
	is available (MicroPython / CircuitPython boards), reports free heap
	before and after the run to help detect memory leaks.

	Returns a shell-style exit code: 0 for all-pass, 1 for any failure.
	"""
	total = 0
	failed = 0

	mem_before = _mem_free()
	if mem_before is not None:
		print(f"HEAP {mem_before} bytes free")

	run_start = _now_seconds()

	for name, function in _iter_test_functions(module):
		total += 1
		test_start = _now_seconds()
		try:
			function()
		except Exception as exception:  # pragma: no cover - exercised indirectly by tests.
			duration = _now_seconds() - test_start
			failed += 1
			print(f"FAIL {name} ({duration:.3f}s)")
			_print_exception(exception)
		else:
			duration = _now_seconds() - test_start
			print(f"PASS {name} ({duration:.3f}s)")

	total_duration = _now_seconds() - run_start

	if total == 0:
		print("NO TESTS FOUND")

	mem_after = _mem_free()
	if mem_after is not None:
		print(f"HEAP {mem_after} bytes free (delta {mem_after - mem_before})")

	print(f"SUMMARY total={total} failed={failed} time={total_duration:.3f}s")
	return 1 if failed else 0
