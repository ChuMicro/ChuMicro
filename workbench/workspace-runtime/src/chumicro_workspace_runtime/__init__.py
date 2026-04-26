"""Host-side runtime for ChuMicro project workspaces.

Phase 4a surface so far:

* **Slice 0 — config-merge core** (Decision 0035): workspace defaults
  + per-thing config + secrets → ``/runtime_config.msgpack``.
* **Slice 1 — deploy integration**: :class:`WithRuntimeConfig` and
  :func:`thing_directory_source` compose with ``chumicro-deploy``'s
  ``FileSource``s so a single ``Deployer.deploy(...)`` call ships
  both the thing's app code and its merged config in one shot.

Subsequent slices add command dispatch, three-zone YAML writer,
onboarding flows, firmware URL derivation, and the import-graph
resolver per ``plans/workstreams/project-workspace.md`` Phase 4a.

Public API::

    from chumicro_workspace_runtime import (
        build_runtime_config,        # read all sources, merge, write msgpack
        merge_configs,               # deep per-key merge of two or more dicts
        resolve_secrets,             # walk a value, replace !secret <name> refs
        read_workspace_yaml,         # parse workspace.yml -> defaults dict
        read_thing_config,           # parse things/<name>/config.{toml,yml,yaml}
        read_secrets_yaml,           # parse secrets.yml -> dict (empty when absent)
        write_runtime_config,        # write merged dict to msgpack at given path
        WithRuntimeConfig,           # FileSource decorator that injects the msgpack
        thing_directory_source,      # convenience: DirectorySource + WithRuntimeConfig
        find_thing_config,           # locate config.toml/.yml/.yaml under a thing dir
        RUNTIME_CONFIG_DEVICE_PATH,  # canonical on-device path (Decision 0035 §8)
        GENERATED_DIRNAME,           # canonical host-side _generated/ dir name
        UnresolvedSecretError,       # !secret <name> resolved against missing key
        WorkspaceConfigError,        # YAML/TOML top-level shape malformed
    )

Workbench-only — runs on CPython only; never lands on a
microcontroller.  Workbench tools and scripts (the workspace's
``run.py`` shim) consume this package; the on-device side is
``chumicro-config`` (Decision 0036).
"""

from chumicro_workspace_runtime.boot_shim import (
    BOOT_MODULE_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    THINGS_PACKAGE_INIT_DEVICE_PATH,
    boot_shim_files,
    build_active_py,
    build_switch_files,
    load_workspace_runtime_payload,
    multi_thing_boot_files,
    multi_thing_boot_source,
    switch_source,
    thing_boot_source,
)
from chumicro_workspace_runtime.deploy_source import (
    GENERATED_DIRNAME,
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
    find_thing_config,
    thing_directory_source,
)
from chumicro_workspace_runtime.devices_yaml import (
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
from chumicro_workspace_runtime.firmware_url import (
    MICROPYTHON_BOARD_BY_MACHINE,
    UnresolvableFirmwareError,
    derive_firmware_url,
    latest_circuitpython_url,
    latest_circuitpython_version,
    latest_micropython_url,
    list_circuitpython_versions,
    list_micropython_builds,
    micropython_board_for_machine,
)
from chumicro_workspace_runtime.import_graph import (
    build_search_paths,
    read_library_sources,
    thing_import_graph_source,
)
from chumicro_workspace_runtime.loaders import (
    WorkspaceConfigError,
    read_secrets_yaml,
    read_thing_config,
    read_workspace_yaml,
)
from chumicro_workspace_runtime.merge import merge_configs
from chumicro_workspace_runtime.onboarding import (
    BoardState,
    OnboardingDiagnosis,
    detect_board_state,
    find_uf2_drive,
)
from chumicro_workspace_runtime.pipeline import build_runtime_config
from chumicro_workspace_runtime.secrets import UnresolvedSecretError, resolve_secrets
from chumicro_workspace_runtime.writer import write_runtime_config

__all__ = [
    "BOOT_MODULE_DEVICE_PATH",
    "GENERATED_DIRNAME",
    "MICROPYTHON_BOARD_BY_MACHINE",
    "RUNTIME_CONFIG_DEVICE_PATH",
    "SHIM_ENTRYPOINT_SOURCE",
    "THINGS_PACKAGE_INIT_DEVICE_PATH",
    "BoardState",
    "DeviceAlreadyExistsError",
    "DeviceNotFoundError",
    "DevicesYamlError",
    "HardwareOverwriteError",
    "OnboardingDiagnosis",
    "UnresolvableFirmwareError",
    "UnresolvedSecretError",
    "WithRuntimeConfig",
    "WorkspaceConfigError",
    "add_device",
    "boot_shim_files",
    "build_active_py",
    "build_runtime_config",
    "build_search_paths",
    "build_switch_files",
    "derive_firmware_url",
    "detect_board_state",
    "dump_devices",
    "find_device",
    "find_thing_config",
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
    "multi_thing_boot_files",
    "multi_thing_boot_source",
    "read_secrets_yaml",
    "read_library_sources",
    "read_thing_config",
    "read_workspace_yaml",
    "rename_device",
    "resolve_secrets",
    "set_runtime_default",
    "switch_source",
    "thing_boot_source",
    "thing_directory_source",
    "thing_import_graph_source",
    "update_device_address",
    "update_device_hardware",
    "write_runtime_config",
]
