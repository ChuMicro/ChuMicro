"""Public exports for the test harness package.

The heavy exports resolve lazily (PEP 562): a board app importing only
the tiny :mod:`chumicro_test_harness.markers` helper must not pull the
runner / discovery machinery into RAM or onto flash.  The deploy walker
stages whatever the package ``__init__`` imports, so eager re-exports
here ride every such deploy; only the small names device-staged test
files import at package level are bound eagerly below.
"""

# ``skip`` stays eager: the export shares its name with its submodule,
# and importing ``chumicro_test_harness.skip`` anywhere binds the module
# onto the package, after which ``__getattr__`` never fires for the
# name and callers would receive the module instead of the function.
# Binding the function here (after the submodule import) wins durably;
# skip.py is a few KB, so eagerness costs nothing.
# ``raises`` stays eager: CircuitPython RAM-mode deploys resolve
# ``from chumicro_test_harness import raises`` against the module dict
# alone (module-level ``__getattr__`` never fires there), so every name
# a device-staged test file imports from this package must be bound
# here.  assertions.py is the same weight class as skip.py.
from chumicro_test_harness.assertions import raises
from chumicro_test_harness.skip import skip

_LAZY_EXPORTS = {
    "discover_source_roots": ("chumicro_test_harness.discovery", "discover_source_roots"),
    "run_one_file": ("chumicro_test_harness.discovery", "run_one_file"),
    "run_module": ("chumicro_test_harness.runner", "run_module"),
    "marker": ("chumicro_test_harness.markers", "marker"),
}


def __getattr__(name):
    """Resolve a public export on first access (PEP 562)."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = __import__(module_name, None, None, (attribute,))
    return getattr(module, attribute)


__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll] - the heavy exports
    # are PEP-562 lazy via __getattr__.
    "discover_source_roots",
    "marker",
    "raises",
    "run_module",
    "run_one_file",
    "skip",
]
