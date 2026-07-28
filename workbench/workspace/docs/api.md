# API Reference

Auto-generated from docstrings via mkdocstrings.  The package root
keeps a deliberately narrow surface; everything else is imported
from the submodule that owns it, so the sections below are grouped
by source file.

`devices.yml` reading and writing is not here.  That schema belongs
to `chumicro-deploy`, whose
[API reference](https://chumicro.github.io/ChuMicro/deploy/stable/api/)
documents `chumicro_deploy.config.devices_yaml` along with
`derive_firmware_url` and the transports.

## Package root

::: chumicro_workspace

## Workspace layout

::: chumicro_workspace.workspace

## Config merge pipeline

`build_runtime_config` is the whole flow; the four steps below it are
public so callers can compose them directly.

::: chumicro_workspace.pipeline

::: chumicro_workspace.loaders

::: chumicro_workspace.merge

::: chumicro_workspace.flatten

::: chumicro_workspace.writer

## Deploy sources

::: chumicro_workspace.deploy_source

## Boot shim

::: chumicro_workspace.boot_shim

## Import graph

::: chumicro_workspace.import_graph

## Deploy targets

::: chumicro_workspace.deploy_targets

## Board onboarding

::: chumicro_workspace.onboarding

## Firmware support windows

::: chumicro_workspace.firmware_support

## Workspace health

::: chumicro_workspace.health

## Failure hints

::: chumicro_workspace.recovery

## Quality knobs

::: chumicro_workspace.quality

## Library scaffolding

::: chumicro_workspace.scaffold

## Curated libraries

::: chumicro_workspace.library

## Test fakes

::: chumicro_workspace.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · [PyPI](https://pypi.org/project/chumicro-workspace/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
