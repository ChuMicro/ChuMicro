# chumicro-workspace

Host-side runtime for ChuMicro project workspaces.  Composes `chumicro-deploy` + `chumicro-repl` with the workspace-shaped pieces those packages don't own: deploy-time config merge, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, an import-graph deploy mode, and the boot-shim layout that lets one board host multiple projects.

- **[Guide](guide.md)** — workflow walkthroughs (day-zero board bring-up, single + multi-project deploys, switch, config merge, firmware, `devices.yml` round-trip).
- **[API](api.md)** — auto-generated reference for the public Python surface.
- **[README](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/workspace/README.md)** — at-a-glance command list and install.

See [Decision 0029](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0029-project-workspace.md) for the workspace contract this package implements, [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench-package pattern, and [Decision 0035](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0035-runtime-config-structure.md) for the config-merge story.
