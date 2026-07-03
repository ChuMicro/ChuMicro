"""Crash-safe text writes for user-owned workspace files.

``secrets.toml`` holds the user's only copy of wifi / MQTT / API
credentials (gitignored, so not recoverable from version control).  A
plain ``Path.write_text`` truncates the target before writing, so a
crash, kill, or full disk between the truncate and the final write can
leave that file empty.  :func:`atomic_write_text` writes a temp file in
the same directory and ``os.replace``\\ s it onto the target, an atomic
rename on POSIX: the target is either its old bytes or the new bytes,
never a truncated in-between.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* via a same-directory temp file + rename.

    When *path* already exists its permission bits are copied onto the
    replacement, since a fresh temp file is mode 0600 and the target
    (for example a mode-0644 ``secrets.toml``) should keep its own bits.
    On a failed write or rename the temp file is removed and the error
    re-raised, so a failure leaves neither a truncated target nor litter.
    """
    try:
        existing_mode: int | None = path.stat().st_mode
    except FileNotFoundError:
        existing_mode = None
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            handle.write(text)
        if existing_mode is not None:
            os.chmod(temp_path, existing_mode)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
