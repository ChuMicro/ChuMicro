"""IDE configuration generation (PyCharm and VS Code/Pyright).

Regenerates source-root configurations, run/task configurations, and Pyright
paths so libraries are importable in the IDE alongside editable installs.
See ``plans/decisions/0012-ide-type-stubs.md``.

This module is idempotent — running it multiple times produces the same
output.  It preserves user settings (e.g. PyCharm SDK selection,
VS Code settings outside ``extraPaths``) while overwriting only the
managed sections.

Called via ``python scripts/run.py sync-ide`` or automatically after
``python scripts/run.py setup`` and ``python scripts/run.py new-library``.
"""

from __future__ import annotations

import json

from shared import load_template
from workspace import ROOT, discover_package_dirs, discover_source_roots

# ---------------------------------------------------------------------------
# Managed task definitions — shared between PyCharm and VS Code
# ---------------------------------------------------------------------------
# Each entry: (display_name, script_path, parameters, vscode_group).
# script_path is relative to the project root.  sync-ide overwrites
# both PyCharm run configurations and VS Code tasks from this single list
# so the two IDEs always stay in sync.

_TASKS: list[tuple[str, str, str, str]] = [
    ("Build", "scripts/run.py", "build", "build"),
    ("Check API", "scripts/run.py", "check-api", "build"),
    ("Check Version", "scripts/run.py", "check-version", "build"),
    ("CircuitPython Compatibility", "scripts/run.py", "test-circuitpython-compatibility", "test"),
    ("Docs", "scripts/run.py", "docs --all", "build"),
    ("Docs Preview", "scripts/run.py", "docs-preview --all", "build"),
    ("Lint", "scripts/run.py", "lint", "build"),
    ("MicroPython Compatibility", "scripts/run.py", "test-micropython-compatibility", "test"),
    ("Preflight", "scripts/run.py", "preflight", "build"),
    ("Prepare Workspace", "scripts/prepare_workspace.py", "", "build"),
    ("Runtime Matrix", "scripts/run.py", "test-runtime-matrix", "test"),
    ("Setup", "scripts/run.py", "setup", "build"),
    ("Test", "scripts/run.py", "test --all", "test"),
    ("Test Everything", "scripts/run.py", "test-everything", "test"),
    ("Test Device", "scripts/run.py", "test-device", "test"),
    ("Test Scripts", "scripts/run.py", "test-scripts", "test"),
    ("Verify Examples", "scripts/run.py", "verify-examples --all", "test"),
]

#: The task that becomes the default build command (Ctrl+Shift+B in VS Code).
_DEFAULT_BUILD_TASK = "Preflight"

# ---------------------------------------------------------------------------
# PyCharm run configurations
# ---------------------------------------------------------------------------


def _config_filename(name: str) -> str:
    """Derive the XML filename from a run configuration display name.

    Args:
        name: Display name (e.g. ``"Lint"``).
    """
    return f"{name.replace(' ', '_')}.xml"


def _sync_run_configurations() -> None:
    """Regenerate PyCharm run configurations from the managed task list.

    Writes one XML file per entry in :data:`_TASKS`.  Removes stale
    managed configurations that no longer appear in the list.
    """
    run_config_dir = ROOT / ".idea" / "runConfigurations"
    run_config_dir.mkdir(parents=True, exist_ok=True)

    template = load_template("run_config.xml.template")

    managed_filenames: set[str] = set()
    for name, script, parameters, _group in _TASKS:
        filename = _config_filename(name)
        managed_filenames.add(filename)
        content = template.format(
            name=name, script=script, parameters=parameters,
        )
        (run_config_dir / filename).write_text(content)

    # Remove stale configurations that were previously managed but dropped
    # from the list.  Only delete files whose name matches the managed
    # naming pattern.  The heuristic: a file is "managed" if every
    # underscore-separated part of its stem starts with an uppercase letter
    # (e.g. ``CircuitPython_Compatibility.xml``).  User-created configs
    # (e.g. ``my_debug_run.xml``) won't match and are left untouched.
    for existing in sorted(run_config_dir.iterdir()):
        if existing.suffix == ".xml" and existing.name not in managed_filenames:
            parts = existing.stem.split("_")
            if all(part and part[0].isupper() for part in parts):
                existing.unlink()

    print(f"  Updated .idea/runConfigurations/ ({len(_TASKS)} configurations)")

