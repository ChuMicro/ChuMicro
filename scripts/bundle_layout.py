"""Single source of truth for bundle layout constants.

Both ``bundle_manager`` (the producer) and ``validate_mip_install`` (the
consumer) need to agree on where compiled bytecode lives in the bundle
repos.  Keeping the constants in one module makes "add another mpy
format version" (see plans/open-questions.md) a one-file change instead
of grepping for string literals.

See [Decision 0024](../plans/decisions/0024-mip-mpy-folder-serving.md)
for the folder-naming scheme and the rationale for separate
per-format-version folders.
"""

from __future__ import annotations

#: Bundle repository names for each channel.  Experimental uses a
#: separate repository so that circup's latest_tag works per-channel
#: without prerelease tag tricks.
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"

#: MicroPython mpy bytecode format version folder name.  mpy v6 is used
#: by MicroPython 1.24+.  Contains .mpy files compiled with MicroPython's
#: mpy-cross (magic byte 'M') and ``package.json`` manifests for mip.
MPY_FORMAT_FOLDER = "mpy6"

#: CircuitPython .mpy folder name.  Follows Adafruit's naming convention
#: where "10.x" reflects the CircuitPython version range.  Contains
#: .mpy files compiled with CircuitPython's mpy-cross (magic byte 'C'),
#: consumed by circup via zip bundles.
CP_MPY_FOLDER = "circuitpython-10.x-mpy"


def mpy_format_folders() -> tuple[str, ...]:
    """Return all supported MicroPython mpy-format folder names.

    Returns a single-element tuple today.  When the workspace gains
    multi-mpy-version support (see plans/open-questions.md), this is
    where the list expands — every consumer iterates over this tuple
    instead of referencing :data:`MPY_FORMAT_FOLDER` directly.
    """
    return (MPY_FORMAT_FOLDER,)


def cp_mpy_folders() -> tuple[str, ...]:
    """Return all supported CircuitPython mpy folder names.

    Returns a single-element tuple today.  Same expansion story as
    :func:`mpy_format_folders` for CircuitPython 11+ / mpy v7 if/when
    those land.
    """
    return (CP_MPY_FOLDER,)
