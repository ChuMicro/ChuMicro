"""Write the merged runtime config as msgpack at the on-device path.

Device format is msgpack.  The on-device path is
``/runtime_config.msgpack``.  This module writes the host-side
artifact at ``projects/<name>/_generated/runtime_config.msgpack``,
which the deployer later overlays onto device flash. The path
constant for the on-device location lives in
``chumicro_config.runtime`` so the write side and the read side
stay in sync.

Wire compatibility with the device-side reader is preserved by
passing ``use_single_float=True`` so floats encode as float32
(``0xca`` + 4 bytes), which CircuitPython's native ``msgpack``
module accepts (CP doesn't support float64).  The caller is also
expected to keep integers in ``[-2**31, 2**32-1]`` and
string/bin/array/map sizes under 65 536, matching the
chumicro-msgpack 32-bit/16-bit subset that the device-side decoder
enforces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from msgpack import packb


def write_runtime_config(merged: dict[str, Any], output_path: Path) -> None:
    """Write *merged* as msgpack bytes to *output_path*.

    Creates the parent directory if needed.

    Args:
        merged: The merged section-namespaced dict, post
            :func:`merge_configs`.
        output_path: Where to write the msgpack file on the host.
            The on-device deployment lands it at
            ``/runtime_config.msgpack``.

    Raises:
        TypeError: *merged* contains a value msgpack can't encode
            (cycles, sets, custom classes).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(packb(merged, use_single_float=True))
