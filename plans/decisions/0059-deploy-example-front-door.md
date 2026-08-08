# Decision 0059: `deploy-example` as the mono-repo front-door command

Status: `accepted`
Date: `2026-05-07`
Summary: `deploy-example <lib> <name>` is the mono-repo front-door command: full precheck on every run, handles four first-touch board states, distinct exit codes for non-interactive use.
Related: Decision [0032](0032-workbench-host-tools.md) (libraries vs workbench split), Decision [0038](0038-workspace-bootstrap-via-clone.md) (workspace bootstrap via clone — sibling onboarding path), Decision [0044](0044-deploy-time-runtime-filtering.md) (`__chumicro_runtimes__` filter on every deploy path), Decision [0047](0047-deploy-mode-flash-default.md) (functional tests default to flash), Decision [0053](0053-recovery-layer-philosophy.md) (recovery layer philosophy — extended here with `NO_PYTHON_RUNTIME`), Decision [0055](0055-config-pipeline-unification.md) (`WithRuntimeConfig` deploy-time merge + validation), Decision [0077](0077-one-device-staging-path.md) (the one device-staging path — partially supersedes §1's separate-`example_source` framing; the rest of this ADR stands), Decision [0078](0078-library-acquisition-is-host-local.md) (host-local library acquisition — the sibling command-collapse in the same phase), Workstream `library-config-aware-refactor` Phase 3, Workstream [`deploy-path-unification`](../workstreams/deploy-path-unification.md) Phase 3.

## Context

The chumicro mono-repo has no first-touch command for "I just plugged in a board, run a library example on it."  Today a contributor must hand-craft a deploy path: register the device via `chumicro-workspace add-device`, manually copy a `circuitpython_*.py` example to `code.py`, populate `secrets.toml`, and hope the import graph + manifest validation passes.  Decision 0038 covers the *user-template-repo* onboarding ladder (Arduino → CircuitPython → user's own project) but says nothing about running an example out of the mono-repo itself, which is where library development, learning, and contribution happen.

Phase 3 of `library-config-aware-refactor` proposed `python scripts/run.py deploy-example <lib> <name>` to fill that gap.  As the design firmed up, the command grew past "ship one example file" — it has to handle four first-touch board states (no device registered / happy path / no Python runtime / port unreachable), support both interactive (human) and non-interactive (agent / CI) modes, run cheap fast prechecks before staging, and reuse the recovery-coaching philosophy of Decision 0053 — without re-implementing any of that machinery.  This ADR is the policy doc; Phase 3 of the workstream is the build plan.

## Decision

### 1. Command shape and home

A new subcommand `chumicro-workspace deploy-example <lib> <name>` lives in [workbench/workspace/src/chumicro_workspace/cli.py](../../workbench/workspace/src/chumicro_workspace/cli/) and uses a new `chumicro_workspace.example_source(library_name, example_name, *, runtime, secrets_toml, project_config=None, library_roots=...)` `FileSource`.  `python scripts/run.py deploy-example` is a thin mono-repo shim that calls into it with `library_roots=<repo>/libraries/`.  Mirrors how `python scripts/run.py add-device` shims `chumicro-workspace add-device` today.

The example is staged through the *one* device-staging path, not a parallel `example_source` implementation: an example is a project through the unified pipeline (a thin shim), per [Decision 0077](0077-one-device-staging-path.md). Example-path resolution (`libraries/<lib>/examples/<name>.py`) and entrypoint renaming (the example file becomes `code.py` on CircuitPython / `main.py` on MicroPython) are the example-specific resolution in front of that shared source + clean-slate + keep-set primitive — they do not fork the stage/delete/keep policy. The rest of this ADR (the precheck stack, the four first-touch board states, exit codes, recovery coaching, `--list`) is unaffected and stands.

### 2. Fast precheck stack — always run, never gated

Every invocation runs the full precheck before staging.  Each check is sub-100ms; together they're the difference between "deploy fails on the board with a cryptic traceback" and "command refuses with a precise diagnosis":

| Check | Layer | Approx cost |
|---|---|---|
| Example file exists at the resolved path | `os.path.isfile` | ~1 ms |
| `__chumicro_runtimes__` marker → required runtime | AST parse | ~5 ms |
| Import-graph walk | `ImportGraphSource` | 20–80 ms |
| Manifest union over walked libs validates merged config | `validate_runtime_config` | ~10 ms |
| Wrong-runtime files filtered from the staged tree | `__chumicro_runtimes__` filter | ~10 ms |
| Board probe (port reachable + runtime banner matches) | `chumicro_deploy.probe` | ~500 ms – 1 s |

The board probe is the only slow check (~1 s).  It runs anyway because its output drives state-(3) classification (Arduino / no Python runtime detected) and lets recovery coaching fire before the deploy attempts to stage.  No `--skip-checks` flag — if a check is too slow to run on every deploy, it doesn't belong here.

### 3. Four first-touch board states

Every `deploy-example` run resolves to one of these four states.  Behavior for each is fixed (rejected: per-state user override flags — too many knobs for a beginner-front-door command).

| State | Detection | Interactive | Non-interactive |
|---|---|---|---|
| **(1) No device registered for runtime** | empty `devices.yml` for runtime | bootstrap wizard ([cli.py:1709](../../workbench/workspace/src/chumicro_workspace/cli/)) → continue deploy | exit 3 + structured stderr hint |
| **(2) Registered, port reachable, probe succeeds** | happy path | deploy + tail | deploy + exit |
| **(3) Registered, port reachable, probe fails** (Arduino / non-Python firmware) | REPL banner doesn't match CP/MP | sub-wizard offers `install-firmware` after explicit consent | exit 6 + structured stderr hint |
| **(4) Registered, port unreachable / busy** | port enumeration | recovery coaching ([recovery.py:48](../../workbench/deploy/src/chumicro_deploy/recovery.py:48)) | exit 4 + recovery hint on stderr |

State (3) requires a new `NO_PYTHON_RUNTIME` member of `chumicro_deploy.recovery.DeployFailureKind` plus a recovery plan that points at `install-firmware`.  This benefits every workbench tool that classifies deploy failures, not just `deploy-example`.

### 4. Interactive vs non-interactive

TTY auto-detection sets the default mode.  Two independent axes that compose with one meta-flag:

| Flag | TTY default | Non-TTY default | Effect |
|---|---|---|---|
| `--auto-register / --no-auto-register` | `--auto-register` | `--no-auto-register` | Fall into bootstrap wizard on state (1) |
| `--tail / --no-tail` | `--tail` | `--no-tail` | Drop into `chumicro-repl tail` after deploy |
| `--non-interactive` | (off) | (on, auto-detected) | Meta-flag: forces both above to off + suppresses every prompt |

State (3)'s firmware-install sub-wizard is *only* available in interactive mode.  Non-interactive runs always exit 6 on state (3) — never auto-flash.

### 5. Distinct exit codes

| Code | Meaning |
|---|---|
| 0 | Deploy succeeded |
| 2 | Precheck failed (file missing, wrong runtime marker, missing config key) |
| 3 | No device registered for runtime, `--no-auto-register` in effect |
| 4 | Deploy itself failed (bubbled from a `DeployFailureKind` with recovery hints on stderr) |
| 5 | Bootstrap wizard canceled by user (interactive mode only) |
| 6 | `NO_PYTHON_RUNTIME` — board has Arduino or unknown firmware |

Distinct codes are load-bearing for agent/CI use — an agent can branch on the code without parsing stderr.

### 6. Destructive-action consent

Flashing firmware overwrites the board's existing program (the user's Arduino sketch, custom firmware, anything they had on the board).  This is destructive and never auto-runs:

- **Interactive**: must prompt y/N, must explicitly state "this will overwrite the current program."
- **Non-interactive**: never auto-flash, ever.  Exit 6 with the structured hint pointing at `install-firmware` so the user (or agent) can issue the command explicitly with full visibility.

This generalizes the AGENTS.md "Executing actions with care" rule for the `deploy-example` surface specifically.

## Rejected

**Wrap each library's example as a project under `projects/_template/` shape.**  Rejected: forces a project directory per example, breaks `examples/<name>.py` discoverability, and conflates "example for a library" with "user's own project."  The example is the example file; ship that, don't repackage it.

**A separate file-source / stage-delete-keep policy for examples.**  Rejected ([Decision 0077](0077-one-device-staging-path.md)): the original framing here ("an example is a single file, not a project; different file source") justified a parallel `example_source` staging path, and that per-context divergence was the disease 0077 exists to stop.  `deploy-example` keeps its *own surface* — the distinct precheck story and first-touch UX above are real and stand — but it stages through the same source + clean-slate + keep-set primitive every deploy uses; an example is a project through that pipeline.  What's rejected is a second *staging policy*, not the `deploy-example` command.

**Auto-flash firmware on detected `NO_PYTHON_RUNTIME` even in non-interactive mode.**  Rejected: destructive without consent.  Agents and CI runners can issue `install-firmware` themselves with full visibility; surprising them with a flash is exactly the failure mode the destructive-action rule prevents.

**Single `--auto` flag spanning every interactive choice rather than three independent axes (`--non-interactive`, `--no-tail`, `--no-auto-register`).**  Rejected: real callers want different combinations.  CI wants no-tail + no-auto-register but might still want bootstrap on a setup script.  The composition is worth the small extra surface.

**Name the command `example` instead of `deploy-example`.**  Rejected: less clear about what it does (deploy a library example to a board).  The `deploy-` prefix anchors it as kin to `chumicro-workspace deploy` and signals "this touches a board."

**Promote `deploy-example` to the workspace-template repo for user-authored libraries.**  Deferred (not rejected): scoped to mono-repo for now per the workstream constraint.  Promotable later if a template-repo user actually asks; the `example_source` shape is general enough.

## Consequences

- A first-time mono-repo contributor runs `python scripts/run.py deploy-example timing circuitpython_blink` and gets to a board running an example in one command.  Pairs with Decision 0038 (which covers the workspace-template repo path); both paths share the bootstrap wizard, recovery coaching, and `__chumicro_runtimes__` filtering machinery.
- Agents and CI runners deploy examples deterministically with `--non-interactive` and parse the exit code instead of stderr.
- `NO_PYTHON_RUNTIME` enters `DeployFailureKind`; every existing workbench tool that classifies deploy failures (`chumicro-deploy`, `chumicro-workspace deploy` / `doctor` / `status`) benefits without further work.
- Phase 3 of `library-config-aware-refactor` becomes the build plan: ~200 LOC `example_source` + ~80 LOC CLI subcommand + ~30 LOC mono-repo shim + ~250 LOC tests + the `NO_PYTHON_RUNTIME` enum addition.
- A future `run-functional-test <lib> <test_name>` command follows the same shape — different file source (`functional_tests/` instead of `examples/`) + invokes `chumicro-pytest-device` instead of `Deployer.deploy`, but reuses every other piece.
- `python scripts/run.py deploy-example --list [<lib>]` ships alongside the main command — discoverability for "what examples are available" is part of the front door, not a follow-on.
- The README's first concrete promise becomes a single command line.  `libraries/timing/examples/circuitpython_blink.py` is the canonical first-time example: pure LED blink, zero config keys, runs on every supported board.
