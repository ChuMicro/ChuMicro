"""On-device reader for ``/runtime_config.msgpack``.

Centralises the path constant + msgpack decode + dict-shape check
so user app code is one line instead of three (and the path constant
isn't hard-coded across every library that reads it).
"""

from chumicro_msgpack import unpackb

from chumicro_config.section import InvalidConfigType

DEFAULT_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"
"""Canonical on-device location of the deployed runtime config.

Fixed by Decision 0030 §1 / Decision 0035 §8.  Changing it would be
an ABI break for every library + every workspace template.
"""


def load_runtime_config(path=None):
    """Read + decode the deployed runtime config.

    Args:
        path: On-device path to the msgpack file.  ``None`` (default)
            resolves to :data:`DEFAULT_RUNTIME_CONFIG_PATH` at call
            time — the indirection lets tests monkey-patch the
            constant without losing the default-arg ergonomics.

    Returns:
        The section-namespaced dict per Decision 0035 §1.

    Raises:
        OSError: File missing — device was deployed without a
            ``/runtime_config.msgpack``, or the path is wrong.
        InvalidConfigType: Decoded payload isn't a dict (corrupted
            file or wrong shape).
    """
    if path is None:
        path = DEFAULT_RUNTIME_CONFIG_PATH
    with open(path, "rb") as handle:
        decoded = unpackb(handle.read())
    if not isinstance(decoded, dict):
        raise InvalidConfigType(
            f"runtime config must decode to a dict, got {type(decoded).__name__}"
        )
    return decoded
