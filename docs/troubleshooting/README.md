# Troubleshooting

Find what you are seeing in the left column and open the page beside it. Each page starts with the quickest check, then the fix, then why it happens.

| What you see | Page |
|---|---|
| Nothing appears when you plug the board in, or `discover` lists no port | [Board not found](board-not-found.md) |
| `PORT_UNAVAILABLE`, `Resource busy`, or `Permission denied: '/dev/ttyACM0'` | [Board not found](board-not-found.md) |
| A deploy hangs, or prints `COMMAND_TIMED_OUT` or `RAW_REPL_UNRESPONSIVE` | [Board not found](board-not-found.md) |
| A deploy reaches the wrong board, or a board that worked yesterday is "unavailable" today | [Board not found](board-not-found.md) |
| A drive named `RPI-RP2` (or `...BOOT`) shows up instead of `CIRCUITPY`, or the tool says `NO_PYTHON_RUNTIME` | [Getting firmware onto a new board](firmware-onto-a-new-board.md) |
| Registering a board warns `Firmware below the supported floor` | [Getting firmware onto a new board](firmware-onto-a-new-board.md) |
| On a Mac, `CIRCUITPY` never appears, is read-only, or deploys fail with `Invalid argument` | [CIRCUITPY on macOS](macos-circuitpy.md) |
| `Deploy refused: unresolved import`, or the board prints `ImportError: no module named ...` | [Deploy refused, or ImportError on boot](deploy-refused-importerror.md) |
| A deploy refuses your project: wrong entrypoint, `async def run()`, or a reset in boot code | [Deploy refused, or ImportError on boot](deploy-refused-importerror.md) |
| A deploy deleted files you put on the board yourself (`settings.toml`, libraries from `circup`) | [Deploys and file persistence](deploys-and-file-persistence.md) |
| The deploy prints `switching to flash mode` after you asked for RAM | [Deploys and file persistence](deploys-and-file-persistence.md) |
| The board never joins wifi, and `wifi.last_error` is `None` | [WiFi won't connect](wifi-wont-connect.md) |
| An example stops with `RuntimeError: set WIFI_SSID + WIFI_PASSWORD ...` | [WiFi won't connect](wifi-wont-connect.md) |
| Everything freezes for several seconds while a CircuitPython board connects | [WiFi won't connect](wifi-wont-connect.md) |
| `certificate validity starts in the future`, or an HTTPS request fails on a valid site | [TLS and HTTPS failures](tls-https-failures.md) |
| `MemoryError`, or `OSError: [Errno 12]` | [Running out of memory](out-of-memory.md) |
| `Cannot remount path when visible via USB.` | [Persisting data](persisting-data.md) |
| `KVStoreFull`, saved data comes back empty, or a stored number comes back changed | [Persisting data](persisting-data.md) |
| One particular board misbehaves where another runs the same code fine | [Known board quirks](board-quirks.md) |
| Building the CircuitPython unix port fails with `'iget'` or `_mp_type_ringio` (contributors) | [CircuitPython RingIO build failure](circuitpython-ringio.md) |

## Reading the commands

Every command on these pages runs on your laptop, from the folder of your workbench (your copy of the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)), in the same form [Start here](../start-here.md) uses:

```bash
python3 run.py doctor
```

Error messages sometimes print the same command as `chumicro-workspace doctor`. That is the program `run.py` starts for you, so either spelling works, and inside the ChuMicro repository itself `chumicro-workspace` is the one to type.

Most failures already print two or three fix steps right under the error. Read those first. These pages cover the problems that take more than one message to explain, or whose error names a symptom rather than the cause.

## Windows

The tools that talk to a board run on macOS and Linux. On native Windows they stop with `chumicro-deploy is not supported on native Windows`. WSL2 (Linux running inside Windows) works, but a USB board only appears inside it after you attach it with [`usbipd-win`](https://github.com/dorssel/usbipd-win). Editing, linting, and host-side tests run on Windows directly; [CONTRIBUTING](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#prerequisites) covers what each platform gets.

## Related

- [Device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md): registering boards in `devices.yml` and running the tests that need real hardware.
- [Contributor cheat sheet](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/cheat-sheet.md): one-line fixes for lint, test, and coverage failures in the ChuMicro repository.
