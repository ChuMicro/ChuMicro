"""``partial`` behaves like CPython's ``functools.partial`` on CPython, MicroPython, and CircuitPython.

``partial(func, *args, **keywords)`` returns a callable that calls ``func``
with ``args`` ahead of the call's own positional arguments. A keyword given
at the call replaces the same keyword in ``keywords`` for that call only.
``partial(set_led, 13, label="status")(50)`` calls
``set_led(13, 50, label="status")``.

The returned callable keeps ``func``, ``args``, and ``keywords`` as
attributes. A ``partial`` of a ``partial`` flattens into one. ``partial``
raises ``TypeError`` when ``func`` is not callable.

``partial`` is the runtime's own ``functools.partial`` when that has the
``func``, ``args``, and ``keywords`` attributes, as on CPython. Elsewhere it
is a small pure-Python class.
"""


class _PurePythonPartial:
    """Pure-Python ``functools.partial`` with ``func``, ``args``, ``keywords``, and CPython's ``repr``."""

    def __init__(self, func: object, *args: object, **keywords: object) -> None:
        if not callable(func):
            raise TypeError(f"{func!r} is not callable")
        if isinstance(func, _PurePythonPartial):
            # Flatten nested partials like CPython so introspection matches.
            merged_keywords = func.keywords.copy()
            merged_keywords.update(keywords)
            args = func.args + args
            keywords = merged_keywords
            func = func.func
        self.func = func
        self.args = args
        self.keywords = keywords

    def __call__(self, *args: object, **keywords: object) -> object:
        if keywords:
            combined = self.keywords.copy()
            combined.update(keywords)
        else:
            # self.keywords is never mutated, so skip the per-call copy.
            combined = self.keywords
        return self.func(*self.args, *args, **combined)

    def __repr__(self) -> str:
        parts = [repr(self.func)]
        parts.extend(repr(arg) for arg in self.args)
        parts.extend(f"{key}={value!r}" for key, value in self.keywords.items())
        return f"functools.partial({', '.join(parts)})"


try:
    from functools import partial

    # Some MicroPython builds ship a degraded partial without .func/.args/.keywords.
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
