"""CPython-only tests for ``default_client_id``'s UID-source ladder.

``default_client_id`` derives a stable per-device MQTT client id so two
boards sharing a broker never collide on the same id.  A duplicate id is
not benign under MQTT 3.1.1: the broker evicts the older session when a
second client connects with its id, and the evicted board immediately
reconnects and evicts the first in turn, producing a reconnect storm.
The old fixed default ``chumicro-mqtt`` did exactly this across a batch
of boards; the ladder replaced it.

The id is derived from the first UID source that answers:
``microcontroller.cpu.uid`` on CircuitPython, ``machine.unique_id()`` on
MicroPython, or the host MAC via ``uuid.getnode()`` on CPython.  Only
when none is available does it fall back to a fixed ``<prefix>-mqtt`` --
the one path back to the colliding behaviour, so it must trigger solely
as a last resort.

Each rung is driven by injecting a fake device module into
``sys.modules``; setting a name to ``None`` there forces its ``import``
to raise, standing in for a runtime that lacks that module.  Both the
``None`` import sentinel and ``types.SimpleNamespace`` are CPython-only,
so these stay off the MicroPython / CircuitPython lanes; the real UID
sources are covered on-device by the hardware suites.
"""

__chumicro_runtimes__ = ("cpython",)

import sys
import types

from chumicro_mqtt import default_client_id


class TestDefaultClientIdLadder:
    """Each UID rung is selected in order and hex-formatted."""

    def test_microcontroller_uid_is_primary(self, monkeypatch) -> None:
        """CircuitPython's ``microcontroller.cpu.uid`` wins when present.

        The real attribute is a bytearray, so the fake mirrors that type
        to prove ``bytes(...)`` accepts it.
        """
        fake = types.SimpleNamespace(
            cpu=types.SimpleNamespace(uid=bytearray([0xDE, 0xAD, 0xBE, 0xEF])),
        )
        monkeypatch.setitem(sys.modules, "microcontroller", fake)
        assert default_client_id() == "chumicro-deadbeef"

    def test_microcontroller_wins_over_machine(self, monkeypatch) -> None:
        """With both device modules present, the first rung is taken."""
        micro = types.SimpleNamespace(
            cpu=types.SimpleNamespace(uid=bytearray([0xAA])),
        )
        machine = types.SimpleNamespace(unique_id=lambda: bytes([0xBB]))
        monkeypatch.setitem(sys.modules, "microcontroller", micro)
        monkeypatch.setitem(sys.modules, "machine", machine)
        assert default_client_id() == "chumicro-aa"

    def test_machine_unique_id_is_fallback(self, monkeypatch) -> None:
        """MicroPython's ``machine.unique_id()`` is used when microcontroller
        is absent."""
        monkeypatch.setitem(sys.modules, "microcontroller", None)
        machine = types.SimpleNamespace(unique_id=lambda: bytes([0x01, 0x02, 0x03]))
        monkeypatch.setitem(sys.modules, "machine", machine)
        assert default_client_id() == "chumicro-010203"

    def test_uuid_getnode_is_last_uid_source(self, monkeypatch) -> None:
        """The CPython host path derives 12 hex chars from the 48-bit MAC."""
        monkeypatch.setitem(sys.modules, "microcontroller", None)
        monkeypatch.setitem(sys.modules, "machine", None)
        monkeypatch.setattr("uuid.getnode", lambda: 0x001122334455)
        assert default_client_id() == "chumicro-001122334455"

    def test_low_bytes_are_zero_padded(self, monkeypatch) -> None:
        """Each UID byte is two lowercase hex digits, so a low byte pads."""
        fake = types.SimpleNamespace(
            cpu=types.SimpleNamespace(uid=bytearray([0x00, 0x0A, 0xFF])),
        )
        monkeypatch.setitem(sys.modules, "microcontroller", fake)
        assert default_client_id() == "chumicro-000aff"

    def test_literal_fallback_when_no_uid_source(self, monkeypatch) -> None:
        """No UID source at all returns the historical ``<prefix>-mqtt``.

        This is the only path back to the colliding default, so it must
        trigger only when every rung fails.  A guarded ``getnode`` error
        stands in for a host with no readable MAC.
        """
        monkeypatch.setitem(sys.modules, "microcontroller", None)
        monkeypatch.setitem(sys.modules, "machine", None)

        def _no_mac():
            raise OSError("no hardware address")

        monkeypatch.setattr("uuid.getnode", _no_mac)
        assert default_client_id() == "chumicro-mqtt"
        assert default_client_id(prefix="dev") == "dev-mqtt"
