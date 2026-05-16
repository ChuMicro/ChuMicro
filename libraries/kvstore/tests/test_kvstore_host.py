"""Host-lane tests for ``KVStore``'s string-backend resolver.

These assert the *host development* experience: constructing a
per-runtime backend by string name (``"nvm"`` / ``"nvs"`` /
``"littlefs"``) on a machine that lacks the backing hardware/module
surfaces a clear error (or, for littlefs, constructs against the
ambient filesystem).  The expected behaviour is true only *off* the
target board — a real CircuitPython board has ``microcontroller`` (so
``"nvm"`` constructs instead of raising), a real ESP32 MicroPython
board has ``esp32`` (so ``"nvs"`` constructs), and a real CP board's
filesystem is read-only to Python by default (so ``"littlefs"`` would
fail there).  They run on CPython and the MicroPython / CircuitPython
unix-ports (no real hardware), never on the on-device sweep.

On-device backend coverage lives under ``functional_tests/``.
"""

#: Host-lane only — asserts the off-target string-resolver error UX;
#: a matching real board has the module/filesystem these expect absent.
__chumicro_host_only__ = True

from chumicro_kvstore import KVStore
from chumicro_test_harness import raises


def test_explicit_nvm_string_raises_runtime_error_on_cpython() -> None:
    """``backend="nvm"`` without ``microcontroller`` raises a clear error.

    The real CP NVM backend tries ``import microcontroller`` and
    surfaces a ``RuntimeError`` with an injection hint when the import
    fails.  Confirms the auto-resolver routes to ``CpNvmBackend``
    rather than silently falling through to memory.
    """
    with raises(RuntimeError):
        KVStore(backend="nvm")


def test_explicit_nvs_string_raises_runtime_error_on_cpython() -> None:
    """``backend="nvs"`` without ``esp32`` raises a clear error.

    Same pattern as the CP NVM check above: the resolver routes to
    ``MpNvsBackend`` whose default-arg path tries ``import esp32``
    and surfaces a ``RuntimeError`` with an injection hint when the
    import fails (CPython, MP unix-port without the esp32 stub).
    """
    with raises(RuntimeError):
        KVStore(backend="nvs")


def test_explicit_littlefs_string_resolves_on_any_filesystem_runtime() -> None:
    """``backend="littlefs"`` constructs anywhere ``os`` is available.

    The LittleFS backend talks to a generic filesystem shim
    (``builtins.open`` + ``os.rename`` / ``remove`` / ``sync``); it
    works on CPython, MicroPython, and (in principle) CircuitPython
    once a writable filesystem is mounted.  The constructor should
    succeed on CPython hosts even without a board.
    """
    store = KVStore(backend="littlefs")
    assert store.backend_name == "littlefs"
