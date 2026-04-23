"""Firmware URL resolution and (later) flashing.

Slice 1e.1 ships the URL-resolution half — given a board id,
runtime, and version, return the canonical download URL.  Today
CircuitPython URLs follow a stable Adafruit S3 template; MicroPython
URLs include a build-date component that changes per release and
currently requires a manual listing lookup, so MP resolution raises
:class:`UnresolvedFirmwareError` until the scraping path lands in a
later slice.

The actual download and flash (``flash_firmware``) is deliberately
held for Slice 1e.2 — it's destructive (erases existing firmware)
and warrants an explicit sign-off before running against boards.
"""

from __future__ import annotations

_DEFAULT_LANGUAGE = "en_US"

#: Adafruit publishes CP firmware at a stable path shape:
#:   ``https://downloads.circuitpython.org/bin/<board_id>/<lang>/\
#:   adafruit-circuitpython-<board_id>-<lang>-<version>.uf2``
#: Version format matches the Adafruit release (e.g. ``10.1.4`` for
#: stable, ``10.2.0-rc.0`` for pre-release).  This is the template
#: the ``resolve_firmware_url`` helper formats.
CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE = (
    "https://downloads.circuitpython.org/bin/{board_id}/{language}/"
    "adafruit-circuitpython-{board_id}-{language}-{version}.uf2"
)


class UnresolvedFirmwareError(Exception):
    """Raised when the firmware URL cannot be built from inputs.

    Typical causes:

    - Runtime is ``"micropython"``.  MP firmware URLs embed a
      per-build date that can't be inferred from the version alone;
      scraping the listing page is on the Slice 1e.2 / 1f roadmap.
    - Runtime is unrecognised (not ``circuitpython`` / ``micropython``).
    - A required field (board_id, version) is empty.
    """


def resolve_firmware_url(
    board_id: str,
    runtime: str,
    version: str,
    *,
    language: str = _DEFAULT_LANGUAGE,
) -> str:
    """Return the canonical firmware download URL.

    Args:
        board_id: Board identifier.  CircuitPython boards use the
            Adafruit ID (e.g. ``"raspberry_pi_pico_w"``,
            ``"adafruit_feather_esp32s3_4mbflash_2mbpsram"``).
        runtime: ``"circuitpython"`` or ``"micropython"``.
        version: Firmware version.  For CircuitPython, the Adafruit
            release label (``"10.1.4"`` for stable; ``"10.2.0-rc.0"``
            for pre-release).
        language: Adafruit language code (CircuitPython only).
            Defaults to ``"en_US"``.

    Returns:
        Fully-formed download URL.

    Raises:
        UnresolvedFirmwareError: If *runtime* is not supported, or
            if any required field is empty.
    """
    if not board_id:
        raise UnresolvedFirmwareError("board_id is required")
    if not version:
        raise UnresolvedFirmwareError("version is required")
    if runtime == "circuitpython":
        return CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE.format(
            board_id=board_id, version=version, language=language,
        )
    if runtime == "micropython":
        raise UnresolvedFirmwareError(
            "MicroPython firmware URLs embed a per-build date that "
            "cannot be inferred from the version alone.  Live listing "
            "lookup is not yet implemented; supply the URL directly "
            "until Slice 1e.2 adds scraping."
        )
    raise UnresolvedFirmwareError(
        f"Unsupported runtime: {runtime!r} "
        f"(expected 'circuitpython' or 'micropython')"
    )
