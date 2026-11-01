# Adding a Workbench Package

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Workbench packages are the laptop-side tools: CPython programs that ship to PyPI and never run on a board. [`workbench/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/) lists each tool and its install command, and [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) records why the workbench sits apart from `libraries/`.

<br clear="left">

## Conventions shared with libraries

A workbench package follows the same per-package conventions as a [device library](new-library.md):

- `pyproject.toml` and a `VERSION` file, following SemVer
- `src/<package_name>/` source layout
- `tests/` meeting the [coverage gate](style-guide.md#coverage-exclusions)
- f-strings, PEP 604/585 annotations ([Decision 0021](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0021-docstring-type-policy.md)), and descriptive names ([Decision 0022](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0022-naming-conventions.md))
- Constructor injection for dependencies, where relevant ([Decision 0010](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0010-library-testability.md))
- `pytest workbench/<name>/tests/` for iteration, `python scripts/run.py test --libraries <name>` for the gated run, and `python scripts/run.py lint` for lint

## Scaffolding

`python scripts/run.py new-library --workbench <name>` scaffolds a workbench package under `workbench/<name>/` from the same templates as a library, then installs it in editable mode and regenerates IDE configs. A workspace outside this repository runs the same scaffolder with `python3 run.py new --workbench <name>`.

## Release lifecycle

A workbench package releases like a library, without the bundle steps:

- [When to bump VERSION](releases.md#when-to-bump-version) applies unchanged, and `check-api` gates API breakage the same way.
- Every `VERSION` bump merged to `main` publishes the package to PyPI under its **experimental** name, such as `chumicro-deploy-experimental`.
- Promotion to **stable** publishes the base name, such as `chumicro-deploy`, through the same `promote.yml` flow libraries use.

## Docs

A workbench package keeps the same `mkdocs.yml` and `docs/` layout as a device library, published as versioned pages at `https://chumicro.com/ChuMicro/<package>/`. Build them locally with `python scripts/run.py docs --libraries <name>`. The docs build and its griffe check treat the package like a library.

## Differences from libraries

- **`functional_tests/` run on the laptop.** A workbench package's `functional_tests/` drive a connected board from the host, as [`workbench/deploy/functional_tests/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy/functional_tests/) does through the public `chumicro_deploy` API. [Device Testing § Run workbench functional tests](device-testing.md#run-workbench-functional-tests) covers running them.
- **Tests run on CPython only.** The `test-micropython` and `test-circuitpython` preflight phases cover `libraries/`.
- **PyPI is the only channel.** Workbench packages skip `.mpy` compilation and stay out of `ChuMicro-Bundle` and `ChuMicro-Bundle-Experimental`, which serve CircuitPython and MicroPython users.
- **Any PyPI dependency works**, such as `pyserial`, `ruamel.yaml`, or `rich`. A workbench package never imports a library package, as [Style Guide § Lint](style-guide.md#lint) describes under `CHU007`.

## Host code with a small device shim

Ship the device shim inside the workbench package, and have the host CLI deploy it. Nobody installs the shim on its own, so it stays payload inside the workbench package.

`chumicro-workspace`, for example, writes a three-line boot shim, `/code.py` or `/main.py`, onto the board at deploy time, from source inside the package. The tool stays one PyPI package with one `VERSION` and no bundle entry.

The on-device piece moves to its own `libraries/` entry only when people need to install it apart from the host CLI.

## See also

- [`workbench/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/): what the workbench is, the current tool list, and install commands
- [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md): full rationale and alternatives
- [Adding a New Library](new-library.md): the parallel guide for device libraries
- [`AGENTS.md`](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md): the repository's trees and the rules agents follow in each
