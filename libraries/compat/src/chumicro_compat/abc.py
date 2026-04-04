"""Lightweight abstract base class support for all Python runtimes.

Provides ``ABC`` and ``abstractmethod`` for CPython, MicroPython, and
CircuitPython without requiring the ``abc`` standard-library module or
metaclasses.

Uses ``__init_subclass__`` (available on MicroPython ≥1.19.1 and
CircuitPython ≥8.x) to collect abstract methods at class-definition
time, and ``__new__`` to enforce them at instantiation time.

Usage::

    from chumicro_compat.abc import ABC, abstractmethod


    class Base(ABC):

        @abstractmethod
        def do_work(self):
            \"\"\"Subclasses must implement this.\"\"\"

    class Concrete(Base):

        def do_work(self):
            return 42

    Concrete()   # OK
    Base()       # TypeError: Can't instantiate abstract class Base ...
"""

try:
    from micropython import const
except ImportError:

    def const(x):
        """Identity fallback for CPython (no micropython.const)."""
        return x


_ATTR = const("__isabstractmethod__")
_METHODS = const("__abstractmethods__")


def abstractmethod(func):
    """Mark a method as abstract.

    Subclasses of ``ABC`` must override any method decorated with
    ``@abstractmethod``; otherwise instantiation raises ``TypeError``.
    """
    setattr(func, _ATTR, True)
    return func


class ABC:
    """Base class for defining abstract classes on all runtimes.

    Works without metaclasses.  ``__init_subclass__`` collects abstract
    methods from the class hierarchy at class-definition time;
    ``__new__`` checks them at instantiation time.

    Subclasses that leave any ``@abstractmethod``-decorated methods
    unoverridden cannot be instantiated.
    """

    def __init_subclass__(cls, **kwargs):
        """Collect abstract methods from the class hierarchy."""
        super().__init_subclass__(**kwargs)
        abstracts = set()
        for name in dir(cls):
            val = getattr(cls, name, None)
            if getattr(val, _ATTR, False):
                abstracts.add(name)
        setattr(cls, _METHODS, abstracts)

    def __new__(cls, *_args, **_kwargs):
        """Raise ``TypeError`` if abstract methods remain unimplemented."""
        abstracts = getattr(cls, _METHODS, None)
        if abstracts:
            names = ", ".join(sorted(abstracts))
            raise TypeError(
                f"Can't instantiate abstract class {cls.__name__} "
                f"with abstract methods: {names}"
            )
        return super().__new__(cls)

