"""Host-side runtime for ChuMicro project workspaces.

Combines:

* **Config merge** (Decisions 0035 + 0057) — workspace defaults +
  per-developer ``workspace.local.yml`` overlay + per-project config
  + optional per-project ``config.local.<suffix>`` overlay →
  ``/runtime_config.msgpack``.  Pure structural deep-merge; no
  ``!secret`` marker (Decision 0057 retired the indirection).
* **Deploy integration** — :class:`WithRuntimeConfig` plus
  :func:`project_directory_source` / :func:`project_import_graph_source`
  / :func:`project_boot_source` compose with ``chumicro-deploy``'s
  ``FileSource``\\ s so a single ``Deployer.deploy(...)`` call ships
  app code + the merged config + (optional) boot shim in one shot.
* **``devices.yml`` round-trip** — three-zone writer (Decision 0029 §9).
* **Onboarding** — board-state detection, firmware URL derivation
  (CP S3 listing + MP curated machine→BOARD map).
* **Init / update** (Decision 0038) — clone the canonical workspace
  template repo and re-flow tool-owned files.
* **CLI dispatch** — :func:`chumicro_workspace.cli.main` powers the
  ``chumicro-workspace`` entry-point and the workspace ``run.py`` shim.

Public API::

    from chumicro_workspace import (
        build_runtime_config,        # read all sources, merge, write msgpack
        compose_runtime_config,      # same as above without the msgpack write
        merge_configs,               # deep per-key merge of two or more dicts
        read_workspace_yaml,         # parse workspace.yml -> defaults dict
        read_project_config,           # parse projects/<name>/config.{toml,yml,yaml}
        write_runtime_config,        # write merged dict to msgpack at given path
        WithRuntimeConfig,           # FileSource decorator that injects the msgpack
        project_directory_source,      # convenience: DirectorySource + WithRuntimeConfig
        find_project_config,           # locate config.toml/.yml/.yaml under a project dir
        RUNTIME_CONFIG_DEVICE_PATH,  # canonical on-device path (Decision 0035 §8)
        GENERATED_DIRNAME,           # canonical host-side _generated/ dir name
        WorkspaceConfigError,        # YAML/TOML top-level shape malformed
        read_workspace_local_yml_starter,  # canonical workspace.local.yml content
    )

Workbench-only — runs on CPython only; never lands on a
microcontroller.  Workbench tools and scripts (the workspace's
``run.py`` shim) consume this package; the on-device side is
``chumicro-config`` (Decision 0036).
"""

from chumicro_deploy.config.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DevicesYamlError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    list_device_ids,
    load_devices,
    rename_device,
    set_runtime_default,
    update_device_address,
    update_device_hardware,
)
from chumicro_deploy.firmware_url import (
    MICROPYTHON_BOARD_BY_MACHINE,
    UnresolvedFirmwareError,
    derive_firmware_url,
    latest_circuitpython_url,
    latest_circuitpython_version,
    latest_micropython_url,
    list_circuitpython_versions,
    list_micropython_builds,
    micropython_board_for_machine,
)

from chumicro_workspace.boot_shim import (
    BOOT_MODULE_DEVICE_PATH,
    PROJECTS_PACKAGE_INIT_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    boot_shim_files,
    build_active_py,
    load_workspace_runtime_payload,
    project_boot_source,
    project_boot_with_import_graph_source,
)
from chumicro_workspace.config_manifest import (
    ConfigManifest,
    ConfigManifestError,
    SectionManifest,
    aggregate_manifests,
    find_library_roots,
    read_manifest,
    validate_runtime_config,
)
from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
    find_project_config,
    project_directory_source,
)
from chumicro_workspace.deploy_targets import read_deploy_targets
from chumicro_workspace.devices_yml_starter import read_devices_yml_starter
from chumicro_workspace.import_graph import (
    build_search_paths,
    project_import_graph_source,
    read_library_sources,
)
from chumicro_workspace.loaders import (
    WorkspaceConfigError,
    read_project_config,
    read_workspace_yaml,
)
from chumicro_workspace.merge import merge_configs
from chumicro_workspace.onboarding import (
    BoardState,
    OnboardingDiagnosis,
    detect_board_state,
    find_uf2_drive,
)
from chumicro_workspace.pipeline import (
    build_runtime_config,
    compose_runtime_config,
)
from chumicro_workspace.workspace_local_yml_starter import (
    read_workspace_local_yml_starter,
)
from chumicro_workspace.writer import write_runtime_config

__all__ = [
    "BOOT_MODULE_DEVICE_PATH",
    "GENERATED_DIRNAME",
    "MICROPYTHON_BOARD_BY_MACHINE",
    "RUNTIME_CONFIG_DEVICE_PATH",
    "SHIM_ENTRYPOINT_SOURCE",
    "PROJECTS_PACKAGE_INIT_DEVICE_PATH",
    "BoardState",
    "ConfigManifest",
    "ConfigManifestError",
    "DeviceAlreadyExistsError",
    "DeviceNotFoundError",
    "DevicesYamlError",
    "HardwareOverwriteError",
    "OnboardingDiagnosis",
    "SectionManifest",
    "UnresolvedFirmwareError",
    "WithRuntimeConfig",
    "WorkspaceConfigError",
    "add_device",
    "aggregate_manifests",
    "boot_shim_files",
    "build_active_py",
    "build_runtime_config",
    "build_search_paths",
    "compose_runtime_config",
    "derive_firmware_url",
    "detect_board_state",
    "dump_devices",
    "find_device",
    "find_library_roots",
    "find_project_config",
    "find_uf2_drive",
    "latest_circuitpython_url",
    "latest_circuitpython_version",
    "latest_micropython_url",
    "list_circuitpython_versions",
    "list_device_ids",
    "list_micropython_builds",
    "load_devices",
    "load_workspace_runtime_payload",
    "merge_configs",
    "micropython_board_for_machine",
    "read_deploy_targets",
    "read_devices_yml_starter",
    "read_library_sources",
    "read_manifest",
    "read_project_config",
    "read_workspace_local_yml_starter",
    "read_workspace_yaml",
    "rename_device",
    "set_runtime_default",
    "project_boot_source",
    "project_boot_with_import_graph_source",
    "project_directory_source",
    "project_import_graph_source",
    "update_device_address",
    "update_device_hardware",
    "validate_runtime_config",
    "write_runtime_config",
]
