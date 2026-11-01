# Guide

`chumicro-workspace` runs on your laptop and puts your Python projects on CircuitPython and MicroPython boards.  It registers a board, creates a project, copies the project and the libraries it imports onto the board, and shows what the board prints.

The commands below are written the way a workspace made from the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) runs them: `python3 run.py <command>`.  The template's `run.py` starts `chumicro-workspace` from the workspace's own virtual environment.  Where `chumicro-workspace` is on your `PATH`, after `pip install chumicro-workspace` or in a clone of the ChuMicro repository, `chumicro-workspace <command>` is the same command.

## Before you start

You need a board with CircuitPython or MicroPython on it, a USB cable that carries data, and a workspace made from the workbench template.  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) sets up all three.

## 1. Register the board

Plug the board in and run:

```bash
python3 run.py bootstrap
```

`bootstrap` picks the board's serial port, works out whether the board runs CircuitPython or MicroPython, and records it in `devices.yml`.  With one serial port in sight it uses that port.  With several, it lists them and asks for a number.  It names the board after its model and runtime, such as `raspberry-pi-pico-w-cp`.  A name of your own goes first: `python3 run.py bootstrap back-porch`.  When it finishes, it prints the commands to run next.

The first board registered for each runtime becomes that runtime's default board.  Every command that talks to a board uses the default board.  `--device <id>` picks another, and `python3 run.py devices` lists the registered boards.

`--demo` also sends the board a counting program, so it prints something straight away:

```bash
python3 run.py bootstrap --demo
```

A script or CI job names the board and the port, so nothing waits for an answer:

```bash
python3 run.py bootstrap back-porch --address /dev/cu.usbmodem1101 --non-interactive
```

