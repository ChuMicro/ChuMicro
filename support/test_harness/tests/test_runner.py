"""Tests for the lightweight test runner."""

from __future__ import annotations

import re
import sys
from types import SimpleNamespace

import chumicro_test_harness.runner as runner_module
from chumicro_test_harness import run_module


def test_run_module_executes_all_test_functions(capsys) -> None:
    """The runner should execute callable `test_*` members and ignore everything else."""
    state = {"ran": 0}

    def test_one() -> None:
        state["ran"] += 1

    def test_two() -> None:
        state["ran"] += 1

    module = SimpleNamespace(test_one=test_one, test_two=test_two, helper=lambda: None)

    result = run_module(module)
    output = capsys.readouterr().out

    assert result == 0
    assert state["ran"] == 2
    assert "PASS test_one" in output
    assert "PASS test_two" in output
    assert "SUMMARY total=2 failed=0" in output


def test_run_module_reports_failures(capsys) -> None:
    """The runner should return a failing exit code when any test raises an exception."""
    def test_failure() -> None:
        raise RuntimeError("boom")

    module = SimpleNamespace(test_failure=test_failure)

    result = run_module(module)
    output = capsys.readouterr().out

    assert result == 1
    assert "FAIL test_failure" in output
    assert "RuntimeError: boom" in output
    assert "SUMMARY total=1 failed=1" in output


def test_run_module_reports_when_no_tests_are_found(capsys) -> None:
    """The runner should print a friendly message when a module has no `test_*` callables."""
    result = run_module(SimpleNamespace(helper=lambda: None))
    output = capsys.readouterr().out

    assert result == 0
    assert "NO TESTS FOUND" in output
    assert "SUMMARY total=0 failed=0" in output


def test_run_module_uses_sys_print_exception_when_available(monkeypatch, capsys) -> None:
    """A MicroPython-style `sys.print_exception` hook should be preferred when present."""
    captured = []

    def fake_print_exception(exception: BaseException) -> None:
        captured.append(str(exception))

    def test_failure() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(sys, "print_exception", fake_print_exception, raising=False)

    result = run_module(SimpleNamespace(test_failure=test_failure))
    output = capsys.readouterr().out

    assert result == 1
    assert captured == ["boom"]
    assert "FAIL test_failure" in output


def test_run_module_handles_missing_traceback_support(monkeypatch, capsys) -> None:
    """The runner should still report failures when traceback support is unavailable."""
    def test_failure() -> None:
        raise RuntimeError("boom")

    monkeypatch.delattr(sys, "print_exception", raising=False)
    monkeypatch.setattr(runner_module, "traceback", None)

    result = run_module(SimpleNamespace(test_failure=test_failure))
    output = capsys.readouterr().out

    assert result == 1
    assert "RuntimeError: boom" in output


def test_run_module_includes_per_test_duration(capsys) -> None:
    """Each PASS/FAIL line should include the test duration in seconds."""
    module = SimpleNamespace(test_ok=lambda: None)

    run_module(module)
    output = capsys.readouterr().out

    assert re.search(r"PASS test_ok \(\d+\.\d{3}s\)", output)


def test_run_module_includes_total_duration(capsys) -> None:
    """The SUMMARY line should include total elapsed time."""
    module = SimpleNamespace(test_ok=lambda: None)

    run_module(module)
    output = capsys.readouterr().out

    assert re.search(r"time=\d+\.\d{3}s", output)


def test_run_module_duration_excludes_gc_collect_time(
    monkeypatch, capsys,
) -> None:
    """Per-test duration must exclude time spent in ``gc.collect``.

    Regression: on ESP32-S2 with PSRAM a single ``gc.collect`` can
    cost hundreds of ms.  The harness used to run the pre- and
    post-test collects *inside* the timed region, inflating a 50 ms
    test to well over a second.  The duration now brackets only
    ``function()``.
    """
    slow_collect_seconds = 0.5
    fake_time = {"now": 1000.0}

    def advance(delta_seconds: float) -> None:
        fake_time["now"] += delta_seconds

    fake_gc = SimpleNamespace(
        collect=lambda: advance(slow_collect_seconds),
        mem_free=lambda: 50000,
        disable=lambda: None,
        enable=lambda: None,
    )
    monkeypatch.setattr(runner_module, "_gc", fake_gc)
    monkeypatch.setattr(runner_module, "_MEM_FREE_AVAILABLE", True)
    monkeypatch.setattr(
        runner_module, "_now_seconds", lambda: fake_time["now"],
    )

    def test_quick() -> None:
        advance(0.05)  # 50 ms of real work inside the test

    module = SimpleNamespace(test_quick=test_quick)
    run_module(module)
    output = capsys.readouterr().out

    pass_line = next(
        line for line in output.splitlines() if line.startswith("PASS ")
    )
    match = re.search(r"\((\d+\.\d{3})s", pass_line)
    assert match is not None
    reported_duration = float(match.group(1))
    # Duration should be ~0.05 s (the test body) — never the ~0.55 s
    # that includes the post-test gc.collect.  Give a generous
    # tolerance to keep the test stable on CI timing jitter.
    assert reported_duration < 0.20, (
        f"Duration {reported_duration}s should exclude GC time "
        f"(expected ~0.05s)"
    )


