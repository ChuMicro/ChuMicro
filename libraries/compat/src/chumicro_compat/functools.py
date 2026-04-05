"""Cross-runtime ``functools.partial`` polyfill.

On CPython, re-exports the C-implemented ``functools.partial`` directly.
On MicroPython and CircuitPython (where ``functools.partial`` is absent),
provides a pure-Python implementation that matches CPython's public API.

Usage::

    from chumicro_compat.functools import partial

    greet = partial(print, "hello")
    greet("world")  # prints: hello world
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

    __slots__ = ("func", "args", "keywords")

    def __init__(self, func, *args, **keywords):
        """Create a partial object.

        Args:
            func: Callable to wrap.  Raises ``TypeError`` if not
                callable.
            *args: Positional arguments to freeze.
            **keywords: Keyword arguments to freeze.
        """
        if not callable(func):
            raise TypeError(f"{func!r} is not callable")
        self.func = func
        self.args = args
        self.keywords = keywords

    def __call__(self, *args, **keywords):
        """Call the wrapped function with frozen + extra arguments."""
        combined = self.keywords.copy()
        combined.update(keywords)
        return self.func(*self.args, *args, **combined)

    def __repr__(self):
        """Return a developer-friendly representation."""
        parts = [repr(self.func)]
        parts.extend(repr(a) for a in self.args)
        parts.extend(f"{k}={v!r}" for k, v in self.keywords.items())
        return f"functools.partial({', '.join(parts)})"


try:
    from functools import partial  # noqa: F401 — CPython; re-exported.
except ImportError:
    partial = _PurePythonPartial

