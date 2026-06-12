"""Tests for the cross-runtime swap context managers."""

from __future__ import annotations

from chumicro_test_harness.patching import FakeModule, SwapAttribute, SwapItem


class _Holder:
    """Attribute bag standing in for a module in SwapAttribute tests."""


def test_swap_attribute_replaces_and_restores_existing() -> None:
    """An existing attribute is replaced inside the block and the original
    value comes back on exit."""
    holder = _Holder()
    holder.adapter = "real"

    with SwapAttribute(holder, "adapter", "fake") as swap:
        assert holder.adapter == "fake"
        assert swap.replacement == "fake"
    assert holder.adapter == "real"


def test_swap_attribute_deletes_attribute_that_was_absent() -> None:
    """An attribute the holder never had is present inside the block and
    deleted again on exit."""
    holder = _Holder()

    with SwapAttribute(holder, "adapter", "fake"):
        assert holder.adapter == "fake"
    assert not hasattr(holder, "adapter")


def test_swap_attribute_restores_on_exception() -> None:
    """The original attribute value is restored even when the block raises,
    and the exception propagates."""
    holder = _Holder()
    holder.adapter = "real"

    raised = False
    try:
        with SwapAttribute(holder, "adapter", "fake"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised
    assert holder.adapter == "real"


def test_swap_item_replaces_and_restores_existing() -> None:
    """An existing mapping entry is replaced inside the block and the
    original value comes back on exit."""
    mapping = {"socketpool": "real"}

    with SwapItem(mapping, "socketpool", "stub"):
        assert mapping["socketpool"] == "stub"
    assert mapping["socketpool"] == "real"


def test_swap_item_deletes_key_that_was_absent() -> None:
    """A key the mapping never had is present inside the block and deleted
    again on exit."""
    mapping = {}

    with SwapItem(mapping, "socketpool", "stub"):
        assert mapping["socketpool"] == "stub"
    assert "socketpool" not in mapping


def test_swap_item_restores_on_exception() -> None:
    """The original mapping entry is restored even when the block raises,
    and the exception propagates."""
    mapping = {"socketpool": "real"}

    raised = False
    try:
        with SwapItem(mapping, "socketpool", "stub"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised
    assert mapping["socketpool"] == "real"


def test_fake_module_carries_hung_attributes() -> None:
    """Attributes hung on a FakeModule instance resolve like module members."""
    fake = FakeModule()
    fake.udp_socket = lambda: "socket"

    assert fake.udp_socket() == "socket"
