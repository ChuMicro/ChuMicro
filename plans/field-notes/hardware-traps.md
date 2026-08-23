# Hardware and tooling traps

## CIRCUITPY mount state

Leave the mount alone from the host. No `diskutil unmount`, `eject`, `mount`, or `rm /Volumes/CIRCUITPY*`. Deploy and transport own the mount, and interference defeats the EACCES classifier. Destructive remediation is `chumicro-workspace reset-board --yes`.

## Writing to /Volumes/CIRCUITPY by hand

`cp -r` included. The board auto-reloads the moment the drive changes, so board and host rewrite the same filesystem at once, and on macOS `cp` drops `._` AppleDouble files into the directories being written. FAT directory entries tear under that: the host can list them, `stat` returns EINVAL, nothing can unlink them, and every later deploy fails until `reset-board --yes` reformats.

Deploy through `test-libraries-functional` or `chumicro-workspace deploy`, which quiesce the board first.

## Two CircuitPython boards at once

They mount as `/Volumes/CIRCUITPY` and `/Volumes/CIRCUITPY 1`. That is normal disambiguation, not a wedge; check `chumicro-workspace devices` first. Parallel deploys to two CircuitPython boards race for the mount, so run them one at a time.

## IDE config files

`cd` to the main checkout before editing `.iml`, `.idea/`, `pyrightconfig.json`, or `.vscode/settings.json`. `sync-ide` run from a worktree writes paths that break in main. PyCharm also rewrites `.idea/chumicro.iml` on its own; `python scripts/run.py sync-ide` restores the managed layout.

## replace_all is a literal substring swap

Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).
