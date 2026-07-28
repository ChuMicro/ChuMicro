"""Cross-runtime swap context managers for monkeypatching in tests.

``unittest.mock.patch`` / ``patch.object`` / ``patch.dict`` don't exist
on the MicroPython and CircuitPython unix-ports, so cross-runtime tests
can't reach for them.  :class:`SwapAttribute` and :class:`SwapItem` are
the stand-ins: each is a context manager that installs a replacement on
enter and restores the original on exit, including the case where the
attribute or key was absent before (it is deleted again on exit).
:class:`FakeModule` is a bare class that stands in for a module object
where ``types.ModuleType`` would normally be used: the unix-ports omit
``types``, so tests build a plain instance and hang attributes on it.

Depends only on built-ins, so it loads on CPython, MicroPython, and
CircuitPython.  No ``contextlib``, ``typing``, or ``unittest`` import.
"""


class SwapAttribute:
    """Context manager that swaps ``module.name`` for *replacement*.

    On enter, sets ``module.name`` to *replacement* and remembers the
    prior value.  On exit, restores the prior value, or deletes the
    attribute when ``module`` had no ``name`` attribute to begin with.
    Used to redirect a module-level binding (an adapter reference, a
    lazily-imported stdlib name) to a test fake for the duration of a
    ``with`` block.
    """

    def __init__(self, module, name, replacement):
        self.module = module
        self.name = name
        self.replacement = replacement
        self._original = None
        self._had_attr = False

    def __enter__(self):
        self._had_attr = hasattr(self.module, self.name)
        if self._had_attr:
            self._original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.replacement)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self._had_attr:
            setattr(self.module, self.name, self._original)
        else:
            delattr(self.module, self.name)
        return False


class SwapItem:
    """Context manager that swaps ``mapping[key]`` for *replacement*.

    On enter, sets ``mapping[key]`` to *replacement* and remembers the
    prior value.  On exit, restores the prior value, or deletes the key
    when ``mapping`` had no entry to begin with.  The usual target is
    ``sys.modules['<name>']`` so an ``import <name>`` that would fail on
    a runtime missing the underlying module picks up the fake instead.
    """

    def __init__(self, mapping, key, replacement):
        self.mapping = mapping
        self.key = key
        self.replacement = replacement
        self._original = None
        self._had_key = False

    def __enter__(self):
        self._had_key = self.key in self.mapping
        if self._had_key:
            self._original = self.mapping[self.key]
        self.mapping[self.key] = self.replacement
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self._had_key:
            self.mapping[self.key] = self._original
        else:
            del self.mapping[self.key]
        return False


class FakeModule:
    """Bare class standing in for a module object where ``types`` is absent.

    The MicroPython and CircuitPython unix-ports ship no ``types``
    module, so ``types.ModuleType`` is unavailable.  An instance of
    this class plays the module role for ``sys.modules`` stubs: ``import
    foo`` on a stubbed key returns the instance, and ``from foo import
    bar`` resolves ``bar`` as an attribute the test hung on it.
    """
