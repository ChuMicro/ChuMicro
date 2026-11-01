# Contributor Cheat Sheet

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

[CONTRIBUTING § Setting up](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up) walks first-time setup, and [Your first change](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#your-first-change-a-worked-example) walks each step of the workflow below.

<br clear="left">

## Workflow (every change)

```bash
git checkout main && git pull upstream main && git push origin main
git checkout -b fix/my-change
# ... make changes ...
pytest libraries/<name>/tests/        # fast check while you work
python scripts/run.py preflight       # last line must start "Preflight passed."
git add <changed files> && git commit
git push -u origin fix/my-change      # then open the PR on GitHub
```

## The rules

1. **Run preflight before every commit**, docs-only commits included. ([The development loop](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#the-development-loop))
2. **Spell names out.** ([Style Guide § Naming](style-guide.md#naming))
3. **Share the one loop, with no `async` or `await`.** ([Style Guide § Cooperative concurrency](style-guide.md#cooperative-concurrency))
4. **Take hardware through the constructor.** ([Why the code looks the way it does](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#why-the-code-looks-the-way-it-does))
5. **Bump `VERSION` once per PR when users would see a change.** ([Releases § When to bump VERSION](releases.md#when-to-bump-version))
6. **Give every public function a docstring**, with the types on the signature. ([Style Guide § Docstrings](style-guide.md#docstrings))
7. **Build strings with f-strings.** ([Style Guide § String formatting](style-guide.md#string-formatting))
8. **Keep every example running** in a top-level `while True:` loop. ([Style Guide § Examples and demos](style-guide.md#examples-and-demos))
9. **Write the clear version first.** Memory tricks wait for a measurement. ([Style Guide § Memory patterns](style-guide.md#memory-patterns-library-code-only))
10. **Update the docs your change made wrong, in the same PR.** A renamed function means its README, guide, and examples change too.

## Common commands

### Every PR

| What | Command |
|---|---|
| Run everything CI will run | `python scripts/run.py preflight` |
| Lint only (ruff plus the project's own rules) | `python scripts/run.py lint` |
| Refresh installs and IDE config after a `git pull` | `python scripts/run.py setup` |
| Scaffold a new device library | `python scripts/run.py new-library my_sensor` |
| Scaffold a laptop-only workbench tool | `python scripts/run.py new-library --workbench my_tool` |

### Testing

| What | Command |
|---|---|
| Test one library | `pytest libraries/timing/tests/` |
| Filter by test name | `pytest libraries/timing/tests/ -k deadline` |
| Stop on first failure, verbose | `pytest libraries/timing/tests/ -k deadline -x -v` |
| Test a single file | `pytest libraries/timing/tests/test_deadline.py` |
| Changed libraries, with the coverage gate | `python scripts/run.py test` |
| Every package, with the coverage gate | `python scripts/run.py test --all` |
| One library, with the coverage gate | `python scripts/run.py test --libraries timing` |
| One test, through the gated runner | `python scripts/run.py test -k timing/test_deadline/rate_fires --no-cov` |
| Browse coverage line by line ([details](style-guide.md#browsing-coverage)) | `python -m coverage html` |
| Test the `scripts/` tooling itself | `python scripts/run.py test-scripts` |
| Check examples parse and import | `python scripts/run.py verify-examples --libraries timing` |

### Cross-runtime testing

[CONTRIBUTING § Testing](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#testing) explains the *unix ports*.

| What | Command |
|---|---|
| Build the MicroPython unix port (once, slow) | `python scripts/run.py prepare-micropython` |
| Build the CircuitPython unix port (once, slow) | `python scripts/run.py prepare-circuitpython` |
| Build only the `mpy-cross` compilers | `python scripts/run.py prepare-mpy-cross` |
| Unit tests on the MicroPython unix port | `pytest libraries/ --target unix-port --runtime micropython` |
| Unit tests on the CircuitPython unix port | `pytest libraries/ --target unix-port --runtime circuitpython` |
| Unit tests on both unix ports | `pytest libraries/ --target unix-port --runtime both` |
| One file on one unix port | `pytest libraries/timing/tests/test_deadline.py --target unix-port --runtime micropython` |
| Unit tests on CPython and both unix ports | `python scripts/run.py test-all-runtimes --libraries timing` |

### Device testing

[Device Testing](device-testing.md) explains functional tests, deploy modes, and every flag.

| What | Command |
|---|---|
| Register a board (probes it, writes `devices.yml`) | `python scripts/run.py add-device <id> --address <port>` |
| Functional tests for one library | `python scripts/run.py test-libraries-functional --library timing` |
| Functional tests on both runtimes | `python scripts/run.py test-libraries-functional --runtime both` |
| Functional tests through bare pytest (IDE play buttons) | `pytest libraries/timing/functional_tests/` |
| Every hardware test (libraries, then workbench tools) | `python scripts/run.py test-functional` |
| Hardware tests for one workbench tool | `python scripts/run.py test-workbench-functional --workbench deploy` |
| Unit suite on real boards (the on-device sweep) | `python scripts/run.py test-unit-on-device` |
| On-device sweep, one library | `python scripts/run.py test-unit-on-device --library timing` |
| On-device sweep, fresh interpreter per file (256 KB boards) | `python scripts/run.py test-unit-on-device --per-file` |
| Preflight plus the functional tests | `python scripts/run.py preflight --with-functional` |
| Preflight plus the on-device sweep | `python scripts/run.py preflight --with-device-unit` |
| Run one example on a board | `chumicro-workspace deploy-example timing rate_blink` |
| List every example | `chumicro-workspace deploy-example --list` |
| Wipe a wedged board (last resort, erases its files) | `chumicro-workspace reset-board --device <id> --yes` |

### Docs and publishing

| What | Command |
|---|---|
| Build docs for one library | `python scripts/run.py docs --libraries timing` |
| Preview one library's docs with live reload | `python scripts/run.py docs --libraries timing --serve` |
| Validate a `mip` install against a bundle repo | `python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing` |

## Where things live in a library

[CONTRIBUTING § What you're contributing to](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#what-youre-contributing-to) maps the top-level folders.

| What | Where |
|---|---|
| Library source | `libraries/<name>/src/chumicro_<name>/` |
| Library laptop tests | `libraries/<name>/tests/` |
| Library real-board tests | `libraries/<name>/functional_tests/` |
| Library docs | `libraries/<name>/docs/` |
| Library examples | `libraries/<name>/examples/` |
| Version file | `libraries/<name>/VERSION` |

## When something fails

| What failed | Where the fix is |
|---|---|
| A preflight phase: `lint`, `test` or its coverage gate, `docs`, `check-version`, `check-size`, a unix-port run | [CONTRIBUTING § Reading a failure](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#reading-a-failure) |
| `functional_tests/` say no device is configured | [Device Testing § Troubleshooting](device-testing.md#troubleshooting) |
| `mpremote: cp: ...: No space left on device` mid-deploy | [Device Testing § Wiping a board's filesystem](device-testing.md#wiping-a-boards-filesystem) |
| macOS `CIRCUITPY` drive won't mount, `diskutil list` hangs, flash-mode deploys fail | [CIRCUITPY on macOS](../troubleshooting/macos-circuitpy.md) |
| Anything else | [CONTRIBUTING § When you're stuck](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#when-youre-stuck) |

## Links

- [Full contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md)
- [Style guide](style-guide.md)
- [PR guide](pull-requests.md)
- [Device testing](device-testing.md)
- [Releases and promotion](releases.md)
- [Troubleshooting](../troubleshooting/README.md)
- [Design decisions](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/README.md)
