"""Write the merged runtime config as msgpack at the canonical path.

Per Decision 0030 §2 + Decision 0035 §8: device format is msgpack;
canonical on-device path is ``/runtime_config.msgpack``.  This
module writes the host-side artifact at
``things/<name>/_generated/runtime_config.msgpack`` (deployer
overlays it onto device flash later); the path constant for the
on-device location lives in ``chumicro_config.runtime``
(Decision 0036) so the write side and the read side stay in sync
through one source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chumicro_msgpack import packb


def write_runtime_config(merged: dict[str, Any], output_path: Path) -> None:
    """Write *merged* as msgpack bytes to *output_path*.

    Creates the parent directory if needed (the typical caller
    targets ``things/<name>/_generated/runtime_config.msgpack``,
    where ``_generated/`` is gitignored and may not exist yet).

    Args:
        merged: The merged section-namespaced dict, post
            :func:`merge_configs` + :func:`resolve_secrets`.
        output_path: Where to write the msgpack file on the host.
            The deployer reads this and overlays it onto device
            flash at ``/runtime_config.msgpack``.

    Raises:
        TypeError: *merged* contains a value chumicro-msgpack can't
            encode (cycles, sets, custom classes — see Decision
            0034 §10 for the supported value types).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(packb(merged))
