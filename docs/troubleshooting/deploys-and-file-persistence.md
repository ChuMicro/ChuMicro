# Deploys and file persistence

The first week with the deploy tool has two traps that both look like lost data.  A deploy clears files you put on the board by hand, and RAM mode (a deploy mode that runs your code straight from host memory) never writes anything to the board at all, so nothing a run saves survives.  RAM mode is opt-in: deploys go to flash by default, and you reach RAM mode only by setting `deploy_mode: ram` on a device entry in `devices.yml` or passing `--deploy-mode ram`.  This page covers both traps, along with the memory error you hit when a RAM-mode deploy is too big for the board.

## A deploy made my hand-installed libraries and `settings.toml` disappear

Deploys are clean-slate by default.  Each one reconciles the board's filesystem to the project's payload (the set of files the deploy sends) and removes anything that isn't in it, apart from a small keep set: `boot.py`, `boot_out.txt`, and the persistent key-value store blob.  A board-resident `settings.toml` is evicted with a one-time notice because it competes with config-driven wifi.  Libraries you installed by hand with `circup` or `mip`, and files you uploaded yourself, are not in the payload, so a default deploy removes them.

Let the workspace own the board's `/lib` by adding libraries through the tool, which puts them in the payload:

```bash
chumicro-workspace library add chumicro_mqtt
chumicro-workspace deploy <project>
```

To keep hand-managed files in place for a single deploy, pass `--no-wipe`:

```bash
chumicro-workspace deploy <project> --no-wipe
```

`--wipe` is the opposite escape: a full erase before the copy.

## Messages stop after the first publish, or the boot counter never increments (`OSError: [Errno 2] ENOENT` on `/runtime_config.msgpack`)

The board is deploying in RAM mode.  Flash is the default, so something opted in: a `deploy_mode: ram` line on the device's entry in `devices.yml`, or a `--deploy-mode ram` on the command.  RAM mode mounts your host source as `/remote/` on the device and never writes the board's flash or non-volatile memory, so absolute paths like `/runtime_config.msgpack` and any state a previous run saved simply aren't there.  Anything that counts across reboots or reads a file at a fixed absolute path fails.  (background: [Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md))

Put the device back on flash mode, which writes files to the board's own filesystem.  Drop the `deploy_mode: ram` line from its entry in `devices.yml`, or set flash explicitly:

```yaml
# devices.yml
devices:
  - id: my-board
    deploy_mode: flash
```

Or override it for one run:

```bash
chumicro-workspace deploy <project> --deploy-mode flash
```

Heavy networking libraries (mqtt, requests, http_server, websockets) switch to flash on their own.

## `INSUFFICIENT_MEMORY`: the RAM-mode payload exceeds the board's free heap

RAM mode runs your code as an inline payload that has to fit in the board's working memory (its heap).  A fat module, or a tight board like the Pico W with 256 KB, can't hold it, and a large CircuitPython RAM payload can even drop the USB connection instead of raising a clean `MemoryError`.

Drop the RAM pin and deploy in flash mode, which writes to the filesystem instead of loading the whole payload into memory:

```bash
chumicro-workspace deploy <project> --deploy-mode flash
```

Splitting a large module into smaller files helps too.  The deploy already checks free memory, strips comments and docstrings, and sends the payload in chunks; when even one chunk won't fit, it fails early and tells you to use flash.
