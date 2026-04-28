"""Deploy only the files an entrypoint actually imports.

Demonstrates :class:`~chumicro_deploy.ImportGraphSource` — AST-walks
the entrypoint, collects every transitively-imported module that
resolves against the configured search paths, and ships *only those*
files.  Modules that aren't reached stay on disk.

Useful when a project directory carries optional code paths or
multi-board variants and you only want what a particular entrypoint
needs.  ``chumicro-workspace deploy --import-graph`` is the same
primitive applied to a workspace's `things/` tree; this example uses
the bare API directly so the mechanism is visible.

Run from the repo root with a board plugged in::

    .venv/bin/python workbench/deploy/examples/import_graph_deploy.py

The script materialises a small project where the entrypoint only
imports half of the available modules; the deploy then ships exactly
the imported half.  Logs which files made the cut, prints the execute
output, exits zero on success.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from chumicro_deploy import (
    Deployer,
    Device,
    DeviceConfigError,
    DeviceEntry,
    ImportGraphSource,
    Runtime,
    load_device_registry,
)


def _pick_micropython_board(entries: list[DeviceEntry]) -> DeviceEntry | None:
    for entry in entries:
        if entry.runtime == Runtime.MICROPYTHON.value:
            return entry
    return None


def _device_from_entry(entry: DeviceEntry) -> Device:
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="ram",
    )


def _materialise_project(parent: Path) -> tuple[Path, Path]:
    """Build a small project where main imports only some of the modules.

    Returns ``(project_dir, entrypoint_path)``.  The project carries:

    - ``main.py`` (entrypoint) — imports `used_helper`
    - ``used_helper.py`` — imports `deeper_helper`
    - ``deeper_helper.py`` — leaf, no further imports
    - ``orphan.py`` — never imported.  Should NOT ship.
    """
    project = parent / "project"
    project.mkdir()
    (project / "main.py").write_text(
        "import sys\n"
        "from used_helper import compose\n"
        "print(compose(f'hello from {sys.implementation.name}'))\n",
    )
    (project / "used_helper.py").write_text(
        "from deeper_helper import flourish\n"
        "def compose(message):\n"
        "    return flourish(message) + '!'\n",
    )
    (project / "deeper_helper.py").write_text(
        "def flourish(message):\n"
        "    return f'>>> {message} <<<'\n",
    )
    (project / "orphan.py").write_text(
        "raise RuntimeError('orphan module loaded — import-graph leaked')\n",
    )
    return project, project / "main.py"


def main() -> int:
    try:
        entries, _defaults = load_device_registry()
    except (DeviceConfigError, FileNotFoundError, OSError) as error:
        print(f"error: failed to load devices.yml: {error}", file=sys.stderr)
        return 1

    board = _pick_micropython_board(entries)
    if board is None:
        print(
            "error: no MicroPython board in devices.yml.  Add one with "
            "`chumicro-workspace add-device` or hand-edit the file.",
            file=sys.stderr,
        )
        return 1

    print(f"deploying to {board.address}")

    with tempfile.TemporaryDirectory(prefix="chumicro-example-") as tmp:
        project_dir, entrypoint = _materialise_project(Path(tmp))
        source = ImportGraphSource(
            entrypoint=entrypoint,
            search_paths=[project_dir],
            device_entrypoint="/main.py",
        )
        files = source.files()
        print(f"import graph resolved {len(files)} files (orphan.py excluded):")
        for path in sorted(files):
            print(f"  {path}")
        if "/orphan.py" in files:
            print("error: orphan.py made it into the deploy set", file=sys.stderr)
            return 1

        result = Deployer(_device_from_entry(board)).deploy(source)

    if result.execute_output:
        print("--- board output ---")
        print(result.execute_output, end="")
    if not result.success:
        print(f"--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
