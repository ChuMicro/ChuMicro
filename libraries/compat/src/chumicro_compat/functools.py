"""Cross-runtime ``functools.partial`` polyfill.

On CPython this re-exports the built-in ``functools.partial``; on
MicroPython and CircuitPython, where it is missing, it provides a
matching pure-Python implementation.
"""


class _PurePythonPartial:
    """Pure-Python ``functools.partial`` for runtimes that lack it."""

    def __init__(self, func: object, *args: object, **keywords: object) -> None:
        if not callable(func):
            raise TypeError(f"{func!r} is not callable")
        if isinstance(func, _PurePythonPartial):
            # Flatten a nested partial like CPython: outer args extend the
            # inner's and outer keywords win, so introspection matches CPython.
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
            # No call-time keywords: reuse the frozen dict directly (it is
            # never mutated) instead of copying it on every call.
            combined = self.keywords
        return self.func(*self.args, *args, **combined)

    def __repr__(self) -> str:
        parts = [repr(self.func)]
        parts.extend(repr(arg) for arg in self.args)
        parts.extend(f"{key}={value!r}" for key, value in self.keywords.items())
        return f"functools.partial({', '.join(parts)})"


try:
    from functools import partial

    # Some MicroPython builds ship a degraded ``partial`` without the
    # .func/.args/.keywords attributes, so feature-detect and fall back.
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
