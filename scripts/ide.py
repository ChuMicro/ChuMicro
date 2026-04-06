"""IDE configuration generation (PyCharm and VS Code/Pyright).

Regenerates source-root configs, run/task configurations, and Pyright
paths so libraries are importable in the IDE without ``pip install -e``.
See ``plans/decisions/0012-ide-type-stubs.md``.
"""

from __future__ import annotations

import json

from discovery import ROOT, discover_package_dirs, discover_source_roots

# ---------------------------------------------------------------------------
# Managed task definitions — shared between PyCharm and VS Code
# ---------------------------------------------------------------------------
# Each entry: (display_name, script_path, parameters, vscode_group).
# script_path is relative to the project root.  sync-ide overwrites
# both PyCharm run configs and VS Code tasks from this single list.

_TASKS: list[tuple[str, str, str, str]] = [
    ("Build", "scripts/run.py", "build", "build"),
    ("Check API", "scripts/run.py", "check-api", "build"),
    ("Check Version", "scripts/run.py", "check-version", "build"),
    ("CircuitPython Compat", "scripts/run.py", "test-circuitpython-compatibility", "test"),
    ("Docs", "scripts/run.py", "docs --all", "build"),
    ("Lint", "scripts/run.py", "lint", "build"),
    ("MicroPython Compat", "scripts/run.py", "test-micropython-compatibility", "test"),
    ("Preflight", "scripts/run.py", "preflight", "build"),
    ("Prepare Workspace", "scripts/prepare_workspace.py", "", "build"),
    ("Runtime Matrix", "scripts/run.py", "test-runtime-matrix", "test"),
    ("Setup", "scripts/run.py", "setup", "build"),
    ("Test", "scripts/run.py", "test --all", "test"),
    ("Verify Examples", "scripts/run.py", "verify-examples --all", "test"),
]

#: The task that becomes the default build command (Ctrl+Shift+B in VS Code).
_DEFAULT_BUILD_TASK = "Preflight"

# ---------------------------------------------------------------------------
# PyCharm run configurations
# ---------------------------------------------------------------------------

_RUN_CONFIG_TEMPLATE = """\
<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="{name}" type="PythonConfigurationType" factoryName="Python">
    <module name="chumicro" />
    <option name="SCRIPT_NAME" value="$PROJECT_DIR$/{script}" />
    <option name="PARAMETERS" value="{parameters}" />
    <option name="WORKING_DIRECTORY" value="$PROJECT_DIR$" />
    <method v="2" />
  </configuration>
</component>
"""


def _config_filename(name: str) -> str:
    """Derive the XML filename from a run configuration display name."""
    return f"{name.replace(' ', '_')}.xml"


def _sync_run_configurations() -> None:
    """Regenerate PyCharm run configurations from the managed task list.

    Writes one XML file per entry in :data:`_TASKS`.  Removes stale
    managed configs that no longer appear in the list.
    """
    rc_dir = ROOT / ".idea" / "runConfigurations"
    rc_dir.mkdir(parents=True, exist_ok=True)

    managed_filenames: set[str] = set()
    for name, script, parameters, _group in _TASKS:
        filename = _config_filename(name)
        managed_filenames.add(filename)
        content = _RUN_CONFIG_TEMPLATE.format(
            name=name, script=script, parameters=parameters,
        )
        (rc_dir / filename).write_text(content)

    # Remove stale configs that were previously managed but dropped from
    # the list.  Only delete files whose name matches the managed naming
    # pattern (Name_With_Underscores.xml) and that are NOT in the current
    # managed set.  This avoids touching user-created configs.
    for existing in sorted(rc_dir.iterdir()):
        if existing.suffix == ".xml" and existing.name not in managed_filenames:
            stem = existing.stem
            if stem == stem.replace(" ", "_").title().replace(" ", "_"):
                existing.unlink()

    print(f"  Updated .idea/runConfigurations/ ({len(_TASKS)} configs)")

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

    content = {"version": "2.0.0", "tasks": tasks}
    tasks_path = vscode_dir / "tasks.json"
    tasks_path.write_text(json.dumps(content, indent=4) + "\n")
    print(f"  Updated .vscode/tasks.json ({len(tasks)} tasks)")


