"""On-device test for ``load_runtime_config``.

The codec + dict-shape logic is covered host-side; the unique
device behavior is "open() works against the canonical
`/runtime_config.msgpack` path on real flash."  This suite stages a
real msgpack file at the canonical location, reads it back via the
library's reader, asserts the round-trip, and cleans up.

Skipped on devices where the filesystem is read-only at runtime
(CircuitPython with USB MSC active mounts ``/`` read-only by
default — the on-device write would fail with ``OSError`` before
the assertion fires).  On MicroPython boards the root filesystem
is writable so the test runs end-to-end.
"""

import sys

from chumicro_config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    InvalidConfigType,
    load_runtime_config,
)
from chumicro_msgpack import packb
from chumicro_test_harness.assertions import raises

_IS_MICROPYTHON = sys.implementation.name == "micropython"

if _IS_MICROPYTHON:
    import os


def _wipe_runtime_config() -> None:
    """Remove the runtime-config file if present."""
    try:
        os.remove(DEFAULT_RUNTIME_CONFIG_PATH)
    except OSError:
        pass  # Already absent — fine.


def test_round_trip_via_default_path() -> None:
    """Write a real msgpack file at the canonical path, read it back."""
    if not _IS_MICROPYTHON:
        return
    _wipe_runtime_config()
    payload = {
        "wifi": {"ssid": "TestNet", "password": "fake"},
        "app": {"sample_period_ms": 1000},
    }
    with open(DEFAULT_RUNTIME_CONFIG_PATH, "wb") as handle:
        handle.write(packb(payload))
    try:
        loaded = load_runtime_config()
        assert loaded == payload
    finally:
        _wipe_runtime_config()


def test_missing_file_raises_oserror_on_device() -> None:
    """A missing ``/runtime_config.msgpack`` raises ``OSError`` on real flash."""
    if not _IS_MICROPYTHON:
        return
    _wipe_runtime_config()
    with raises(OSError):
        load_runtime_config()


def test_non_dict_payload_raises_invalid_type_on_device() -> None:
    """A non-dict payload (e.g. corrupted file) raises ``InvalidConfigType``."""
    if not _IS_MICROPYTHON:
        return
    _wipe_runtime_config()
    try:
        with open(DEFAULT_RUNTIME_CONFIG_PATH, "wb") as handle:
            handle.write(packb([1, 2, 3]))  # decodes to list, not dict
        with raises(InvalidConfigType):
            load_runtime_config()
    finally:
        _wipe_runtime_config()


def test_default_path_constant_matches_adr_on_device() -> None:
    """The path constant is the same on every runtime (ADR 0030 §1)."""
    assert DEFAULT_RUNTIME_CONFIG_PATH == "/runtime_config.msgpack"