When the board does not answer, `bootstrap` prints what it found and what to do.  A drive such as `RPI-RP2` in place of a Python prompt means the board sits in its bootloader with no CircuitPython or MicroPython running.  A port that opens with no Python prompt behind it usually needs fresh firmware.  A port that will not open points at the cable or a driver.  [Board not found](https://chumicro.com/ChuMicro/guides/troubleshooting/board-not-found/) and [Getting firmware onto a new board](https://chumicro.com/ChuMicro/guides/troubleshooting/firmware-onto-a-new-board/) walk the fixes.

## 2. Create a project and deploy it

```bash
python3 run.py new blinker
python3 run.py deploy blinker
```

`new` copies `projects/_template/` to `projects/blinker/`.  The copy holds `app.py`, where your code goes inside a function named `run()`, and `project_config.toml` for settings that belong to this project.

`deploy` copies the project onto the board and restarts the board.  The board starts from a `code.py` (`main.py` on MicroPython) that `deploy` generates.  That file imports `app.py` and calls `run()`.  The terminal then shows what the board prints right after the restart.

A project name can be a path.  `new garage/door_open` creates `projects/garage/door_open/`.  `deploy door_open` finds that project by its last part.  With one project in the workspace, `deploy` needs no name at all.  A board runs one project at a time, and the next deploy replaces it.

## 3. Watch the board's output

```bash
python3 run.py deploy blinker --tail 30   # deploy, then show 30 seconds of output
python3 run.py repl --tail 30             # show 30 seconds of output, no deploy
python3 run.py repl                       # type at the board's Python prompt
```

`--tail` streams what the board prints and highlights tracebacks as they scroll past.  It stops after the number of seconds you give, or 30 with no number.  The exit code is non-zero when a traceback shows up, so a script can tell a crash from a clean run.  `--no-fail-on-traceback` turns that check off.  `deploy --tail` follows one board, so it needs one project and one board.

`repl` opens the board's interactive Python prompt, the REPL.  On a terminal it edits each line on your laptop before sending it, keeps your history between sessions, and completes names from the board with Tab.  `:help` lists the prompt's own commands.  Ctrl-X leaves without restarting the board.  `--mode passthrough` sends each key straight to the board, for paste mode.

## 4. Add a library

```bash
python3 run.py library add chumicro_timing
```

`library add` fetches the library's published release into `libraries/chumicro_timing/`, along with every ChuMicro library it depends on, and records each one in the `libraries:` table of `workspace.yml`.

Replace `projects/blinker/app.py` with a loop that uses it:

```python
from chumicro_timing import Rate, ticks_ms


def run():
    tick = Rate(1000, ticks_ms())       # due once a second
    count = 0
    while True:                         # set up once, then loop until the power goes
        now = ticks_ms()
        if tick.due(now):               # is it time yet?
            count += 1
            print("tick", count)
```

Then deploy it and watch:

```bash
python3 run.py deploy blinker --tail 10
```

`deploy` reads the `import` lines in `app.py`, follows them into `libraries/`, and copies every library the project reaches to `/lib/` on the board.  An import it cannot find stops the deploy before anything is copied.  The message names the module, and [Deploy refused for an import](https://chumicro.com/ChuMicro/guides/troubleshooting/deploy-refused-importerror/) covers each case.

The library stays at the version `library add` fetched.  `python3 run.py library list` shows each library's channel and version.  [Libraries in depth](#libraries-in-depth) covers updates, the experimental channel, and removal.

## 5. Keep your WiFi password in secrets.toml

`secrets.toml` sits at the top of the workspace and holds the values every project shares, such as WiFi credentials and the MQTT broker address.  Git ignores it.  `setup` creates it with placeholder values.  Replace them with your own:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

Each project's `project_config.toml` holds the settings for that project alone.  A key set in both files takes the project's value:

```toml
# projects/blinker/project_config.toml
[blink]
period_ms = 250
```

Each deploy merges the two files and copies the result onto the board as `/runtime_config.msgpack`.  On the board, `load_runtime_config()` from the `chumicro_config` library reads it.  Every key arrives under a flat dotted name, so `ssid` in the `[wifi]` table becomes `wifi.ssid`.  Fetch the library, then read the period from the settings:

```bash
python3 run.py library add chumicro_config
```

```python
from chumicro_config import load_runtime_config
from chumicro_timing import Rate, ticks_ms


def run():
    config = load_runtime_config()
    period_ms = config.get("blink.period_ms", 500)   # 500 when no file sets it
    tick = Rate(period_ms, ticks_ms())
    count = 0
    while True:
        now = ticks_ms()
        if tick.due(now):
            count += 1
            print("tick", count)
```

`python3 run.py dump-config blinker` prints the merged settings, as the board receives them, without deploying.  [Wiring WiFi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) lists every key the libraries read.  [Settings in depth](#settings-in-depth) covers the merge rules.

## Workspace layout

```
my-workspace/
├── run.py                 # runs chumicro-workspace from the workspace's virtual environment
├── workspace.yml          # workspace machinery: libraries, deploy_targets, quality, library_sources
├── secrets.toml           # credentials and defaults every project shares
├── devices.yml            # the registered boards
├── quality.toml           # lint and coverage settings for test, lint, and preflight
├── projects/
│   ├── _template/         # new copies this folder
│   ├── blinker/           # one project
│   │   ├── app.py         # def run(): ...
│   │   └── project_config.toml
│   └── garage/
│       └── door_open/     # a nested project
├── shared/                # your own helper modules, imported by bare name
├── libraries/
│   ├── chumicro_timing/   # fetched with library add
│   │   └── src/chumicro_timing/
│   └── gpio/              # created with new gpio --library
│       └── src/gpio/
└── packages/              # third-party modules you copy in yourself
```

`chumicro-workspace` finds the workspace by walking up from the current folder to the first one that holds `workspace.yml`, so every command works from any folder inside it.

The template's `.gitignore` keeps `secrets.toml`, `workspace.yml`, and `devices.yml` out of git.  `secrets.toml` holds real passwords.  The other two hold paths and board ids that differ from one computer to the next.

### Where shared code goes

Every project can import from `shared/`, `libraries/`, and `packages/`.  Pick the folder by the size of the code:

| Code | Folder | Import | Notes |
|---|---|---|---|
| A short helper several projects share | `shared/foo.py` | `from foo import bar` | No tests, no version.  The import uses the bare module name, never `shared.foo`. |
| A library of your own, with tests | `libraries/<name>/`, from `new <name> --library` | `import <name>` | Gets `src/`, `tests/`, `docs/`, `examples/`, `pyproject.toml`, and `VERSION`. |
| A published ChuMicro library | `libraries/chumicro_<name>/`, from `library add chumicro_<name>` | `import chumicro_<name>` | Arrives with the ChuMicro libraries it depends on. |
| A third-party module | `packages/` | `import <name>` | Copy the files in by hand. |

`deploy` looks for an imported module in this order: the project's own folder, any `library_sources:` paths in `workspace.yml`, `shared/`, each `libraries/<name>/src/`, then `packages/`.  A library from `new buttons --library` is importable as `import buttons` from any project with no further setup.

A module at `shared/foo.py` is `from foo import bar`.  The spelling `from shared.foo import bar` stops the deploy with a message that shows the bare-name form.

## Boards and devices.yml

`bootstrap` is `add-device` plus the list of next steps.  The two commands take the same options.  `add-device` suits a second or third board:

```bash
python3 run.py discover                       # list serial ports; run it before and after plugging in
python3 run.py add-device kitchen --address /dev/cu.usbmodem1102 --runtime micropython
python3 run.py probe --device kitchen         # print the runtime, version, model, and unique id
python3 run.py rename --device kitchen kitchen-window
python3 run.py remove-device kitchen-window --yes
```

Without `--runtime`, `add-device` tries CircuitPython and then MicroPython.  `--force` updates an entry that already has the id and keeps your description.  It suits a different board swapped in under the same name.  `reset-device <id> --yes` rebuilds an entry from the connected board and drops the fields you set by hand.

With a default board for each runtime, a command needs `--device <id>`, or `--runtime circuitpython` or `--runtime micropython` to pick that runtime's default.

### Who owns each field

`devices.yml` keeps your comments and field order through every rewrite.  A field's group decides which commands change it:

| Group | Fields | Changed by |
|---|---|---|
| Yours | `id`, `description`, `deploy_mode`, `serial_baudrate` | Your edits.  `rename --device` changes `id`, and `reset-device` clears the other three. |
| Read from the board | `address`, `firmware_version` | `add-device --force`, because a board moves between ports and gets new firmware. |
| Read once | `runtime`, and the `hardware:` block (`uid`, `machine`, `board_id`, `firmware_source`) | `add-device --force` rewrites the `hardware:` block, and `reset-device` rewrites both, because a new unique id usually means a different board. |

When a probe fails, [`detect_board_state`](api.md) sorts the board into one of these states and prints the next step:

- The Python prompt answered, and the board is fine.
- The board shows a UF2 bootloader drive holding `INFO_UF2.TXT`, so it needs firmware.
- The port opened with no Python prompt behind it, so the board needs an `esptool` reflash.
- The port would not open, which points at the cable or a driver.

## Check the workspace: status and doctor

```bash
python3 run.py status
# WORKSPACE      /Users/you/my-workspace
# WORKSPACE.YML  ✓ valid
# SECRETS.TOML   ✓ valid
# DEVICES.YML    ✓ 2 devices registered
# PROJECTS       ✓ 4 projects: blinker, garage/door_open, …
```

`status` prints one line per check on `workspace.yml`, `secrets.toml`, `devices.yml`, and `projects/`.  Every `deploy` runs the same checks before it copies anything.  An error, such as a `devices.yml` that will not parse, stops the deploy.  A warning, such as no registered boards, prints and lets the deploy go on.  `deploy --skip-health-check` skips the checks.

`doctor` runs every `status` check, then checks the Python version, that each project's `app.py` defines `run()`, that no other program holds a registered board's serial port, and on macOS that the system still mounts drives such as `CIRCUITPY`.  Both commands exit 1 on an error and 0 on warnings alone, so a shell script can test them.

`doctor --fix-fskit-wedge` clears the macOS hang that stops `CIRCUITPY` from mounting.  [CIRCUITPY on macOS](https://chumicro.com/ChuMicro/guides/troubleshooting/macos-circuitpy/) explains the hang and the fix.

## How deploy builds the file list

`deploy` picks what to copy from the shape of the project:

| Project holds | Board receives | Libraries |
|---|---|---|
| `app.py` with a top-level `run()`, and no `code.py` or `main.py` | The project's files, plus a generated `code.py` (`main.py` on MicroPython) | Every library `app.py` imports, under `/lib/` |
| `code.py` for a CircuitPython board, or `main.py` for a MicroPython board | The project's files, as they are | None, unless you pass `--import-graph` |

Either way, the merged settings travel along as `/runtime_config.msgpack`.  `project_config.toml` and the `_generated/` folder stay on your laptop.

For an `app.py` project, the board receives:

```
/code.py                  # generated (main.py on MicroPython)
/app.py                   # your code: def run(): ...
/helpers.py               # any other file in the project folder
/runtime_config.msgpack   # the merged settings
/lib/chumicro_timing/...  # the libraries app.py imports
```

Every deploy writes the generated file again, so edits to it on the board are lost.  It holds exactly this:

```python
# Shipped by chumicro-workspace; do not edit.
from app import run as _run
_run()
```

`deploy` writes only the file the board's runtime starts from, `code.py` or `main.py`.  A project holding only `code.py`, deployed to a MicroPython board, stops with a message before anything is copied.  So does a project holding only `main.py`, deployed to a CircuitPython board.

`deploy` also refuses these project shapes before it copies anything:

- `app.py` defines `async def run()`.  The generated file calls `run()` without awaiting it, so the board would start and do nothing.  ChuMicro code runs in a plain `while True:` loop.
- `code.py`, `main.py`, or `app.py` calls `microcontroller.reset()` or `machine.reset()`.  The reset would run on every start and reboot the board forever.
- Any copied module calls a reset at its top level, for the same reason.  A reset inside a function the code calls on purpose is fine.

`--boot-shim` and `--import-graph` choose the layout by hand.  Passing either flag replaces the automatic choice with exactly the flags you pass, so `--boot-shim` alone generates `code.py` without copying libraries.

### See the file list first with --dry-run

```bash
python3 run.py deploy garage/door_open --dry-run
```

`--dry-run` builds the file list the way a real deploy does, prints each board path with its size and a one-word kind, and leaves the board untouched.  The kinds are:

- `shim`: `/code.py` or `/main.py`, the file the board starts from.
- `config`: `/runtime_config.msgpack`.
- `library`: anything under `/lib/`.
- `file`: everything else.

A library missing from the `library` rows means the import walk never reached it.

## Choosing the board

Without `--device`, `deploy` uses the board that `workspace.yml` maps to the project under `deploy_targets:`, or else the default board in `devices.yml`.  The mapping saves typing `--device` in a workspace with several boards:

```yaml
deploy_targets:
  garage/door: pi-pico-w-circuitpython-board   # one board
  garage/window: [lolin-s2-circuitpython-board]
  garage/server:                               # several boards
    - pi-pico-w-micropython-board
    - lolin-s2-micropython-board
```

`--all-devices` and `--all-projects` deploy in a loop, and a failure on one target moves on to the next.  The exit code is non-zero when any target failed:

- `deploy <name> --all-devices` sends one project to every board in `devices.yml`, in file order.  It conflicts with `--device` and `--runtime`.
- `deploy --all-projects` sends every project in `deploy_targets:` to each board listed for it, in file order.  It conflicts with a project name, `--device`, `--runtime`, and `--all-devices`, and exits 2 when `deploy_targets:` is empty.

## What deploy removes from the board

A plain `deploy` leaves the board holding the new files plus `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`, where `chumicro_kvstore` saves data across restarts.  It removes every other file, including a `settings.toml` on the board, because that file's WiFi settings compete with the ones `secrets.toml` provides.

| Option | What survives on the board |
|---|---|
| `--no-wipe` | Everything outside `/lib/` and the startup and settings files (`code.py`, `main.py`, `active.py`, `runtime_config.msgpack`).  Files you copied over by hand stay. |
| (none) | `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`. |
| `--wipe` | Nothing.  The whole filesystem is erased before the copy. |

`--wipe` suits a board whose filesystem is corrupted.  CircuitPython runs `storage.erase_filesystem()`, which reformats the drive and restarts the board.  MicroPython on RP2040, RP2350, and ESP32 boards reformats its filesystem and restarts.  Both leave the firmware itself alone.  `reset-board --yes` erases the same way and deploys nothing afterward.  [Deploys and file persistence](https://chumicro.com/ChuMicro/guides/troubleshooting/deploys-and-file-persistence/) covers a deploy that removed files you wanted to keep.

## RAM mode and flash mode

A board's `deploy_mode` in `devices.yml` decides where `deploy` puts the files.  `flash`, the default, writes them to the board's storage, where they survive a restart.  `ram` runs them without writing storage: CircuitPython runs the code over the serial connection, and MicroPython reads the files from your laptop while it runs.  A restart ends a RAM-mode run.  `--deploy-mode ram` or `--deploy-mode flash` sets the mode for one run.

`deploy` switches a RAM-mode run to flash, and prints why, when a library in the file list declares `requires_flash = true` under `[tool.chumicro]` in its `pyproject.toml`, or when the file list holds any file other than `.py`.  Every project deploy carries `/runtime_config.msgpack`, so a project deploy lands in flash on a RAM-mode board too.  `--force-deploy-mode ram` keeps RAM mode anyway, for debugging that switch.  `--wipe` and `reset-board` do nothing in RAM mode.

## When a deploy fails

When the board prints a traceback that matches a known mistake, `deploy` prints a `--- hints ---` block under it:

- `NameError: name '<name>' is not defined` points at a missing `from ... import ...` in `app.py`.
- An `OSError` naming `runtime_config.msgpack` points at RAM mode, which leaves that file off the board, and suggests flash mode.
- An `ImportError` or `ModuleNotFoundError` naming a `chumicro_*` module suggests running `setup` again.
- `KeyError: '<key>'` names the missing setting and points at `project_config.toml` and `secrets.toml`.

A traceback that matches none of them prints with no hints block.  [`detect_hints`](api.md) holds the patterns.

## Libraries in depth

`library add` pins each library at the version it fetched.  `--floating` records a library as following the latest release instead.  `library update` refreshes every floating library:

```bash
python3 run.py library add chumicro_mqtt --floating
python3 run.py library update                # refresh every floating library
python3 run.py library add chumicro_mqtt --version <tag>   # fetch one release tag
```

`--channel experimental` fetches pre-release versions.  `library switch-channel <name> stable` moves a library back to the stable channel.  `library browse` opens a catalog to pick libraries from on a terminal.  `library remove <name>` deletes the library's folder and keeps its record in `workspace.yml` marked declined, so `update` skips it.  `library forget <name>` drops the record as well.  Both warn when another fetched library still needs the one you remove.

Each fetch moves the copy already in `libraries/<name>/` to `_library-backups/<name>/` first, so local edits survive in the backup.  A `.chumicro-local` file inside `libraries/<name>/` claims the folder as yours.  Every later fetch leaves that folder alone.

### Pointing the library channel at a mirror

`library add`, `browse`, `update`, and `switch-channel` fetch from GitHub.  Two environment variables move them to any server that holds the same folder layout, over `https`, `http`, or `file`:

```bash
export CHUMICRO_CHANNEL_FILES_BASE="https://mirror.example"     # replaces raw.githubusercontent.com
export CHUMICRO_CHANNEL_TARBALLS_BASE="https://mirror.example"  # replaces codeload.github.com
```

The paths keep GitHub's shapes: `<owner>/<repo>/<ref>/<path>` for single files and `<owner>/<repo>/tar.gz/refs/tags/<tag>` for release archives.  A plain folder served by `python -m http.server`, or a `file://` base, works as a mirror.

### Installing libraries without the workspace tools

`circup` on CircuitPython and `mip` on MicroPython install ChuMicro libraries straight onto a board from `ChuMicro-Bundle`, along with the ChuMicro libraries each one needs:

```bash
# CircuitPython: register the bundle once per computer, then install by name
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_wifi chumicro_mqtt chumicro_runner

# MicroPython: one mip install per library, and the board needs WiFi to fetch
mpremote connect /dev/cu.usbmodem1101 mip install \
    github:ChuMicro/ChuMicro-Bundle/chumicro_wifi
mpremote connect /dev/cu.usbmodem1101 mip install \
    github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
```

Swap `ChuMicro-Bundle` for `ChuMicro-Bundle-Experimental` to install pre-release versions.  Files land in `/lib/chumicro_<name>/` on the board.  The next `deploy` removes every one of them its own file list leaves out, so `circup` and `mip` suit a board you program by hand, without `deploy`.  [The install guide](https://chumicro.com/ChuMicro/guides/install/) covers pre-compiled `.mpy` files and `pip` for the laptop.

## Settings in depth

`deploy` builds the board's settings from two files with the same `[table]` layout:

```
secrets.toml                       projects/<name>/project_config.toml
  credentials and defaults           settings for this project:
  every project shares.              sample period, MQTT topic,
  Git ignores it.                    pins.  Wins on any key both set.
              │                                   │
              └────────────────┬──────────────────┘
                               ▼
                        merge_configs           ← chumicro_workspace.merge
                               │                  (tables merge key by key,
                               ▼                   a list replaces a list)
                       flatten_config           ← chumicro_workspace.flatten
                               │                  ([wifi] ssid becomes the
                               ▼                   flat key "wifi.ssid")
                    write_runtime_config        ← chumicro_workspace.writer
                               │                  (32-bit floats, which
                               ▼                   CircuitPython's msgpack reads)
          /runtime_config.msgpack on the board
                               │
                               ▼
                 load_runtime_config()          ← chumicro_config, on the board
```

Nested tables merge key by key at any depth, so a project can change `mqtt.topic` and keep `mqtt.host` from `secrets.toml`.  A list in `project_config.toml` replaces the list in `secrets.toml` whole.  The board reads flat dotted keys, one lookup per key.

`workspace.yml` holds workspace machinery: the `libraries:` table, `deploy_targets:`, `quality:`, and `library_sources:`.  None of it reaches the board.

`python3 run.py config-validate` checks every project's merged settings against the settings each library in the workspace marks as required, prints `OK` or `FAIL` per project, and exits 1 on any failure.

[`compose_runtime_config`](api.md) returns the merged, flattened settings as a dict and writes nothing, which suits tests.  [`build_runtime_config`](api.md) also writes the file `deploy` copies:

```python
from pathlib import Path
from chumicro_workspace.pipeline import build_runtime_config

build_runtime_config(
    secrets_toml=Path("secrets.toml"),
    project_config=Path("projects/blinker/project_config.toml"),
    output_path=Path("projects/blinker/_generated/runtime_config.msgpack"),
)
```

## Firmware

`install-firmware` downloads the latest stable release of the runtime a registered board already runs, and flashes it.  `--method` picks the flashing tool: `uf2` for RP2040 and RP2350 boards such as the Pi Pico, `esptool` for ESP32 boards.

```bash
python3 run.py install-firmware --method uf2                       # a Pi Pico
python3 run.py install-firmware --method esptool                   # an ESP32 board
python3 run.py install-firmware --method uf2 --allow-prerelease    # include release candidates
python3 run.py install-firmware --method uf2 --url https://example.com/custom.uf2
```

The command puts the board into its bootloader where it can, and otherwise prompts for the manual step, such as holding BOOTSEL while plugging in a Pico.  `upgrade-firmware` is the same command under another name.

`install-firmware` reads the board's details from `devices.yml`, so the board must be registered first.  A board with no CircuitPython or MicroPython on it gets its first firmware the way [Start here](https://chumicro.com/ChuMicro/guides/start-here/) describes.

Without `--url`, the download address comes from the board's `devices.yml` entry, through `derive_firmware_url` in [`chumicro-deploy`](https://chumicro.com/ChuMicro/deploy/stable/api/):

1. `hardware.firmware_source`, when set, is used as it is.  A vendor build or a mirror goes here.
2. A CircuitPython board gets the latest stable build for its `hardware.board_id` from the Adafruit download bucket.
3. A MicroPython board gets the latest stable build from micropython.org for its `hardware.machine`, through a built-in table of board names.

ESP32 boards on MicroPython take a `.bin` file in place of `.uf2`.  Add `firmware_extension: bin` under the entry's `hardware:` block.

`add-device` prints a warning, and registers the board anyway, when its firmware is older than CircuitPython 10.1 or MicroPython 1.27, or reports a version it cannot read.  [`check_firmware_supported`](api.md) makes that comparison.

## Code checks: test, lint, preflight

```bash
python3 run.py test -- -k blink -x   # pytest; its own flags go after --
python3 run.py lint -- --fix         # ruff, then chumicro-checks; ruff's flags go after --
python3 run.py preflight             # lint, then test, stopping at the first failure
```

`test`, `lint`, and `preflight` read their settings from `quality.toml` and `workspace.yml`.  `quality.toml` at the workspace root holds the settings git tracks.  The `quality:` block in `workspace.yml` overrides them on one computer:

```toml
# quality.toml: shared settings, tracked by git
coverage_threshold = 85    # top-level keys go before any [table]

[lint]
enabled = true
tools = ["ruff", "chumicro-checks"]
select = ["E", "F", "I"]
```

```yaml
# workspace.yml: this computer's overrides
quality:
  lint:
    enabled: false
```

- `lint.enabled = false` makes `lint` print a note and run nothing.
- `lint.tools` picks the tools.  The default runs both.  An empty list acts like `enabled = false`.  An unknown tool name fails when the settings load.
- `lint.select` goes to ruff as `--select <list>`, ahead of the flags after `--`, so your own flags win.
- `coverage_threshold` goes to pytest as `--cov-fail-under=<n>`.

With neither file present, linting runs and coverage has no minimum.  [`load_quality_config`](api.md) reads and checks both files, and an error names the file that holds the bad value.

## Python API

The CLI is built on the Python modules the [API reference](api.md) documents, and a script can call them directly.  This script deploys an `app.py` project with a generated `main.py` and no libraries, the layout `--boot-shim` alone gives:

```python
from chumicro_deploy import Device, Deployer
from chumicro_workspace.boot_shim import project_boot_source
from chumicro_workspace.workspace import WorkspaceLayout

workspace = WorkspaceLayout.from_dir()
device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

source = project_boot_source(
    workspace.project_dir("garage/door_open"),
    workspace=workspace,
    entrypoint_filename="main.py",
)
result = Deployer(device).deploy_diff(source)
assert result.success
```

`deploy_diff` asks the board which files it holds, deletes the ones the new file list leaves out, then copies the new files and starts the board.

`devices.yml` belongs to `chumicro-deploy`, which reads and writes it with `ruamel.yaml` so comments and key order survive.  Every change is load, change, dump:

```python
from pathlib import Path
from chumicro_deploy.config.devices_yaml import (
    HardwareOverwriteError,
    dump_devices,
    load_devices,
    update_device_address,
)

devices = load_devices(Path("devices.yml"))
update_device_address(devices, "back-porch", "/dev/cu.usbmodem1102")
dump_devices(devices, Path("devices.yml"))
```

`update_device_hardware` raises `HardwareOverwriteError` when a read-once field would change.  `force=True` allows the change after a board swap.  `rename_device` also rewrites any `defaults.<runtime>` entry that named the old id.  `remove_device` deletes an entry, clears any `defaults.<runtime>` that named it, and returns the removed entry.

`chumicro-workspace` runs on CPython on your laptop.  Its board-side half is [`chumicro-config`](https://chumicro.com/ChuMicro/config/stable/), which reads the settings file each deploy writes.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
