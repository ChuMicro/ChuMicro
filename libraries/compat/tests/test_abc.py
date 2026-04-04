"""Tests for the lightweight abc implementation.

Verifies that ``ABC`` and ``abstractmethod`` enforce the abstract-method
contract across single-level, multi-level, and diamond inheritance.
"""

import pytest
from chumicro_compat.abc import ABC, abstractmethod

# -- abstractmethod decorator --


def test_abstractmethod_sets_flag():
    """@abstractmethod should set __isabstractmethod__ on the function."""

    @abstractmethod
    def some_method(self):
        """A placeholder."""

    assert some_method.__isabstractmethod__ is True


def test_regular_method_lacks_flag():
    """A plain function should not have __isabstractmethod__."""

    def some_method(self):
        """A placeholder."""

    assert not getattr(some_method, "__isabstractmethod__", False)


# -- ABC: instantiation enforcement --


def test_cannot_instantiate_abstract_class():
    """Instantiating a class with unimplemented abstract methods should raise TypeError."""

    class Base(ABC):
        """Abstract base with one abstract method."""

        @abstractmethod
        def work(self):
            """Must be implemented."""

    with pytest.raises(TypeError, match="work"):
        Base()


def test_can_instantiate_concrete_subclass():
    """A subclass that implements all abstract methods should instantiate."""

    class Base(ABC):
        """Abstract base."""

        @abstractmethod
        def work(self):
            """Must be implemented."""

    class Concrete(Base):
        """Implements work."""

        def work(self):
            """Do work."""
            return 42

    obj = Concrete()
    assert obj.work() == 42


def test_error_lists_all_missing_methods():
    """The TypeError message should list all unimplemented abstract methods."""

    class Base(ABC):
        """Abstract base with two abstract methods."""

        @abstractmethod
        def alpha(self):
            """Must be implemented."""

        @abstractmethod
        def beta(self):
            """Must be implemented."""

    with pytest.raises(TypeError, match="alpha") as exc_info:
        Base()
    assert "beta" in str(exc_info.value)


def test_partial_implementation_raises():
    """Implementing only some abstract methods should still raise TypeError."""

    class Base(ABC):
        """Abstract base with two abstract methods."""

        @abstractmethod
        def alpha(self):
            """Must be implemented."""

        @abstractmethod
        def beta(self):
            """Must be implemented."""

    class Partial(Base):
        """Implements only alpha."""

        def alpha(self):
            """Implemented."""
            return 1

    with pytest.raises(TypeError, match="beta"):
        Partial()


# -- Multi-level inheritance --


def test_multilevel_all_implemented():
    """Concrete class should work when abstract methods are spread across levels."""

    class Base(ABC):
        """Top-level abstract."""

        @abstractmethod
        def foo(self):
            """Must be implemented."""

    class Middle(Base):
        """Adds another abstract method without implementing foo."""

        @abstractmethod
        def bar(self):
            """Must be implemented."""

    class Concrete(Middle):
        """Implements everything."""

        def foo(self):
            """Implemented."""
            return 1

        def bar(self):
            """Implemented."""
            return 2

    obj = Concrete()
    assert obj.foo() == 1
    assert obj.bar() == 2


def test_intermediate_abstract_cannot_be_instantiated():
    """An intermediate abstract class should also raise TypeError."""

    class Base(ABC):
        """Top-level abstract."""

        @abstractmethod
        def foo(self):
            """Must be implemented."""

    class Middle(Base):
        """Still abstract — doesn't implement foo."""

        @abstractmethod
        def bar(self):
            """Must be implemented."""

    with pytest.raises(TypeError, match="foo"):
        Middle()


def test_implementation_at_middle_level():
    """A middle class can implement some methods; the leaf finishes the rest."""

    class Base(ABC):
        """Two abstract methods."""

        @abstractmethod
        def foo(self):
            """Must be implemented."""

        @abstractmethod
        def bar(self):
            """Must be implemented."""

    class Middle(Base):
        """Implements foo, leaves bar abstract."""

        def foo(self):
            """Implemented."""
            return "foo"

    class Leaf(Middle):
        """Implements bar."""

        def bar(self):
            """Implemented."""
            return "bar"

    # Middle is still abstract (bar missing).
    with pytest.raises(TypeError, match="bar"):
        Middle()

    # Leaf is concrete.
    obj = Leaf()
    assert obj.foo() == "foo"
    assert obj.bar() == "bar"


# -- Diamond inheritance --


def test_diamond_inheritance():
    """Diamond inheritance should correctly resolve abstract methods."""

    class Base(ABC):
        """Top of the diamond."""

        @abstractmethod
        def work(self):
            """Must be implemented."""

    class Left(Base):
        """Left branch — implements work."""

        def work(self):
            """Implemented on left branch."""
            return "left"

    class Right(Base):
        """Right branch — still abstract."""

    class Diamond(Left, Right):
        """Merges both branches — Left provides the implementation."""

    obj = Diamond()
    assert obj.work() == "left"


# -- __init__ with arguments --


def test_concrete_with_init_args():
    """Concrete classes with __init__ arguments should work."""

    class Base(ABC):
        """Abstract base."""

        @abstractmethod
        def value(self):
            """Must be implemented."""

    class Concrete(Base):
        """Concrete with constructor arguments."""

        def __init__(self, val):
            """Store a value."""
            self._val = val

        def value(self):
            """Return the stored value."""
            return self._val

    obj = Concrete(99)
    assert obj.value() == 99


# -- No abstract methods --


def test_abc_subclass_with_no_abstracts():
    """A direct ABC subclass with no abstract methods should instantiate."""

    class Plain(ABC):
        """No abstract methods at all."""

        def greet(self):
            """A normal method."""
            return "hi"

    obj = Plain()
    assert obj.greet() == "hi"

