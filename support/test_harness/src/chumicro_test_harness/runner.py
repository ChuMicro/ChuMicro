"""Minimal test discovery and execution helpers for cross-runtime tests."""

import sys

try:
	import traceback
except ImportError:  # pragma: no cover - MicroPython and CircuitPython may omit traceback.
	traceback = None


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
	"""Run all `test_*` callables on a module-like object and return a shell-style exit code."""
	total = 0
	failed = 0

	for name, function in _iter_test_functions(module):
		total += 1
		print(f"RUN {name}")
		try:
			function()
		except Exception as exception:  # pragma: no cover - exercised indirectly by tests.
			failed += 1
			print(f"FAIL {name}")
			_print_exception(exception)
		else:
			print(f"PASS {name}")

	if total == 0:
		print("NO TESTS FOUND")

	print(f"SUMMARY total={total} failed={failed}")
	return 1 if failed else 0

