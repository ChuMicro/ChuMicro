# Deploys and file persistence

A deploy makes the files on the board match your project. If you are used to dragging files onto CIRCUITPY, that has a surprising side: anything you put on the board yourself disappears at the next deploy. This page covers what a deploy keeps, what it removes, and how to keep your own files.

## A deploy deleted files I put on the board myself

A deploy sends your project, the libraries it uses, and a config file, then deletes every other file on the board. Three files survive:

- `boot.py`, the file CircuitPython and MicroPython run before your program starts.
- `boot_out.txt`, which CircuitPython writes about itself at power-up.
- `_chu_kv.msgpack`, where `chumicro-kvstore` saves data on boards that keep it in a file.

Everything else goes, including libraries you installed with `circup` or `mip` and files you copied over by hand. A `settings.toml` on the board goes too, with a `WARNING: removing the board's settings.toml` notice. Its `CIRCUITPY_WIFI_*` keys make CircuitPython join wifi by itself, which [fights the wifi library for the radio](wifi-wont-connect.md#wifi-drops-or-fights-itself-on-circuitpython).

To see exactly what a deploy sends, without touching the board:

```bash
python3 run.py deploy <project> --dry-run
```

Then keep each kind of file where the deploy sends it from:

- **Libraries:** add them to the workbench, and every deploy carries the ones your project imports. (A project with its own `code.py` or `main.py` needs one extra flag; see [Deploy refused, or ImportError on boot](deploy-refused-importerror.md#the-board-prints-importerror-no-module-named-chumicro_-after-a-clean-deploy).)

  ```bash
  python3 run.py library add chumicro_mqtt
  ```

- **Your own files** (fonts, images, a data table): put them in the project folder. They ride along with every deploy.
- **Your own `boot.py`:** put it in the project folder too. A project's `boot.py` replaces the one on the board.
- **Wifi passwords and other settings:** `secrets.toml` in the workbench folder, which the deploy turns into `/runtime_config.msgpack` on the board.

To deploy once and leave the board's other files alone, pass `--no-wipe`:

```bash
python3 run.py deploy <project> --no-wipe
```

## `reset-board` erased `settings.toml` and `boot.py`

`reset-board` empties the board's filesystem completely, the files a deploy keeps included. It is the recovery step for a board whose files are damaged, and it refuses to run without `--yes` so you get a moment to back up anything that exists only on the board:

```bash
python3 run.py reset-board --device <id> --yes
```

`deploy --wipe` does the same erase before it copies your project.

## The deploy prints `switching to flash mode` after you asked for RAM

A deploy has two modes. *Flash* mode, the default, writes your files to the board's storage, where they survive a reset. *RAM* mode runs your code without writing anything, which saves wear on the board's flash but loses everything at the next reset. You opt into RAM mode with `deploy_mode: ram` in `devices.yml` or `--deploy-mode ram` on the command.

The deploy switches a RAM request back to flash, and prints why, whenever the payload holds something RAM mode can't carry. RAM mode only carries `.py` files reliably, and a workbench project always sends its config file, `/runtime_config.msgpack`, so project deploys land in flash. The heavy network libraries (`chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`) trigger the same switch, because importing them in RAM mode runs small boards out of memory.

Nothing needs fixing: your project runs in flash mode as normal. To stop the message, drop the `deploy_mode: ram` line from `devices.yml`, or the `--deploy-mode ram` flag from the command.

## After `--force-deploy-mode ram`: `ENOENT` on `/runtime_config.msgpack`, a boot counter that never counts, or `INSUFFICIENT_MEMORY`

`--force-deploy-mode ram` keeps RAM mode even when the deploy would switch, so everything the switch protects against happens:

- `/runtime_config.msgpack` never reaches the board, so `load_runtime_config()` raises `OSError: [Errno 2] ENOENT` and your wifi settings never arrive.
- Your program never lands in the board's storage, so after a reset the board doesn't run it, and a boot counter never gets the chance to count.
- The payload has to fit in the board's free memory at once. A large one fails with `INSUFFICIENT_MEMORY`, and on CircuitPython it can drop the USB connection instead.

Deploy in flash mode:

```bash
python3 run.py deploy <project>
```

If `devices.yml` sets `deploy_mode: ram` for the board (or under `defaults:` for every board), delete that line or change it to `deploy_mode: flash`.
