# Deploy refused, or ImportError on boot

Before a deploy copies anything to the board, it checks your project on the laptop: that there is a file the board can start from, and that every `import` points at a file it can send. When a check fails, the deploy stops and prints the reason, and nothing on the board changes. An import the check never saw fails later instead, on the board, as `ImportError`.

## `Deploy refused: unresolved import.`

The message names each file and the module it imports, for example `code.py imports 'chumicro_wifi', which resolves to no deployed file`. The deploy looked for that module in the project's own folder, in your workbench's `libraries/`, `shared/`, and `packages/` folders, and among the modules built into the board's firmware, and found it in none of them.

Find your case:

- **A ChuMicro library you haven't added.** Add it, then deploy again:

  ```bash
  python3 run.py library add chumicro_wifi
  ```

- **A typo** in the `import` line. Fix the spelling.
- **A helper file of your own.** Keep it in the project's folder, or in `shared/` when several projects use it (see the next section for how to import from `shared/`).
- **A library from elsewhere**, such as the Adafruit bundle or PyPI. `pip install` and `circup` put it on your laptop or straight onto the board, where the deploy can't see it. Copy the library's source folder (or single `.py` file) into `packages/`, and the deploy sends it along.
- **An optional import** your code can run without. Wrap it, and the deploy treats it as optional:

  ```python
  try:
      import adafruit_dotstar
  except ImportError:
      adafruit_dotstar = None
  ```

- **A module built into your firmware that the deploy doesn't know about.** List it in the `CHUMICRO_DEPLOY_EXTRA_BUILTINS` environment variable (comma-separated names) for that run.

## `from shared.foo import bar` is refused

The deploy copies the files in `shared/` straight onto the board, so `shared/foo.py` arrives as a module named `foo`. No module called `shared` exists on the board. Import by the bare name:

```python
from foo import bar
```

The refusal prints the same hint.

## The board prints `ImportError: no module named 'chumicro_...'` after a clean deploy

Your project has its own `code.py` or `main.py`. A project like that is sent as-is: the files in its folder and nothing else, so the libraries it imports never reach the board. The deploy also clears files it didn't send, which removes libraries left on the board from earlier.

Pick one fix:

- Move your code into `app.py`, inside a function named `run`, and delete `code.py` / `main.py`. This is the layout `python3 run.py new` creates. The deploy then follows your imports and sends every library they reach:

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

`python3 run.py deploy <project> --dry-run` lists every file a deploy would send, without touching the board, so you can confirm the libraries are in it.

## `has code.py (CircuitPython entrypoint) but you targeted a MicroPython board`

CircuitPython starts `code.py` at boot and MicroPython starts `main.py`, and your project carries the file for the other runtime. The reverse message (`has main.py` on a CircuitPython board) means the same thing.

Rename the file to match the board, or move the code into `app.py` under `def run():`, which works on both. If the deploy picked the wrong board, name the right one with `--device <id>`.

## `has no entrypoint chumicro-deploy can use`

The project folder has no `code.py`, no `main.py`, and no `app.py` with a `def run():` in it, so the board would have nothing to start. Wrap your code in `def run():` inside `app.py`, as in the example above.

## `defines async def run() in app.py, which chumicro can't run`

The board calls `run()` like an ordinary function, and calling an `async def` function only creates a coroutine without running it, so the board would boot and do nothing. Change it to a plain `def run():` with a `while True:` loop. ChuMicro libraries never need `async` or `await`.

## `ships code.py with a hard reset call`, or `calls a board hard reset ... at module top level`

A `microcontroller.reset()` or `machine.reset()` that runs at boot restarts the board, which runs the same file and resets again, forever, until you wipe the board. The deploy refuses any reset that would run at startup: anywhere in `code.py`, `main.py`, or `app.py`, and at the top level of any other file it sends.

Move the reset into a function in another module, and call that function only when something has gone wrong.

## `python3 run.py new` rejects the project name

Project folders are imported as Python modules, so each part of the name follows Python's naming rules: letters, digits, and underscores, no hyphens or spaces, no leading digit, and no leading underscore (names like `_template` are reserved for the tools). Rename `back-porch` to `back_porch`, and `1sensor` to `sensor_one`. A `/` or a `.` in the name makes nested folders: `garage/door` creates `projects/garage/door/`.

## `RuntimeError: chumicro_sockets.sockets_factory not available`

`MQTTClient.from_config(...)` and the other network clients' `from_config` raise this when the board has no `chumicro_sockets`, the library that opens network connections. `library add` installs it alongside the libraries that need it, unless you answered no when it asked to pull it in. Add it:

```bash
python3 run.py library add chumicro_sockets
```

If you build your own connections on purpose, hand one in with `transport_factory=` (or `socket=` for MQTT and NTP) instead.
