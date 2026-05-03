"""my_template — example third-party package using chumicro-deploy.

Ships a custom :class:`FileSource` that reads a nonstandard project
layout (``project/source/*.py`` + ``project/helpers/*.py`` + a
manifest at ``project/deploy.json``).  The only chumicro dependency
is :mod:`chumicro_deploy` — nothing from the ChuMicro mono repo
leaks into this template.
"""

from __future__ import annotations

import json
from pathlib import Path


class CustomLayoutFileSource:
    """FileSource for this template's ``project/`` tree.

    Reads ``project/deploy.json`` which has the shape::

        {
            "entrypoint": "/code.py",
            "layout": {
                "/code.py": "source/app.py",
                "/lib/greeter.py": "helpers/greeter.py"
            }
        }

    Keys are on-device paths; values are file paths relative to
    the template root.  Non-chumicro layout on purpose — the
    important project is that
    :class:`chumicro_deploy.sources.FileSource` is structural and
    accepts any ``files()`` + ``entrypoint()`` duck type.
    """

    def __init__(self, template_root: Path) -> None:
        self._template_root = template_root
        manifest_path = template_root / "project" / "deploy.json"
        manifest = json.loads(manifest_path.read_text())
        self._entrypoint = manifest["entrypoint"]
        self._layout: dict[str, str] = manifest["layout"]

    def files(self) -> dict[str, bytes]:
        return {
            device_path: (self._template_root / source_relative).read_bytes()
            for device_path, source_relative in self._layout.items()
        }

    def entrypoint(self) -> str:
        return self._entrypoint
