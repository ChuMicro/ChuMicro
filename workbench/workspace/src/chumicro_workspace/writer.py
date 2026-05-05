"""Write the merged runtime config as msgpack at the canonical path.

Per Decision 0030 §2 + Decision 0035 §8: device format is msgpack;
canonical on-device path is ``/runtime_config.msgpack``.  This
module writes the host-side artifact at
``projects/<name>/_generated/runtime_config.msgpack`` (deployer
overlays it onto device flash later); the path constant for the
on-device location lives in ``chumicro_config.runtime``
(Decision 0036) so the write side and the read side stay in sync
through one source of truth.

Encoder choice: standard ``msgpack`` from PyPI (the well-maintained
host-side library).  Workbench packages don't import from
``libraries/`` per the ecosystem boundary — those packages are
*for the board*.  Wire compatibility with the device-side reader
is preserved by passing ``use_single_float=True`` so floats encode
as float32 (``0xca`` + 4 bytes), which CircuitPython's native
``msgpack`` module accepts (CP doesn't support float64).  The
caller is also expected to keep integers in
``[-2**31, 2**32-1]`` and string/bin/array/map sizes under
65 536 — matching the chumicro-msgpack 32-bit/16-bit subset that
the device-side decoder enforces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from msgpack import packb


def write_runtime_config(merged: dict[str, Any], output_path: Path) -> None:
    """Write *merged* as msgpack bytes to *output_path*.

    Creates the parent directory if needed (the typical caller
    targets ``projects/<name>/_generated/runtime_config.msgpack``,
    where ``_generated/`` is gitignored and may not exist yet).

    Args:
        merged: The merged section-namespaced dict, post
            :func:`merge_configs` (Decision 0057 — no separate
            secrets-resolution step; gitignored overlay is just
            another merge layer).
        output_path: Where to write the msgpack file on the host.
            The deployer reads this and overlays it onto device
            flash at ``/runtime_config.msgpack``.

    Raises:
        TypeError: *merged* contains a value msgpack can't encode
            (cycles, sets, custom classes — see Decision 0034 §10
            for the supported value types).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(packb(merged, use_single_float=True))
