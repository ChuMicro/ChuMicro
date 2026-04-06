"""IDE configuration generation (PyCharm and VS Code/Pyright).

Regenerates source-root configs, run configurations, and Pyright paths
so libraries are importable in the IDE without ``pip install -e``.
See ``plans/decisions/0012-ide-type-stubs.md``.
"""

from __future__ import annotations

import json

from discovery import ROOT, discover_package_dirs, discover_source_roots

# ---------------------------------------------------------------------------
# Managed PyCharm run configurations
# ---------------------------------------------------------------------------
# Each entry: (display_name, script_path, parameters).
# script_path is relative to $PROJECT_DIR$.  sync-ide overwrites these
# on every run so they stay in sync with run.py commands.

_RUN_CONFIGS: list[tuple[str, str, str]] = [
    ("Build", "scripts/run.py", "build"),
    ("Check API", "scripts/run.py", "check-api"),
    ("Check Version", "scripts/run.py", "check-version"),
    ("CircuitPython Compat", "scripts/run.py", "test-circuitpython-compatibility"),
    ("Docs", "scripts/run.py", "docs --all"),
    ("Lint", "scripts/run.py", "lint"),
    ("MicroPython Compat", "scripts/run.py", "test-micropython-compatibility"),
    ("Preflight", "scripts/run.py", "preflight"),
    ("Prepare Workspace", "scripts/prepare_workspace.py", ""),
    ("Runtime Matrix", "scripts/run.py", "test-runtime-matrix"),
    ("Setup", "scripts/run.py", "setup"),
    ("Test", "scripts/run.py", "test --all"),
    ("Verify Examples", "scripts/run.py", "verify-examples --all"),
]

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
    """Regenerate PyCharm run configurations from the managed list.

    Writes one XML file per entry in :data:`_RUN_CONFIGS`.  Removes stale
    managed configs that no longer appear in the list.
    """
    rc_dir = ROOT / ".idea" / "runConfigurations"
    rc_dir.mkdir(parents=True, exist_ok=True)

    managed_filenames: set[str] = set()
    for name, script, parameters in _RUN_CONFIGS:
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
            # Safety: only remove if we previously generated it (all our
            # names use Title_Case with underscores — skip anything that
            # looks hand-created, e.g. lowercase or special chars).
            stem = existing.stem
            if stem == stem.replace(" ", "_").title().replace(" ", "_"):
                existing.unlink()

    count = len(_RUN_CONFIGS)
    print(f"  Updated .idea/runConfigurations/ ({count} configs)")


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
    return 0

