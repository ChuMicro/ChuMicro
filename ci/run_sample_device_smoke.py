"""Run the sample timing smoke test through the lightweight harness.

This file is intentionally import-free enough to execute consistently under the
current CPython, MicroPython unix-port, and CircuitPython unix-port paths.
See `plans/decisions/0006-shared-import-free-compatibility-smoke-runner.md`.
"""

import time


class _ModuleNamespace:
    """Simple object namespace for manually executed module code."""


def _namespace_to_object(namespace):
    """Convert an execution namespace into a plain attribute object."""
    module = _ModuleNamespace()
    for key in namespace:
        setattr(module, key, namespace[key])
    return module


def _execute_source(file_path, module_name, package_name=""):
    """Execute a source file and return its globals namespace."""
    namespace: dict[str, object] = {}
    namespace["__name__"] = module_name
    namespace["__file__"] = file_path
    namespace["__package__"] = package_name
    with open(file_path) as source_file:
        source = source_file.read()

    exec(source, namespace)
    return namespace


def _build_test_module(ticks_ms, ticks_diff):
    """Return a module-like object containing the timing smoke test."""
    namespace: dict[str, object] = {}
    namespace["__name__"] = "test_heartbeat_ticks"
    namespace["__file__"] = "sample/device_tests/test_heartbeat_ticks.py"
    namespace["__package__"] = ""
    namespace["time"] = time

    def _sleep_ms(duration_ms):
        runtime_sleep_ms = getattr(time, "sleep_ms", None)
        if callable(runtime_sleep_ms):
            runtime_sleep_ms(duration_ms)
            return

        time.sleep(duration_ms / 1000)

    def test_ticks_progress_on_runtime():
        start_ms = ticks_ms()
        _sleep_ms(20)
        end_ms = ticks_ms()
        assert ticks_diff(end_ms, start_ms) >= 1

    namespace["_sleep_ms"] = _sleep_ms
    namespace["test_ticks_progress_on_runtime"] = test_ticks_progress_on_runtime
    return _namespace_to_object(namespace)


def main():
    """Run the checked-in timing smoke test and return a shell-style exit code."""
    ticks_namespace = _execute_source(
        "sample/src/chumicro_sample/ticks.py",
        "chumicro_sample.ticks",
        package_name="chumicro_sample",
    )
    runner_namespace = _execute_source(
        "support/test_harness/src/chumicro_test_harness/runner.py",
        "chumicro_test_harness.runner",
        package_name="chumicro_test_harness",
    )
    test_module = _build_test_module(
        ticks_namespace["ticks_ms"],
        ticks_namespace["ticks_diff"],
    )
    return runner_namespace["run_module"](test_module)


raise SystemExit(main())
