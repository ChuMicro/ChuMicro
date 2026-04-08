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


def _memory_free():
	"""Return free heap bytes, or ``None`` if unavailable."""
	if _gc is not None and hasattr(_gc, "mem_free"):
		# Collect first so the reading reflects actually-available memory
		# rather than including reclaimable garbage.  This makes before/after
		# comparisons meaningful for detecting real leaks.
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
	"""Print an exception using the best runtime-specific mechanism available.

	Three tiers, in priority order:

	1. ``sys.print_exception`` — MicroPython/CircuitPython native hook.
	2. ``traceback.print_exception`` — CPython standard library fallback.
	3. Bare class-name + message — always works, no traceback.
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


def run_module(module):
	"""Run all ``test_*`` callables on a module-like object.

	Prints per-test duration and PASS/FAIL status.  When ``gc.mem_free``
	is available (MicroPython / CircuitPython boards), reports free heap
	before and after the run to help detect memory leaks.

	Returns a shell-style exit code: 0 for all-pass, 1 for any failure.

	**Output format contract** — each line uses a fixed prefix so the
	cross-runtime entry point (``run_cross_runtime.py``) and CI can
	parse results reliably::

		PASS <name> (<duration>s)
		FAIL <name> (<duration>s)
		HEAP <bytes> bytes free
		HEAP <bytes> bytes free (delta <+/-bytes> bytes)
		SUMMARY total=<n> failed=<n> time=<seconds>s
		NO TESTS FOUND
	"""
	total = 0
	failed = 0

	memory_before = _memory_free()
	if memory_before is not None:
		print(f"HEAP {memory_before} bytes free")

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

	memory_after = _memory_free()
	if memory_after is not None:
		delta = memory_after - memory_before
		sign = "+" if delta >= 0 else ""
		print(f"HEAP {memory_after} bytes free (delta {sign}{delta} bytes)")

	print(f"SUMMARY total={total} failed={failed} time={total_duration:.3f}s")
	return 1 if failed else 0