def test_run_module_reports_heap_when_available(monkeypatch, capsys) -> None:
    """When gc.mem_free is available, per-test and module-level heap stats should appear."""
    fake_gc = SimpleNamespace(
        collect=lambda: None,
        mem_free=lambda: 50000,
        disable=lambda: None,
        enable=lambda: None,
    )
    monkeypatch.setattr(runner_module, "_gc", fake_gc)
    monkeypatch.setattr(runner_module, "_MEM_FREE_AVAILABLE", True)

    module = SimpleNamespace(test_ok=lambda: None)
    run_module(module)
    output = capsys.readouterr().out

    assert "PASS test_ok" in output
    assert "heap +0" in output
    assert "HEAP 50000 bytes free" in output
    assert "delta +0 bytes" in output


def test_run_module_skips_non_callable_test_attributes(capsys) -> None:
    """Attributes named test_* that are not callable should be silently skipped."""
    module = SimpleNamespace(test_value=42, test_ok=lambda: None)

    result = run_module(module)
    output = capsys.readouterr().out

    assert result == 0
    assert "PASS test_ok" in output
    assert "test_value" not in output
    assert "SUMMARY total=1 failed=0" in output


def test_run_module_name_filter_runs_only_matching_tests(capsys) -> None:
    """When name_filter is set, only tests whose name contains the filter should run."""
    state = {"ran": []}

    def test_alpha() -> None:
        state["ran"].append("alpha")

    def test_beta() -> None:
        state["ran"].append("beta")

    def test_alpha_extra() -> None:
        state["ran"].append("alpha_extra")

    module = SimpleNamespace(
        test_alpha=test_alpha, test_beta=test_beta, test_alpha_extra=test_alpha_extra
    )

    result = run_module(module, name_filter="alpha")
    output = capsys.readouterr().out

    assert result == 0
    assert "alpha" in state["ran"]
    assert "alpha_extra" in state["ran"]
    assert "beta" not in state["ran"]
    assert "PASS test_alpha" in output
    assert "PASS test_alpha_extra" in output
    assert "test_beta" not in output
    assert "SUMMARY total=2 failed=0" in output


def test_run_module_name_filter_no_matches(capsys) -> None:
    """When name_filter matches nothing, the runner should report no tests found."""
    module = SimpleNamespace(test_one=lambda: None)

    result = run_module(module, name_filter="nonexistent")
    output = capsys.readouterr().out

    assert result == 0
    assert "NO TESTS FOUND" in output
    assert "SUMMARY total=0 failed=0" in output


def test_run_module_name_filter_none_runs_all(capsys) -> None:
    """When name_filter is None (default), all tests should run."""
    state = {"ran": 0}

    def test_one() -> None:
        state["ran"] += 1

    def test_two() -> None:
        state["ran"] += 1

    module = SimpleNamespace(test_one=test_one, test_two=test_two)

    result = run_module(module, name_filter=None)
    output = capsys.readouterr().out

    assert result == 0
    assert state["ran"] == 2
    assert "SUMMARY total=2 failed=0" in output


def test_run_module_discovers_class_grouped_tests(capsys) -> None:
    """``class Test*`` collection mirrors pytest — methods + module-level functions both run."""
    state = {"calls": []}

    class TestExample:
        def test_alpha(self) -> None:
            state["calls"].append("TestExample.alpha")

        def test_beta(self) -> None:
            state["calls"].append("TestExample.beta")

        def helper(self) -> None:  # not collected — no test_ prefix
            state["calls"].append("helper")

    def test_module_level() -> None:
        state["calls"].append("module_level")

    module = SimpleNamespace(
        TestExample=TestExample,
        test_module_level=test_module_level,
    )

    result = run_module(module)
    output = capsys.readouterr().out

    assert result == 0
    assert sorted(state["calls"]) == [
        "TestExample.alpha",
        "TestExample.beta",
        "module_level",
    ]
    assert "PASS TestExample.test_alpha" in output
    assert "PASS TestExample.test_beta" in output
    assert "PASS test_module_level" in output
    assert "SUMMARY total=3 failed=0" in output


def test_run_module_class_test_gets_fresh_instance_per_method(capsys) -> None:
    """Each test method runs against a fresh instance — no state leak."""
    seen_ids: list[int] = []

    class TestIsolation:
        def __init__(self) -> None:
            self.value = 0

        def test_first(self) -> None:
            seen_ids.append(id(self))
            self.value = 99

        def test_second(self) -> None:
            seen_ids.append(id(self))
            assert self.value == 0  # not 99 from the prior test

    module = SimpleNamespace(TestIsolation=TestIsolation)

    result = run_module(module)
    capsys.readouterr()

    assert result == 0
    assert len(seen_ids) == 2
    assert seen_ids[0] != seen_ids[1]


def test_run_module_ignores_non_class_attrs_named_test(capsys) -> None:
    """Module-level objects named ``Test*`` that aren't classes are ignored."""
    not_a_class = SimpleNamespace(test_method=lambda self: None)

    module = SimpleNamespace(TestNotAClass=not_a_class)

    result = run_module(module)
    output = capsys.readouterr().out

    assert result == 0
    assert "NO TESTS FOUND" in output