# ---------------------------------------------------------------------------
# VS Code tasks and settings
# ---------------------------------------------------------------------------


def _sync_vscode_tasks() -> None:
    """Regenerate ``.vscode/tasks.json`` from the managed task list."""
    vscode_dir = ROOT / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for name, script, parameters, group in _TASKS:
        args = [script]
        if parameters:
            args.extend(parameters.split())

        # Preflight is the default build task (Ctrl+Shift+B).
        if name == _DEFAULT_BUILD_TASK:
            task_group: dict | str = {"kind": group, "isDefault": True}
        else:
            task_group = group

        tasks.append({
            "label": name,
            "type": "shell",
            "command": "python",
            "args": args,
            "group": task_group,
            "presentation": {"reveal": "always", "panel": "shared"},
        })

    content = {
        "//": (
            "Managed by scripts/ide_sync.py — regenerated on every "
            "`python scripts/run.py setup` and `new-library` run. "
            "Edits to this file will be lost. Add personal tasks to "
            "a separate config or extend via VS Code user tasks."
        ),
        "version": "2.0.0",
        "tasks": tasks,
    }
    tasks_file = vscode_dir / "tasks.json"
    tasks_file.write_text(json.dumps(content, indent=4) + "\n")
    print(f"  Updated .vscode/tasks.json ({len(tasks)} tasks)")


def _sync_vscode_settings() -> None:
    """Sync ``python.analysis.extraPaths`` in ``.vscode/settings.json``.

    Preserves all existing user settings; only overwrites the extraPaths
    key so Pylance resolves library imports the same way pyrightconfig
    does.
    """
    vscode_dir = ROOT / ".vscode"
    settings_file = vscode_dir / "settings.json"

    if settings_file.exists():
        settings = json.loads(settings_file.read_text())
    else:
        settings = {}

    settings["python.analysis.extraPaths"] = [
        str(source_dir.relative_to(ROOT)) for source_dir in discover_source_roots()
    ] + ["scripts"]

    settings_file.write_text(json.dumps(settings, indent=4) + "\n")
    print("  Updated .vscode/settings.json")


def _sync_pycharm_iml() -> None:
    """Regenerate .idea/chumicro.iml source roots from the workspace structure.

    Also writes a sibling ``.idea/libraries/embedded_stubs.xml`` that
    registers ``typings/embedded-stubs/`` as an external library so
    PyCharm indexes the CircuitPython / MicroPython type stubs for
    autocomplete in library code without marking the directory as a
    project source root (which would risk shadowing stdlib stubs for
    the CPython task-runner code).  The ``.iml`` references that
    library via ``<orderEntry type="library">`` so PyCharm loads it as
    part of the project's classpath.
    """
    iml_file = ROOT / ".idea" / "chumicro.iml"

    # Preserve the existing SDK reference so users keep their interpreter
    # setting across regenerations.
    jdk_line = ""
    if iml_file.exists():
        for line in iml_file.read_text().splitlines():
            if 'type="jdk"' in line:
                jdk_line = line
                break

    source_lines: list[str] = []
    for package_dir in discover_package_dirs():
        relative_path = package_dir.relative_to(ROOT)
        for subdir, is_test in [
            ("src", "false"),
            ("tests", "true"),
            ("functional_tests", "true"),
        ]:
            if (package_dir / subdir).is_dir():
                source_lines.append(
                    f'      <sourceFolder url="file://$MODULE_DIR$/{relative_path}/{subdir}"'
                    f' isTestSource="{is_test}" />'
                )

    source_lines.append(
        '      <sourceFolder url="file://$MODULE_DIR$/scripts" isTestSource="false" />'
    )
    if (ROOT / "scripts" / "tests").is_dir():
        source_lines.append(
            '      <sourceFolder url="file://$MODULE_DIR$/scripts/tests" isTestSource="true" />'
        )

    sources = "\n".join(source_lines)
    jdk_entry = f"\n{jdk_line}" if jdk_line else ""
    content = load_template("chumicro.iml.template").format(
        sources=sources, jdk=jdk_entry,
    )

    iml_file.parent.mkdir(parents=True, exist_ok=True)
    iml_file.write_text(content)
    print(f"  Updated {iml_file.relative_to(ROOT)}")

    _sync_pycharm_embedded_stubs_library()


