# Deploys and file persistence

A deploy makes the files on the board match your project. Files copied onto `CIRCUITPY` by hand disappear at the next deploy.

## A deploy deleted files put on the board by hand

List exactly what a deploy sends, without touching the board:

```bash
python3 run.py deploy <project> --dry-run
```

Keep each kind of file where the deploy sends it from:

- **Libraries:** add them to the [workspace](../glossary.md#workspace), and every deploy carries the ones your project imports. A project with its own `code.py` or `main.py` also needs `--import-graph`, as [Deploy refused, or ImportError on boot](deploy-refused-importerror.md#the-board-prints-importerror-no-module-named-chumicro_-after-a-clean-deploy) explains.

  ```bash
  python3 run.py library add chumicro_mqtt
  ```

- **Your own files**, such as fonts, images, or a data table: put them in the project folder. They ride along with every deploy.
- **Your own `boot.py`:** put it in the project folder too. A project's `boot.py` replaces the one on the board.
- **Wifi passwords and other settings:** `secrets.toml` in the workspace folder. The deploy turns it into `/runtime_config.msgpack` on the board.

To deploy once and leave the board's other files alone, pass `--no-wipe`:

```bash
python3 run.py deploy <project> --no-wipe
```

A deploy sends your project, the libraries it uses, and a config file, then deletes every other file on the board except these:

- `boot.py`, the file CircuitPython and MicroPython run before your program starts.
- `boot_out.txt`, which CircuitPython writes about itself at power-up.
- `_chu_kv.msgpack`, where `chumicro-kvstore` saves data on boards that keep it in a file.

The deleted files include libraries installed with `circup` or `mip`. A `settings.toml` on the board goes too, with a `WARNING: removing the board's settings.toml` notice. Its `CIRCUITPY_WIFI_*` keys make CircuitPython join wifi by itself, which [fights the wifi library for the radio](wifi-wont-connect.md#wifi-drops-or-fights-itself-on-circuitpython).

## `reset-board` erased `settings.toml` and `boot.py`

A `boot.py` kept in the project folder comes back with the next deploy. Wifi settings belong in the workspace's `secrets.toml`, which every deploy sends.

`reset-board` empties the board's filesystem, the files a deploy keeps included. Its job is recovering a board whose files are damaged. Without `--yes` it refuses to run, which leaves a moment to back up files that exist only on the board:

```bash
python3 run.py reset-board --device <id> --yes
```

`deploy --wipe` erases the same way before it copies your project.

## The deploy prints `switching to flash mode` after you asked for RAM

Nothing needs fixing: your project runs in flash mode as normal. To stop the message, drop the `deploy_mode: ram` line from `devices.yml`, or the `--deploy-mode ram` flag from the command.

*Flash* mode, the default, writes your files to the board's storage, where they survive a reset. *RAM* mode runs your code without writing anything: it saves wear on the board's flash and loses everything at the next reset. `deploy_mode: ram` in `devices.yml` or `--deploy-mode ram` on the command selects RAM mode.

The deploy switches a RAM request to flash, and prints why, whenever the payload holds something RAM mode can't carry. RAM mode carries only `.py` files reliably. A workspace project always sends its config file, `/runtime_config.msgpack`, so every project deploy lands in flash. The network libraries `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, and `chumicro-websockets` trigger the same switch, because importing them in RAM mode runs small boards out of memory.

## After `--force-deploy-mode ram`: `ENOENT` on `/runtime_config.msgpack`, a boot counter that never counts, or `INSUFFICIENT_MEMORY`

Deploy in flash mode:

```bash
python3 run.py deploy <project>
```

When `devices.yml` sets `deploy_mode: ram` for the board, or under `defaults:` for every board, delete that line or change it to `deploy_mode: flash`.

`--force-deploy-mode ram` keeps RAM mode even where the deploy would switch, so everything the switch protects against happens:

- `/runtime_config.msgpack` never reaches the board, so `load_runtime_config()` raises `OSError: [Errno 2] ENOENT` and your wifi settings never arrive.
- Your program never lands in the board's storage, so after a reset the board runs nothing, and a boot counter never gets the chance to count.
- The payload has to fit in the board's free memory at once. A large one fails with `INSUFFICIENT_MEMORY`, and on CircuitPython it can drop the USB connection instead.
