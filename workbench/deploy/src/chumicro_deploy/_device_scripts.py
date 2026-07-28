"""On-device script sources for the MicroPython transport.

Host-side home for the Python snippets the transport execs on a
board (raw REPL or ``mpremote exec``), plus the host-side parser for
the scope-listing scripts' output.  Marker, emitter, and parser live
together so they cannot drift apart.

Every script body is pure stdlib (``os.listdir`` + ``os.stat``) so it
runs on any MicroPython / CircuitPython build without preinstalled
helper libs.  Missing dirs and per-file ``OSError`` are tolerated so a
fresh-flashed board (no ``/lib/`` yet) yields an empty result instead
of erroring out.  Shared fragments (the recursive walk, the recursive
rmtree) are defined once and composed per script.  Follows the
``PROBE_IMPLEMENTATION_SCRIPT`` model in :mod:`.protocol`.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Sentinel prefix the scope-listing scripts emit in front of every
#: found file path.  Host-side parsing scans for this marker so any
#: incidental ``print()`` from an autorun ``boot.py`` etc. doesn't
#: contaminate the listing.
SCOPE_LISTING_MARKER: str = "__CHU_F:"


def parse_scope_listing(output: str) -> list[str]:
    """Extract device paths from a scope-listing script's stdout.

    Filters to lines starting with :data:`SCOPE_LISTING_MARKER` so
    surrounding output (raw-REPL banner, autorun prints) doesn't
    contaminate the result.  Returns deduplicated paths in the
    order they appear.
    """
    seen: set[str] = set()
    result: list[str] = []
    for line in output.splitlines():
        if not line.startswith(SCOPE_LISTING_MARKER):
            continue
        path = line[len(SCOPE_LISTING_MARKER):].strip()
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


#: Recursive file walk that prints every file path behind the
#: listing marker.  ``stat[0] & 0x4000`` is the directory bit.
_WALK_AND_PRINT_DEF: str = (
    "import os\n"
    "def _walk(p):\n"
    "    try:\n"
    "        names = os.listdir(p)\n"
    "    except OSError:\n"
    "        return\n"
    "    for name in names:\n"
    "        full = p + '/' + name if p != '/' else '/' + name\n"
    "        try:\n"
    "            stat = os.stat(full)\n"
    "        except OSError:\n"
    "            continue\n"
    "        if stat[0] & 0x4000:\n"
    "            _walk(full)\n"
    "        else:\n"
    f"            print({SCOPE_LISTING_MARKER!r} + full)\n"
)

#: Implements the additive (``clean_slate=False``) walk for
#: :func:`chumicro_deploy.protocol.is_in_deploy_scope`: the four
#: entrypoint / state files plus everything under ``/lib``.  The
#: embedded path tuple mirrors ``protocol.DEPLOY_SCOPE_FILES`` (pinned
#: by a unit test) but stays a literal so the device-visible listing
#: order is deterministic.
LIST_SCOPE_SCRIPT: str = _WALK_AND_PRINT_DEF + (
    "for path in ('/code.py', '/main.py', '/active.py', '/runtime_config.msgpack'):\n"
    "    try:\n"
    "        os.stat(path)\n"
    "    except OSError:\n"
    "        continue\n"
    f"    print({SCOPE_LISTING_MARKER!r} + path)\n"
    "_walk('/lib')\n"
)

#: Implements the ``clean_slate=True`` walk: every file on the device.
#: The host filters out :data:`flash_drive.DEVICE_KEEP_SET` (and any
#: dot-prefixed path) post-walk.
LIST_ALL_SCRIPT: str = _WALK_AND_PRINT_DEF + "_walk('/')\n"


#: Recursive rmtree tolerant of files, dirs, and already-absent
#: paths: try dir-removal first, fall back to file removal, swallow
#: the rest (best-effort, since the post-``fs cp`` free-space check is the
#: real guard downstream).
_RMTREE_DEF: str = (
    "import os\n"
    "def _rm(p):\n"
    "    try:\n"
    "        for e in os.listdir(p):\n"
    "            _rm(p + '/' + e)\n"
    "        os.rmdir(p)\n"
    "    except OSError:\n"
    "        try:\n"
    "            os.remove(p)\n"
    "        except OSError:\n"
    "            pass\n"
)


def clean_slate_script(keep: Iterable[str]) -> str:
    """Remove every device-root entry except *keep* (recursively).

    Args:
        keep: Basenames that survive (typically
            ``flash_drive.DEVICE_KEEP_SET``).  Sorted into the script
            so the generated source is deterministic.
    """
    return _RMTREE_DEF + (
        f"_keep = {sorted(keep)!r}\n"
        "for _e in os.listdir('/'):\n"
        "    if _e not in _keep:\n"
        "        _rm('/' + _e)\n"
    )


def remove_entries_script(entries: Iterable[str]) -> str:
    """Recursively remove the named top-level *entries* from the device root.

    Args:
        entries: Top-level names (no leading slash) to rmtree.
    """
    listed = ", ".join(repr(name) for name in entries)
    return _RMTREE_DEF + (
        f"for _n in ({listed},):\n"
        "    _rm(_n)\n"
    )


def delete_files_script(paths: list[str]) -> str:
    """Delete *paths* then reap every directory left empty.

    ``repr(paths)`` round-trips a list of strings cleanly into a
    Python literal, so no manual escaping is required.  The reap walks the
    whole filesystem bottom-up and ``os.rmdir``-reaps any directory
    that's now empty; dot-prefixed entries are skipped (not ours to
    reap) and ``rmdir`` only removes empties so live packages are
    never touched.

    Args:
        paths: Absolute on-device file paths to remove.
    """
    return (
        "import os\n"
        f"_paths = {paths!r}\n"
        "for _path in _paths:\n"
        "    try:\n"
        "        os.remove(_path)\n"
        "    except OSError:\n"
        "        pass\n"
        "def _reap(p):\n"
        "    try:\n"
        "        entries = os.listdir(p)\n"
        "    except OSError:\n"
        "        return\n"
        "    for name in entries:\n"
        "        if name.startswith('.'):\n"
        "            continue\n"
        "        full = p + '/' + name if p != '/' else '/' + name\n"
        "        try:\n"
        "            stat = os.stat(full)\n"
        "        except OSError:\n"
        "            continue\n"
        "        if stat[0] & 0x4000:\n"
        "            _reap(full)\n"
        "    if p != '/':\n"
        "        try:\n"
        "            if not os.listdir(p):\n"
        "                os.rmdir(p)\n"
        "        except OSError:\n"
        "            pass\n"
        "_reap('/')\n"
    )


#: Remove ``main.py`` / ``code.py`` and confirm they are gone, all on
#: the device in one round trip: re-``stat`` after ``os.remove`` so a
#: still-present entrypoint raises *on the device* and surfaces loud.
CLEAR_ENTRYPOINTS_SCRIPT: str = (
    "import os\n"
    "for _p in ('main.py', 'code.py'):\n"
    "    try:\n"
    "        os.remove(_p)\n"
    "    except OSError:\n"
    "        pass\n"
    "    try:\n"
    "        os.stat(_p)\n"
    "        raise RuntimeError('entrypoint still present: ' + _p)\n"
    "    except OSError:\n"
    "        pass\n"
)


#: Implements the MicroPython half of the wipe_filesystem contract
#: documented on :meth:`TransportProtocol.wipe_filesystem`.
#:
#: Substrate-dispatched: each MicroPython port exposes its flash /
#: data partition through a different module.  The dispatch covers
#: rp2 and esp32; other ports raise ``RuntimeError`` so the failure
#: has a name instead of surfacing as "mkfs got no block device."
#: (CircuitPython's half is a ``storage.erase_filesystem()`` one-liner
#: and stays inline in its transport.)
WIPE_FILESYSTEM_SCRIPT: str = (
    "import os, sys, machine\n"
    "if sys.platform == 'rp2':\n"
    "    import rp2\n"
    "    _block_dev = rp2.Flash()\n"
    "elif sys.platform == 'esp32':\n"
    "    import esp32\n"
    "    _block_dev = esp32.Partition.find("
    "esp32.Partition.TYPE_DATA, label='vfs')[0]\n"
    "else:\n"
    "    raise RuntimeError("
    "'chumicro_deploy.wipe_filesystem: unsupported MicroPython "
    "platform ' + sys.platform)\n"
    "try:\n"
    "    os.umount('/')\n"
    "except OSError:\n"
    "    pass\n"
    "os.VfsLfs2.mkfs(_block_dev)\n"
    "machine.soft_reset()\n"
)
