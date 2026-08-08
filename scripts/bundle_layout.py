"""Single source of truth for bundle layout constants.

Both ``bundle_manager`` (the producer) and ``validate_mip_install`` (the
consumer) need to agree on where compiled bytecode lives in the bundle
repos.  Keeping the names here means nobody greps for string literals to
find them.

"Add another mpy format version" is not a one-file change, and this
module used to claim it was.  Reading the bundle is covered: the
validator iterates :func:`mpy_format_folders`, so a longer tuple
validates the new folder on its own.  Writing it is bounded by the
toolchain instead of by this file, because each folder needs its own
pinned mpy-cross.  :func:`mpy_format_folders` carries the current split.

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

#: Full-source-tree channel repos for host-side workspace acquisition
#: (``chumicro-workspace library add/browse``).  Distinct from the
#: device bundles above: those are deploy-flattened ``.py``+``.mpy``
#: for circup/mip; these carry each library's whole tree
#: (src/tests/examples/docs/pyproject/VERSION/README) plus a root
#: ``index.json`` catalog, tag-versioned with the same snapshot model.
STABLE_LIBRARIES_REPO = "ChuMicro-Libraries"
EXPERIMENTAL_LIBRARIES_REPO = "ChuMicro-Libraries-Experimental"

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
    multi-mpy-version support (Decision 0112), this is where the list
    expands.

    Consumers that *read* the bundle iterate this tuple, so a new folder
    is covered without editing them: ``validate_mip_install`` validates
    every entry it returns.  The producer is not symmetric and cannot be.
    ``bundle_manager`` stages one folder per pinned mpy-cross binary, so
    adding a format means pinning another compiler in
    ``target-runtimes.toml`` and giving ``stage`` a second pass, not just
    lengthening this tuple.  Within a pass every path and dependency
    reference is threaded from the folder being staged, so the two ABI
    generations cannot cross-reference each other's packages.
    """
    return (MPY_FORMAT_FOLDER,)


def cp_mpy_folders() -> tuple[str, ...]:
    """Return all supported CircuitPython mpy folder names.

    Returns a single-element tuple today.  Same expansion story as
    :func:`mpy_format_folders` for CircuitPython 11+ / mpy v7 if/when
    those land.
    """
    return (CP_MPY_FOLDER,)