def _sync_pycharm_embedded_stubs_library() -> None:
    """Write the ``.idea/libraries/embedded_stubs.xml`` library definition.

    The library registers ``typings/embedded-stubs/`` as an
    external-library classpath entry so PyCharm's on-device module
    autocomplete (``time.ticks_ms``, ``gc.mem_free``, ``board.*``,
    ``busio.*``, etc.) picks up the MicroPython and CircuitPython
    stubs.  PyCharm's bundled typeshed stubs still take precedence for
    stdlib modules, so the CPython ``time.perf_counter()`` calls in
    ``scripts/`` continue to resolve against the real stdlib.  This
    mirrors pyright's ``executionEnvironments`` split but works under
    PyCharm's own type inference.
    """
    library_dir = ROOT / ".idea" / "libraries"
    library_dir.mkdir(parents=True, exist_ok=True)
    library_file = library_dir / "embedded_stubs.xml"
    library_file.write_text(
        '<component name="libraryTable">\n'
        '  <library name="embedded-stubs">\n'
        "    <CLASSES>\n"
        '      <root url="file://$PROJECT_DIR$/typings/embedded-stubs" />\n'
        "    </CLASSES>\n"
        "    <JAVADOC />\n"
        "    <SOURCES />\n"
        "  </library>\n"
        "</component>\n",
    )
    print(f"  Updated {library_file.relative_to(ROOT)}")


def _sync_pyrightconfig() -> None:
    """Regenerate pyrightconfig.json extraPaths from the workspace structure.

    ``extraPaths`` holds the union of every source root plus ``scripts``
    so imports resolve workspace-wide.

    ``executionEnvironments`` carves out the embedded-runtime stubs
    (``typings/embedded-stubs/``) so pyright applies them *only* to
    ``libraries/`` and ``support/test_harness/`` — code that actually
    targets CircuitPython / MicroPython.  Under ``scripts/`` and the
    rest of ``support/`` (CPython-only orchestration), the stubs are
    excluded so their top-level ``time.pyi`` / ``gc.pyi`` / ``sys.pyi``
    files don't shadow stdlib stubs.
    """
    config_file = ROOT / "pyrightconfig.json"

    # Preserve any existing user settings; only overwrite extraPaths +
    # executionEnvironments.
    if config_file.exists():
        config = json.loads(config_file.read_text())
    else:
        config = {}

    source_paths = [
        str(source_dir.relative_to(ROOT)) for source_dir in discover_source_roots()
    ] + ["scripts"]

    config["extraPaths"] = source_paths
    config["executionEnvironments"] = [
        # Library and on-device harness code — include the embedded stubs
        # so `time.ticks_ms`, `gc.mem_free`, etc. resolve.
        {
            "root": "libraries",
            "extraPaths": ["typings/embedded-stubs", *source_paths],
        },
        {
            "root": "support/test_harness",
            "extraPaths": ["typings/embedded-stubs", *source_paths],
        },
        # Everything else (scripts, support orchestration) — stdlib
        # only, no embedded stubs.
        {
            "root": ".",
            "extraPaths": source_paths,
        },
    ]

    config_file.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  Updated {config_file.relative_to(ROOT)}")


def sync_ide() -> int:
    """Regenerate IDE configuration files from the workspace structure."""
    _sync_pycharm_iml()
    _sync_run_configurations()
    _sync_pyrightconfig()
    _sync_vscode_tasks()
    _sync_vscode_settings()
    return 0
