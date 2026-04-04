"""Public exports for the lightweight test harness."""

from .assertions import raises
from .discovery import discover_source_roots, discover_tests, exec_as_namespace, run_all
from .runner import run_module

__all__ = [
    "discover_source_roots",
    "discover_tests",
    "exec_as_namespace",
    "raises",
    "run_all",
    "run_module",
]

