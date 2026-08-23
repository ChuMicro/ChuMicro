---
paths:
  - "workbench/**/*.py"
  - "scripts/**/*.py"
---

# Workbench and scripts

CPython-only trees. The library rules do not apply here.

- A workbench package never imports a library package. Use the third-party equivalent (`pyserial`, `ruamel.yaml`, `msgpack`). Embedding device-side code as raw bytes is payload, not an import.
- Every host-side tool that touches hardware exposes a closed-set failure-kind enum, a classifier, and recovery plans in `<package>.recovery`. CLIs wrap entry points in coaching loops. A bare `raise Exception` is a UX defect.
- Every CLI and `scripts/run.py` task supports non-interactive use: TTY detected through `sys.stdin.isatty()`, a `--non-interactive` override, no prompts or tails without a TTY, and a distinct exit code per failure mode. An inherently interactive subcommand documents the requirement and exits cleanly without one.
- `run.py` holds the argument parser and the dispatch table. Task bodies live in [`scripts/run_tasks/`](../../scripts/run_tasks/); edit them there.
