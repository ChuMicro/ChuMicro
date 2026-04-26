# my-workspace

A ChuMicro project workspace.

## Quickstart

```bash
python run.py setup                                  # editable-install deps
python run.py add-device my-board --address /dev/cu.usbmodem1101 --runtime micropython
python run.py new my-thing                           # scaffold things/my-thing/
# Edit things/my-thing/{config.toml, app.py}
python run.py deploy my-thing
```

See [chumicro-workspace-runtime's guide](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/workspace-runtime/docs/guide.md) for the full workflow walk-through.

## Layout

- `things/<name>/` — your apps.  `def run()` in `app.py`.
- `devices.yml` — registered boards.  Edit via `add-device` or by hand.
- `workspace.yml` — defaults every thing inherits.
- `secrets.yml` — gitignored credentials referenced via `!secret <name>`.
- `libs/` — shared user code.  Things `import` from here.
- `packages/` — gitignored, mirror-cached external libs.