def _sync_vscode_settings() -> None:
    """Sync ``python.analysis.extraPaths`` in ``.vscode/settings.json``.

    Preserves all existing user settings; only overwrites the extraPaths
    key so Pylance resolves library imports the same way pyrightconfig
    does.
    """
    vscode_dir = ROOT / ".vscode"
    settings_path = vscode_dir / "settings.json"

    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    settings["python.analysis.extraPaths"] = [
        str(r.relative_to(ROOT)) for r in discover_source_roots()
    ]

    settings_path.write_text(json.dumps(settings, indent=4) + "\n")
    print("  Updated .vscode/settings.json")


def _sync_pycharm_iml() -> None:
    """Regenerate .idea/chumicro.iml source roots from the workspace structure."""
    iml_path = ROOT / ".idea" / "chumicro.iml"

    # Preserve the existing SDK reference so users keep their interpreter
    # setting across regenerations.  PyCharm stores the project SDK as a
    # line containing type="jdk" (its internal name for the Python
    # interpreter entry).  We scan for it with text search rather than
    # XML parsing to avoid adding a dependency on lxml/ElementTree for
    # this single line.  Losing this entry would reset the user's
    # interpreter selection in the IDE.
    jdk_line = ""
    if iml_path.exists():
        for line in iml_path.read_text().splitlines():
            if 'type="jdk"' in line:
                jdk_line = line
                break

    source_lines: list[str] = []
    for pkg_dir in discover_package_dirs():
        rel = pkg_dir.relative_to(ROOT)
        for subdir, is_test in [
            ("src", "false"),
            ("tests", "true"),
            ("functional_tests", "true"),
        ]:
            if (pkg_dir / subdir).is_dir():
                source_lines.append(
                    f'      <sourceFolder url="file://$MODULE_DIR$/{rel}/{subdir}"'
                    f' isTestSource="{is_test}" />'
                )


    sources = "\n".join(source_lines)
    jdk_entry = f"\n{jdk_line}" if jdk_line else ""
    # Two-phase interpolation: the template uses f-string for {sources}
    # but defers {jdk} to .format() because the XML content contains
    # literal curly braces that would conflict with f-string syntax.
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<module type="PYTHON_MODULE" version="4">\n'
        '  <component name="NewModuleRootManager">\n'
        '    <content url="file://$MODULE_DIR$">\n'
        f"{sources}\n"
        '      <excludeFolder url="file://$MODULE_DIR$/.venv" />\n'
        '      <excludeFolder url="file://$MODULE_DIR$/.tools" />\n'
        "    </content>{jdk}\n"
        '    <orderEntry type="sourceFolder" forTests="false" />\n'
        "  </component>\n"
        "</module>\n"
    ).format(jdk=jdk_entry)

    iml_path.parent.mkdir(parents=True, exist_ok=True)
    iml_path.write_text(content)
    print(f"  Updated {iml_path.relative_to(ROOT)}")


def _sync_pyrightconfig() -> None:
    """Regenerate pyrightconfig.json extraPaths from the workspace structure."""
    config_path = ROOT / "pyrightconfig.json"

    # Preserve any existing user settings; only overwrite extraPaths.
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {}

    config["extraPaths"] = [
        str(r.relative_to(ROOT)) for r in discover_source_roots()
    ]

    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  Updated {config_path.relative_to(ROOT)}")


def sync_ide() -> int:
    """Regenerate IDE configuration files from the workspace structure."""
    _sync_pycharm_iml()
    _sync_run_configurations()
    _sync_pyrightconfig()
    _sync_vscode_tasks()
    _sync_vscode_settings()
    return 0

