---
title: "WiFi credentials: get a network name and password onto a board without putting them in git"
---

<span id="wiring-wifi-credentials-for-examples-and-functional-tests"></span>

# WiFi credentials

On macOS or Linux (native Windows deploy tooling is unsupported), connect a WiFi-capable CircuitPython or MicroPython board without committing credentials. Replace `first-board` with your registered board name.

- [Workbench route](#workbench-route): finished [Start here](start-here.md), using `my-workbench`.
- [Clone route](#clone-route): ran `python3 scripts/prepare_workspace.py`, which creates `.venv`; register through `add-device` or the initial example wizard.
- [Direct-copy route](#direct-copy-route): prepared workbench or clone; edit constants in copied Python source.

## Edit root credentials

For Workbench and Clone only. Direct-copy readers: [prepare source copies](#prepare-source-copies), skipping TOML.

Use `secrets.toml` beside `run.py` in the workbench root, created during Start here, or at the repository root, created by clone preparation. Only the root `secrets.toml` is read as configuration input.

Workbench git ignores every `secrets.toml`; clone git ignores only the root file. A project-folder copy is ignored as input but sent to the board root as plaintext.

Replace both `[wifi]` placeholders (SSID means network name). If the file is missing, create:

```toml
[wifi]
ssid = "replace-with-your-ap-ssid"
password = "replace-with-your-password"

[mqtt.broker]
host = "replace-with-your-broker-host"
port = 1883
```

Keep `[mqtt.broker]`: validation for a deploy or example run requires it with `chumicro_mqtt`, which the clone includes.

### Quote both TOML values

- Neither `"` nor `\` inside: use double quotes.
- `"` or `\` inside, but no apostrophe: use single quotes, like `'ex"am\ple'`.
- Apostrophe inside: use double quotes; replace `"` with `\"` and `\` with `\\`.

Misquoting can cause parse errors or silently change values through escapes such as `\n` and `\t`.

## Before your first deploy

**Deletion:** On both runtimes, a deploy or example run (`deploy-example`) removes files outside the files the deploy sends, except `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`. This includes hand-installed libraries, including circup/mip installs, and CircuitPython's `settings.toml`. See the [removal rule](troubleshooting/deploys-and-file-persistence.md#a-deploy-made-my-hand-installed-libraries-and-settingstoml-disappear).

`CIRCUITPY_WIFI_*` auto-connect can conflict with `chumicro_wifi`: they share one radio.

Before deploying, copy your own board files, including credential-bearing `settings.toml` or `secrets.py`, to an existing laptop folder outside every checkout; create it first if necessary. Reinstall libraries later with circup/mip; libraries need no copy-off.

CircuitPython: use a file browser to copy from `CIRCUITPY`.

MicroPython: attach one USB board. From the prepared workbench/repository root, copy one file per invocation: `:` means board side, `<file>` the board filename, `<folder>` your backup folder.

```bash
.venv/bin/mpremote fs cp :<file> <folder>/<file>
```

<span id="recommended-use-a-chumicro-workspace"></span>

## Workbench route

First [edit and quote credentials](#edit-root-credentials) and [preserve board files](#before-your-first-deploy). Run these commands in `my-workbench`:

```bash
python3 run.py new my_first_network --from examples/wifi_only
python3 run.py library add chumicro_wifi
python3 run.py library add chumicro_runner
```

Press Enter at `pull <dep>? [Y/n]` to accept dependencies.

This creates `projects/my_first_network/`. Re-adding Runner, already acquired in Start here, leaves the new project's source unchanged. Each headline shows that library's version; dependency lines follow each:

```text
Added chumicro_wifi v<version> (stable)
Added chumicro_runner v<version> (stable)
```

**Password display:** `dump-config` prints the full password, which remains in terminal scrollback.

```bash
python3 run.py dump-config my_first_network
```

Compare this JSON, the values the deploy sends: `wifi.ssid` and `wifi.password` must match your intended values.

JSON writes `"` as `\"`, `\` as `\\`, and non-ASCII network-name characters as `\uXXXX`. TOML `'ex"am\ple'` becomes JSON `"ex\"am\\ple"`. Passwords use printable ASCII; password backslash pairs other than `\"` or `\\` mean misquoting.

Remaining placeholders: check root-file replacements. Malformed TOML gives a traceback ending in `tomllib.TOMLDecodeError` with line/column; fix the [quoting](#quote-both-toml-values).

Deploy with `--tail 30`, a 30-second board serial-output watch:

```bash
python3 run.py deploy my_first_network --device first-board --tail 30
```

A successful join prints:

```text
wifi: connected at <ip>
```

Repeated `wifi: connecting` means joining or retrying, not terminal failure. If it persists or success is missing, compare `dump-config` with network details; see [WiFi troubleshooting](troubleshooting/wifi-wont-connect.md).

### Change networks

The board uses one network, with values from its last deploy.

**Different network and password:** Replace both root `secrets.toml` `[wifi]` values. Run `dump-config` above, then repeat the deploy command.

**One project, unchanged password:** `projects/my_first_network/project_config.toml` contains committed per-project settings, which override secret-file values. **Duplicate `[wifi]` headers cause parse errors.** Edit the existing table: uncomment `# ssid = "MyNetwork"` and substitute your new network name.

```toml
[wifi]
ssid = "MyNetwork"
```

Other comments can remain. Keep the password in `secrets.toml`; committing it in the project file retains it in git history. Run `dump-config`, then repeat the deploy command.

<span id="running-an-example-from-a-clone-of-this-repository"></span>

## Clone route

First [edit and quote credentials](#edit-root-credentials) and [preserve board files](#before-your-first-deploy). From the repository root, activate `.venv` and run:

```bash
source .venv/bin/activate
chumicro-workspace deploy-example wifi connect_to_ap --runtime micropython
```

For CircuitPython, substitute `--runtime circuitpython`. Without registration, the wizard offers a port picker and saves your board name.

After deployment, output is captured for up to 10 seconds, then chumicro-repl opens at a local `>>>` prompt. Empty Enter sends no bytes and displays buffered output; future output needs another Enter.

If `WIFI_OK` or `FAIL` is missing, wait and press Enter; still missing, wait and press Enter again. A `FAIL` result appears about 15 seconds after example start, beyond initial capture. Exit with Ctrl-X.

`WIFI_OK ip=<address>` means joined. `FAIL last_error=...` can mean placeholders, wrong password, misquoting, or an unreachable network. Compare root secrets with network details; fix [quoting](#quote-both-toml-values). For `deploy-example: precheck failed: <tomllib message>`, repair malformed TOML using those rules.

For another network, replace both root `[wifi]` values and repeat the example command.

<span id="raw-single-file-deploy-no-workspace"></span>

## Direct-copy route

### Prepare source copies

Use a prepared workbench or clone and its installed tools; run commands from that root. MicroPython needs one attached USB board; mpremote selects it automatically, without registration. CircuitPython needs a mounted `CIRCUITPY` drive and a registered board for tail (`add-device` or the example wizard). Without the drive, use the Workbench or Clone route.

Copy `ntp_query.py` and sibling `helpers.py` from the clone's `libraries/ntp/examples/`, or each file's raw text in [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp/examples), into a folder outside every checkout.

**Git exposure:** In-checkout edits appear in `git status`. Committed credentials stay in history; pushing exposes them to remote repository readers, publicly if the repository is public.

Edit only the copied `ntp_query.py`, replacing both constants. In Python strings, write `\` as `\\` and `"` as `\"`:

```python
WIFI_SSID = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
```

Install board dependencies `chumicro_ntp`, `chumicro_sockets`, and `chumicro_timing` with [circup/mip](install.md). A previous deploy's `/runtime_config.msgpack` overrides these constants; remove it below. See [credential locations](#locate-credentials).

### Run on CircuitPython

1. Eject `CIRCUITPY` to flush writes, then unplug and replug the same USB port. Resetting with pending writes risks drive corruption on macOS. Power-up enables auto-reload, which restarts the program after a drive write.
2. Delete `/runtime_config.msgpack` from the drive's top level if present.
3. Copy `helpers.py` to the drive.
4. Rename edited laptop `ntp_query.py` to `code.py`.

Start a 60-second tail, a board serial-output watch.

Workbench, in `my-workbench`:

```bash
python3 run.py repl --tail 60 --device first-board
```

Clone, repository root with `.venv` active (`source .venv/bin/activate`):

```bash
chumicro-workspace repl --tail 60 --runtime circuitpython
```

Within 60 seconds, drag `code.py` onto `CIRCUITPY` in the file browser, overwriting it. The program restarts; tail stays silent until the board prints. If tail expires, restart it and repeat the drag.

### Run on MicroPython

With one board attached, from the prepared workbench/repository root, use `.venv/bin/mpremote` (available in both). Remove stale configuration:

```bash
.venv/bin/mpremote fs rm :runtime_config.msgpack
```

If absent, `mpremote: rm: ...` is harmless; continue. `<path>` is your edited-copy folder:

```bash
.venv/bin/mpremote fs cp <path>/ntp_query.py :main.py
.venv/bin/mpremote fs cp <path>/helpers.py :helpers.py
```

This installs `/main.py` for future boots and `/helpers.py`. Now execute the edited laptop script on the connected board:

```bash
.venv/bin/mpremote run <path>/ntp_query.py
```

`run` streams stdout/errors through completion without writing a script file. No tail, replug, or registration is needed. If an import error names one of the three dependencies, [install it](install.md), then repeat `run`.

### Check results and change networks

Success prints:

```text
WIFI_OK ip=<address>
NTP_OK unix_seconds=<n>
```

`NTP_FAIL <error>` after `WIFI_OK` means credentials worked but the time query failed, for example because UDP 123 is blocked. Immediate `RuntimeError` naming `WIFI_SSID` means the network-name placeholder remains.

Wrong passwords or unreachable networks can produce MicroPython's `OSError: wifi did not connect within 15s` after about 15 seconds, or CircuitPython's `ConnectionError` from `wifi.radio.connect`, before the helper's timeout loop.

For CircuitPython silence, inspect `CIRCUITPY/lib`, confirm the new `code.py`, then repeat tail and copy.

For another network, edit both constants: CircuitPython's laptop `code.py`, then tail and copy; MicroPython's `ntp_query.py`, then recopy to `/main.py` and repeat `run`.

<span id="what-the-library-reads"></span>

## Locate credentials

A deploy or example run writes board configuration to `/runtime_config.msgpack`; the app reads it. It is unencrypted: board-file access reveals credentials.

Generated laptop copies are ignored by git: workbench `projects/<name>/_generated/`, clone `libraries/<lib>/examples/_generated/`. Direct-copy credentials live in edited laptop source and board source.

## Related pages

- [`chumicro_wifi` guide](https://chumicro.com/ChuMicro/wifi/stable/guide/#configuration): configuration, including optional timeout, backoff, and hostname keys.
- [workspace guide](https://chumicro.com/ChuMicro/workspace/stable/guide/#how-config-flows-from-your-edits-to-the-device): configuration-flow mechanics.
