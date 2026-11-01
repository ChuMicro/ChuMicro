---
title: "chumicro-workspace: put your project on a CircuitPython or MicroPython board"
---

# chumicro-workspace

**The laptop command that puts your Python project on a CircuitPython or MicroPython board and shows what the board prints.**

`chumicro-workspace` registers each board you plug in, creates a folder for each project, copies a project and every library it imports onto the board, and streams the board's output back to your terminal.  Your WiFi password stays in a `secrets.toml` file on your laptop, and each deploy carries it to the board.

## First five commands

Run these in a workspace made from the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template), in this order:

```bash
python3 run.py bootstrap                     # register the board plugged into USB
python3 run.py new blinker                   # create projects/blinker/ with an app.py for your code
python3 run.py library add chumicro_timing   # fetch a library into the workspace's libraries/
python3 run.py deploy blinker --tail 30      # copy the project onto the board, show 30 s of output
python3 run.py repl                          # open the board's Python prompt; Ctrl-X leaves
```

The template's `run.py` starts `chumicro-workspace` from the workspace's own virtual environment.  In a clone of the ChuMicro repository, or after `pip install chumicro-workspace`, type `chumicro-workspace` in place of `python3 run.py`.

## Documentation

- [Guide](guide.md): a new board's first hour, then every command in depth.
- [API Reference](api.md): the Python modules behind the commands.
- [Start here](https://chumicro.com/ChuMicro/guides/start-here/): from a board in its packaging to your own code running on it.

## Install

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
python3 run.py setup      # creates a virtual environment and installs the tools
```

Or on its own, from PyPI:

```bash
pip install chumicro-workspace
```

`chumicro-workspace` runs on your laptop, so nothing installs on the board.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
