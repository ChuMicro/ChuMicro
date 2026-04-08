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


def test_run_module_reports_heap_when_available(monkeypatch, capsys) -> None:
    """When gc.mem_free is available, HEAP stats should appear before and after."""
    fake_gc = SimpleNamespace(collect=lambda: None, mem_free=lambda: 50000)
    monkeypatch.setattr(runner_module, "_gc", fake_gc)

    module = SimpleNamespace(test_ok=lambda: None)
    run_module(module)
    output = capsys.readouterr().out

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


def test_memory_free_returns_none_without_gc_mem_free(monkeypatch) -> None:
    """_memory_free should return None when gc lacks mem_free."""
    monkeypatch.setattr(runner_module, "_gc", SimpleNamespace(collect=lambda: None))
    assert runner_module._memory_free() is None


def test_memory_free_returns_none_without_gc(monkeypatch) -> None:
    """_memory_free should return None when gc is not available."""
    monkeypatch.setattr(runner_module, "_gc", None)
    assert runner_module._memory_free() is None
