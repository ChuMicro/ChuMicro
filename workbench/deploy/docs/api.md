# API Reference

Auto-generated from docstrings via mkdocstrings.  All public names are
re-exported at the package top level via the lazy-attr table in
`chumicro_deploy/__init__.py`; the per-module sections below mirror
the internal layout for readers who want to navigate by source file.

## Device

::: chumicro_deploy.device

## Deployer

::: chumicro_deploy.deployer

## Result types

::: chumicro_deploy.result

## File sources

::: chumicro_deploy.sources

## Probe

::: chumicro_deploy.probe

## Firmware

::: chumicro_deploy.firmware

## Interactive recovery

::: chumicro_deploy.recovery

## macOS FSKit wedge detection

::: chumicro_deploy.macos_fskit

## Host platform compatibility

::: chumicro_deploy.host_platform

## Devices.yml schema and loader registry

The `chumicro_deploy.config` package owns the `devices.yml` schema.
`load_devices_yml` is the built-in loader (registered under the
`"default"` entry-point name); third parties register their own
config formats via the `chumicro_deploy.config_loaders` entry-point
group, and `discover_config_loaders` collects every registered
loader keyed by name.

::: chumicro_deploy.config

::: chumicro_deploy.config.default

## Transport protocol

::: chumicro_deploy.protocol

## MicroPython transport

::: chumicro_deploy.micropython_transport

## CircuitPython transport

::: chumicro_deploy.circuitpython_transport

## CircuitPython bootstrap helpers

::: chumicro_deploy.circuitpython_bootstrap

## Flash drive helpers

::: chumicro_deploy.flash_drive

## Test fakes

::: chumicro_deploy.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · [PyPI](https://pypi.org/project/chumicro-deploy/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
