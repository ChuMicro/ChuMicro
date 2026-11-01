# Deploy refused, or ImportError on boot

A deploy checks your project on the laptop before it copies anything. It looks for a file the board can start from, and for a file to send behind every `import`. A failed check stops the deploy with the reason and leaves the board unchanged. An import the check never saw fails later, on the board, as `ImportError`.

## `Deploy refused: unresolved import.`

The message names each file and the module it imports, for example `code.py imports 'chumicro_wifi', which resolves to no deployed file`. Find that module's case:

- **A ChuMicro library missing from the [workspace](../glossary.md#workspace).** Add it, then deploy again:

  ```bash
  python3 run.py library add chumicro_wifi
  ```

- **A typo** in the `import` line. Fix the spelling.
- **A helper file of your own.** Keep it in the project's folder, or in `shared/` when several projects use it. [The `shared/` section](#from-sharedfoo-import-bar-is-refused) shows how to import from there.
- **A library from elsewhere**, such as the Adafruit bundle or PyPI. `pip install` puts it on your laptop and `circup` puts it straight onto the board, and the deploy sees neither copy. Copy the library's source folder, or its single `.py` file, into `packages/`, and the deploy sends it along.
- **An optional import** your code can run without. Wrap it, and the deploy treats it as optional:

  ```python
  try:
      import adafruit_dotstar
  except ImportError:
      adafruit_dotstar = None
  ```

- **A module built into your firmware that the deploy has no record of.** List it in the `CHUMICRO_DEPLOY_EXTRA_BUILTINS` environment variable, as comma-separated names, for that run.

The deploy searches the project's own folder, the workspace's `libraries/`, `shared/`, and `packages/` folders, and the modules built into the board's firmware. The named module is in none of them.

## `from shared.foo import bar` is refused

Import by the bare name:

```python
from foo import bar
```

The refusal prints the same hint. The deploy copies the files in `shared/` straight onto the board, so `shared/foo.py` arrives as a module named `foo`, and the board has no module called `shared`.

## The board prints `ImportError: no module named 'chumicro_...'` after a clean deploy

List the files a deploy sends, without touching the board:

```bash
python3 run.py deploy <project> --dry-run
```

A project with its own `code.py` or `main.py` shows only its own files there, and no libraries. Pick one fix:

- Move your code into `app.py`, inside a function named `run`, and delete `code.py` / `main.py`. `python3 run.py new` creates this layout. The deploy then follows your imports and sends every library they reach:

  ```python
  # app.py
  import time


  def run():
      while True:
          print("still running")
          time.sleep(1)
  ```

- Keep `code.py` and ask the deploy to follow its imports:

  ```bash
  python3 run.py deploy <project> --import-graph
  ```

A project with its own `code.py` or `main.py` ships as-is: the files in its folder and nothing else. The deploy also clears files it did not send, which removes libraries left on the board by earlier deploys.

## `has code.py (CircuitPython entrypoint) but you targeted a MicroPython board`

Rename the file to match the board, or move the code into `app.py` under `def run():`, which runs on both. When the deploy picked the wrong board, name the right one with `--device <id>`.

CircuitPython starts `code.py` at boot and MicroPython starts `main.py`. The project carries the file for the other runtime. The reverse message, `has main.py` on a CircuitPython board, means the same thing.

## `has no entrypoint chumicro-deploy can use`

Wrap your code in `def run():` inside `app.py`, as in [the `app.py` example above](#the-board-prints-importerror-no-module-named-chumicro_-after-a-clean-deploy).

The project folder holds no `code.py`, no `main.py`, and no `app.py` with a `def run():` in it, so the board has nothing to start.

## `defines async def run() in app.py, which chumicro can't run`

Change it to a plain `def run():` with a `while True:` loop. ChuMicro libraries run without `async` or `await`.

The board calls `run()` like an ordinary function. Calling an `async def` function only creates a coroutine, so the board would boot and do nothing.

## `ships code.py with a hard reset call`, or `calls a board hard reset ... at module top level`

Move the reset into a function in another module, and call that function only when something has gone wrong.

A `microcontroller.reset()` or `machine.reset()` that runs at boot restarts the board. The board then runs the same file and resets again, forever, until you wipe it. The deploy refuses any reset that would run at startup: anywhere in `code.py`, `main.py`, or `app.py`, and at the top level of any other file it sends.

## `python3 run.py new` rejects the project name

Rename `back-porch` to `back_porch`, and `1sensor` to `sensor_one`.

Python imports project folders as modules, so each part of the name follows Python's naming rules: letters, digits, and underscores, starting with a letter. Names that start with an underscore, such as `_template`, belong to the tools. A `/` or a `.` in the name makes nested folders: `garage/door` creates `projects/garage/door/`.

## `RuntimeError: chumicro_sockets.sockets_factory not available`

Add `chumicro_sockets`, the library that opens network connections:

```bash
python3 run.py library add chumicro_sockets
```

To build your own connections on purpose, hand one in through the keyword argument the error names, such as `transport_factory=`.

`MQTTClient.from_config(...)` and the other network clients' `from_config` raise this error when the board lacks `chumicro_sockets`. `library add` installs it beside the libraries that need it, unless its prompt to pull it in was declined. A `__chumicro_skip_factories__` entry in the project's entrypoint also leaves it off the board, as [Slimming your deploy](../contributing/slimming-your-deploy.md) describes.
