"""On-device test for ``load_runtime_config``.

The codec + dict-shape logic is covered host-side. The unique
device behavior is "open() works against the
`/runtime_config.msgpack` path on real flash."  This suite stages a
real msgpack file at the standard location, reads it back via the
library's reader, asserts the round-trip, and cleans up.

Runs on MicroPython only.  CircuitPython with USB MSC active mounts
``/`` read-only by default. The on-device write would fail with
``OSError`` before the assertion fires.  The
``__chumicro_runtimes__ = ("micropython",)`` marker keeps CP targets
out at collection time so the wrong-runtime parametrization never
deploys this file.
"""

__chumicro_runtimes__ = ("micropython",)

import os

from chumicro_config import (
    InvalidConfigType,
    load_runtime_config,
)
from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH
from chumicro_msgpack import packb
from chumicro_test_harness.assertions import raises


def _save_runtime_config() -> bytes | None:
    """Return the runtime-config file's bytes, or ``None`` if it is absent.

    Captured before a test overwrites or removes the standard path so
    the board's real deployed config survives the run.
    """
    try:
        with open(DEFAULT_RUNTIME_CONFIG_PATH, "rb") as handle:
            return handle.read()
    except OSError:
        return None  # Nothing deployed at the standard path.


def _restore_runtime_config(saved: bytes | None) -> None:
    """Rewrite *saved* bytes, or remove the file when *saved* is ``None``.

    Returns the standard path to the exact state ``_save_runtime_config``
    captured, so a provisioned board keeps its real config.
    """
    if saved is None:
        try:
            os.remove(DEFAULT_RUNTIME_CONFIG_PATH)
        except OSError:
            pass  # Was already absent when saved.
        return
    with open(DEFAULT_RUNTIME_CONFIG_PATH, "wb") as handle:
        handle.write(saved)


def _remove_runtime_config() -> None:
    """Remove the runtime-config file if present, to set up the absent state."""
    try:
        os.remove(DEFAULT_RUNTIME_CONFIG_PATH)
    except OSError:
        pass  # Already absent.


def test_round_trip_via_default_path() -> None:
    """Write a real msgpack file at the standard path, read it back.

    Uses the flat dotted-key shape every consumer library actually
    reads. This is the same shape ``chumicro_workspace.compose_runtime_config``
    writes at deploy time.  A nested payload would deserialize without
    error here (the reader only requires the outer value to be a dict)
    but would mislead readers of the test about the on-wire contract.
    """
    saved = _save_runtime_config()
    payload = {
        "wifi.ssid": "TestNet",
        "wifi.password": "fake",
        "app.sample_period_ms": 1000,
    }
    try:
        with open(DEFAULT_RUNTIME_CONFIG_PATH, "wb") as handle:
            handle.write(packb(payload))
        loaded = load_runtime_config()
        for key, value in payload.items():
            assert loaded[key] == value
    finally:
        _restore_runtime_config(saved)


def test_missing_file_raises_oserror_on_device() -> None:
    """A missing ``/runtime_config.msgpack`` raises ``OSError`` on real flash."""
    saved = _save_runtime_config()
    try:
        _remove_runtime_config()
        with raises(OSError):
            load_runtime_config()
    finally:
        _restore_runtime_config(saved)


def test_non_dict_payload_raises_invalid_type_on_device() -> None:
    """A non-dict payload (e.g. corrupted file) raises ``InvalidConfigType``."""
    saved = _save_runtime_config()
    try:
        with open(DEFAULT_RUNTIME_CONFIG_PATH, "wb") as handle:
            handle.write(packb([1, 2, 3]))  # decodes to list, not dict
        with raises(InvalidConfigType):
            load_runtime_config()
    finally:
        _restore_runtime_config(saved)


def test_default_path_constant_matches_on_device() -> None:
    """The path constant resolves to ``/runtime_config.msgpack`` on real flash."""
    assert DEFAULT_RUNTIME_CONFIG_PATH == "/runtime_config.msgpack"
