"""Cross-runtime ``functools.partial`` polyfill.

On CPython, re-exports the C-implemented ``functools.partial`` directly.
On MicroPython and CircuitPython (where ``functools.partial`` is absent),
provides a pure-Python implementation that matches CPython's public API.

Example:
    ```python
    from chumicro_compat.functools import partial

    greet = partial(print, "hello")
    greet("world")  # prints: hello world
    ```
"""


class _PurePythonPartial:
    """Pure-Python ``functools.partial`` for runtimes that lack it.

    Freezes positional and keyword arguments to a callable.  The
    public attributes mirror CPython's ``functools.partial``:

    Attributes:
        func: The wrapped callable.
        args: Frozen positional arguments (tuple).
        keywords: Frozen keyword arguments (dict).
    """

    def __init__(self, func: object, *args: object, **keywords: object) -> None:
        """Create a partial object.

        Args:
            func: Callable to wrap.  Raises ``TypeError`` if not
                callable.
            *args: Positional arguments to freeze.
            **keywords: Keyword arguments to freeze.
        """
        if not callable(func):
            raise TypeError(f"{func!r} is not callable")
        if isinstance(func, _PurePythonPartial):
            # Flatten a nested partial the way CPython does: the outer
            # args extend the inner's, and outer keywords override inner
            # ones — so .func / .args / .keywords match CPython instead
            # of nesting one partial inside another.
            merged_keywords = func.keywords.copy()
            merged_keywords.update(keywords)
            args = func.args + args
            keywords = merged_keywords
            func = func.func
        self.func = func
        self.args = args
        self.keywords = keywords

    def __call__(self, *args: object, **keywords: object) -> object:
        """Call the wrapped function with frozen + extra arguments."""
        if keywords:
            combined = self.keywords.copy()
            combined.update(keywords)
        else:
            # No call-time keywords: pass the frozen dict straight
            # through (it's never mutated) rather than copying it every
            # call — this is the hot path on the runtimes where this
            # class actually runs.
            combined = self.keywords
        return self.func(*self.args, *args, **combined)

    def __repr__(self) -> str:
        """Return a ``functools.partial(...)`` string showing func, args, and keywords."""
        parts = [repr(self.func)]
        parts.extend(repr(arg) for arg in self.args)
        parts.extend(f"{key}={value!r}" for key, value in self.keywords.items())
        return f"functools.partial({', '.join(parts)})"


try:
    from functools import partial

    # Feature-detect rather than trust the import: some MicroPython
    # builds (micropython-lib) ship a degraded closure-based ``partial``
    # that lacks the .func / .args / .keywords introspection attributes.
    # If the imported partial can't introspect, fall back to the pure
    # implementation so behavior is identical on every runtime.
    _probe = partial(int, 0)
    if not (
        hasattr(_probe, "func")
        and hasattr(_probe, "args")
        and hasattr(_probe, "keywords")
    ):  # pragma: no cover - only micropython-lib's degraded partial hits this
        partial = _PurePythonPartial
    del _probe
except ImportError:  # pragma: no cover - MicroPython/CircuitPython fallback
    partial = _PurePythonPartial
