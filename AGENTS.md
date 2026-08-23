# ChuMicro Development Ecosystem

> Operating manual for AI coding agents.
> Human contributors use [CONTRIBUTING.md](CONTRIBUTING.md).

Cross-runtime Python libraries for embedded boards.

CircuitPython and MicroPython deploy to hardware. CPython is the host test seam,
never a deployment target. Minimum board class is 256 KB RAM and 2 MB flash, of
which roughly 800 KB is usable
([Decision 0015](plans/decisions/0015-board-architecture-support.md)).

## Ground rules

When two instructions conflict, the higher one wins.

1. **The user's instruction in this session.**
   It overrides everything below it, this file included.
   Follow it, and name the rule it displaces.
2. **This file.**
3. **The [`.claude/rules/`](.claude/rules/) file for the tree being edited.**
4. **The skill in [`.github/skills/`](.github/skills/) named for the task.**
5. **Accepted decisions in [`plans/decisions/`](plans/decisions/).**
6. **[`docs/contributing/`](docs/contributing/).**

Two items at the same level that disagree: stop and ask. Never resolve a
conflict by picking the more convenient side.

Destructive and outward-facing actions take one confirmation at any rank:
force-push, `reset-board`, `deploy --wipe`, deletions, anything leaving this
repo. The confirmation is a check, not an override. Once the user confirms,
proceed without asking again.

Do not game a rule to satisfy its metric. A rule that has to be worked around to
be met is a rule to break openly and say so.

`CLAUDE.md` loads this file and holds no rules of its own. Never start a second
rules file beside it; `CHU026` flags one.

## Research

Read one file and run one command at a time. A pipeline that returns four
matching lines is not research.

- Never `grep | head` your way toward an answer on a judgment task.
  Read the file. If it is long, read it in ranges.

- Run one command, read all of its output, then choose the next one.
  Chained commands hide which one failed.

- Neither the exit code nor the first line is the verdict. Read the whole
  output. `run.py lint` prints ruff's `All checks passed!` first and the
  `chumicro-checks` findings after it, so `| head` reports green on a red run.
  Never `head` or `tail` a gate. Redirect it to `.scratch/` and read the file.

- Failure is suppressed or deferred by design under `--no-fail-on-traceback`,
  `--allow-no-tests`, `--skip-health-check`, and `--skip-demo`, and inside the
  per-target loops in `sweep-devices`, `deploy --all-devices`, and
  `deploy --all-projects`.

- Run `--help` before guessing a flag. `run.py test --help` and several others
  carry an `examples:` block.

- `chumicro-workspace deploy --dry-run` prints the exact file map without
  touching a board. It is the reference for what deploy ships.

- Web-search anything version-specific or newer than the model cutoff.

Where answers live:

| Question | Where the answer is |
|---|---|
| What does this command do | `--help`, then [`scripts/run_tasks/`](scripts/run_tasks/) for the task body |
| Why is it built this way | [`plans/decisions/`](plans/decisions/) |
| How do I implement this | [`plans/patterns.md`](plans/patterns.md) |
| What did a board actually do | [`plans/field-notes/`](plans/field-notes/) |
| What is in flight | [`plans/next-up.md`](plans/next-up.md) |
| What does a `CHU0NN` flag | the rule module's docstring in [`workbench/checks/src/chumicro_checks/rules/`](workbench/checks/src/chumicro_checks/rules/) |
| How does a runtime built-in behave | `.tools/`, after `run.py prepare-micropython` / `prepare-circuitpython` |
| What ships to PyPI | [`libraries/README.md`](libraries/README.md), [`workbench/README.md`](workbench/README.md) |
| How do I run tests on hardware | [`device-testing.md`](docs/contributing/device-testing.md) |
| How does versioning and release work | [`releases.md`](docs/contributing/releases.md) |
| How do I recover a wedged board | [`docs/troubleshooting/`](docs/troubleshooting/) |

## Commands

Activate the venv first with `source .venv/bin/activate`. If bare `python` is
missing, the shell did not inherit it.

### `python scripts/run.py`: repo gates

`--help` lists all 31 subcommands. These carry the daily work.

| Command | Does | Example |
|---|---|---|
| `preflight` | Full CI mirror: lint, tests, examples, compatibility, build | `run.py preflight --coverage-threshold 94` |
| `test` | CPython unit tests, changed packages by default | `run.py test -k timing/test_ticks/ticks_add --no-cov -x` |
| `lint` | Ruff plus `chumicro-checks` across the workspace | `run.py lint` |
| `test-all-runtimes` | Unit tests on CPython, MicroPython, and CircuitPython unix ports | `run.py test-all-runtimes --libraries timing,runner` |
| `test-unit-on-device` | Cross-runtime unit suite on real boards, RAM-preferred | `run.py test-unit-on-device --library mqtt --per-file` |
| `test-libraries-functional` | Hardware-gated functional tests on connected boards | `run.py test-libraries-functional --library buttons --runtime both` |
| `sweep-devices` | Demo smoke plus functional suite across every board in `devices.yml` | `run.py sweep-devices --functional` |
| `check-version` | VERSION bump enforcement for the change-set | `run.py check-version --base origin/main` |
| `check-api` | Public API diff against the last release tag | `run.py check-api` |
| `check-size` | Fails when a library outgrows `size-budgets.toml` | `run.py check-size` |
| `verify-examples` | Import-checks `libraries/<lib>/examples/` under CPython | `run.py verify-examples --libraries timing` |
| `new-library` | Scaffolds a library, or a host tool with `--workbench` | `run.py new-library gpio` |
| `bench` | Perf and heap benches on both unix ports against the baseline | `run.py bench --update-baseline` |
| `setup` | Reinstall dependencies and regenerate IDE config | `run.py setup` |
| `prepare-micropython` / `prepare-circuitpython` | Clone and build runtime source into `.tools/` | `run.py prepare-circuitpython` |

Flags worth knowing:

- `preflight --with-functional` adds the hardware tail.
  `--with-device-unit` appends the on-device sweep.
- `preflight --quiet` buffers per-phase output and replays the full transcript
  under `== <phase> ==` headers. This is the right mode for an agent run.
- `test --libraries a,b` scopes to named packages.
  `--allow-no-tests` lets an empty filter pass instead of failing.
  `--elevated-packages` raises the coverage bar on changed libraries only.

### `chumicro-workspace`: the front door

Project deploys, device management, firmware, and workspace health. Most agent
work routes here. `--help` lists all 27 subcommands.

This mono-repo has no `projects/` tree, so `deploy <project>` applies to user
workspaces rather than here. To put code on a board from this repo, use
`deploy-example`, `demo`, or `run.py test-libraries-functional`.

| Subcommand | Does | Example |
|---|---|---|
| `deploy [name]` | Ships app code plus merged config to a board | `chumicro-workspace deploy <project> --tail 30` |
| `deploy --dry-run` | Prints the file map, writes nothing | `chumicro-workspace deploy <project> --dry-run` |
| `deploy-example` | Ships one `libraries/<lib>/examples/<name>.py` | `chumicro-workspace deploy-example timing periodic_tick --no-tail` |
| `deploy-example --list` | Lists every example, optionally scoped to a library | `chumicro-workspace deploy-example --list timing` |
| `repl` | Interactive REPL, or `--tail SECONDS` to follow output | `chumicro-workspace repl --tail 60 --device pi-pico-w-circuitpython-board` |
| `devices` | Prints every entry in `devices.yml` | `chumicro-workspace devices` |
| `discover` | Lists the serial ports the host sees right now | `chumicro-workspace discover` |
| `probe` | Prints the runtime identity the board reports | `chumicro-workspace probe --device pi-pico-w-micropython-board` |
| `add-device [id]` | Probes a board and registers it | `chumicro-workspace add-device back-porch-mp --runtime micropython` |
| `status` / `doctor` | Health snapshot; `doctor` adds a Python-version and `run()` AST scan | `chumicro-workspace doctor --fix-fskit-wedge` |
| `demo` | Built-in hello-world to the active device, about 5 seconds | `chumicro-workspace demo` |
| `dump-config` | Prints the merged runtime config a project would receive | `chumicro-workspace dump-config <project>` |
| `config-validate` | Validates merged config against every reachable library manifest | `chumicro-workspace config-validate <project>` |
| `install-firmware` | Downloads and flashes firmware | `chumicro-workspace install-firmware --device tinys3-cp` |
| `reset-board --yes` | Wipes the user filesystem. Exits 2 without `--yes` | `chumicro-workspace reset-board --device tinys3-cp --yes` |

Deploy flags worth knowing:

- The default is clean-slate: the deploy removes anything that is not the new
  payload or a keep-set file (`boot.py`, `boot_out.txt`, `_chu_kv.msgpack`).
- `--no-wipe` is additive and leaves other board files in place.
  `--wipe` erases the keep set too, for corruption recovery.
- `--device <id>` or `--runtime <name>` picks the target.
  `--all-devices` and `--all-projects` loop and do not abort on one failure.
- `--import-graph` ships only transitively imported modules.
  `--boot-shim` is auto-detected for a project with `app.py` exporting `run()`.
- `--non-interactive` is auto-detected from the TTY and fails fast with a
  distinct exit code per failure mode.

### `chumicro-deploy` and `chumicro-repl`: lower level

Reach for these only outside a workspace context.

| Command | Does | Example |
|---|---|---|
| `chumicro-deploy probe` | Probes a board's runtime identity | `chumicro-deploy probe --address /dev/cu.usbmodem1101` |
| `chumicro-deploy deploy` | Raw file push by directory or file map | `chumicro-deploy deploy --help` |
| `chumicro-deploy flash-firmware` | Downloads a firmware URL and flashes it | `chumicro-deploy resolve-firmware-url --help` |
| `chumicro-repl --address` | Serial REPL with traceback highlighting | `chumicro-repl --address /dev/cu.usbmodem1101 --tail 30` |

Never bypass `chumicro-workspace deploy` for a project tree. Both front doors
run the one device-staging path, a diff followed by `rsync --delete`. The
transport primitives underneath (`deploy_files`, `delete_files`,
`list_files_in_scope`) stay internal to `chumicro_deploy`; consumers stage
through `Deployer.deploy_diff()`, and `CHU034` enforces it.

## Workflow

### Gates

- Pass preflight before every commit, doc-only and plans-only included.
  If preflight is already red on `main` from someone else's change, stop and
  say so.

- Close every unit of work with the
  [`task-checkpoint`](.github/skills/task-checkpoint/SKILL.md) skill.
  A unit of work is one commit subject. Several per session is normal.

- A public-API or behavior change takes one `VERSION` bump per change-set,
  never one per commit. One bump anywhere in the set satisfies the gate, so a
  full audit pass is a single bump and a pull request never carries a version
  ladder for one library. `check-api` names the minimum level.

- A behavior-only change still bumps `patch`, so users see it land in their
  version pin. That includes a changed exception message or any other shipped
  string. A `src/*.py` diff limited to comments and docstrings is not
  release-relevant and needs no bump
  ([Decision 0113](plans/decisions/0113-docstring-only-not-release-relevant.md)).
  Detail in [releases.md](docs/contributing/releases.md).

### Evidence

- Anchor every claim to a file, symbol, test, or command output.

- Re-derive any concrete claim from a sub-agent or a `plans/handoffs/` file
  before building on it, `[VERIFIED]` included. Never trust a summary.
  Re-read the file or re-run the smallest failing check.

- Re-read a file after a "modified externally" notice.
  Re-assert `pwd` after any external change.

- Re-run the failing check yourself after the user performs a recovery action
  such as a replug, a `reset-board`, or an unwedge. "Done" from the user is the
  signal to verify, not proof the fix worked.

### Scope

- Fix what was asked. No new features, abstractions, or speculative error
  handling. Name pre-existing issues instead of fixing them, except under the
  carve-out below.

- Carve-out: a stale flag name, a renamed identifier, a dead reference, or
  prose the current code contradicts gets fixed in place and noted in the
  commit body. Anything that needs research stays out.

- Remove what your change orphans: unused imports, variables, functions, tests.
  When a pre-existing inconsistency is directly material to the task, such as
  writing a regex to handle drift you could instead normalize, surface the
  choice rather than papering over it.

- A feature that exists only in code is incomplete. Docs, ADRs, planning files,
  scaffold templates, and CI are part of the deliverable. Update the docs your
  change made wrong in the same commit, including this file, ADR bodies, CI
  workflows, and scaffold templates. A drift class that can be linted must be
  ([Decision 0074](plans/decisions/0074-drift-mechanization-as-project-policy.md)).

### Git

- `main` is PR-only and the only long-lived branch
  ([Decision 0019](plans/decisions/0019-branching-model.md),
  [Decision 0120](plans/decisions/0120-main-is-pr-only.md)).
  Work on `fix/…`, `docs/…`, or `feature/…`, push the branch, open a PR.
  Never push to `main`; the ruleset rejects it for every actor, agent sessions
  included. The one other branch 0019 allows is a short-lived
  `release/<library>-vX.Y.x` cut from a stable tag to hotfix an older release,
  deleted once the patch ships.

- Stage with explicit pathspecs and run `git --no-pager diff --cached --stat`
  before every commit. Never `git add .` or `git add -A`; parallel sessions,
  linter hooks, and in-flight user work all land in the same files.

- Pass commit messages through a single-quoted heredoc,
  `git commit -m "$(cat <<'EOF' … EOF)"`, so backticks and `$` pass literally.
  No `Co-Authored-By` trailer. Mechanics live in the
  [`git-commit`](.github/skills/git-commit/SKILL.md) skill.

- Never commit unsolicited.

- Never `git commit --amend`. A failed pre-commit means the commit did not
  happen.

- Never `git stash`. Scope a commit with pathspecs, and drop staged work with
  `git restore --staged <path>`.

- Never bypass git safety without an explicit ask: no `git config` edits, no
  `--no-verify`, no `--no-gpg-sign`, no force-push to `main`, and none of
  `reset --hard`, `checkout .`, `restore .`, `clean -f`, or `branch -D`.

### Housekeeping

- No backwards compatibility before 1.0
  ([Decision 0092](plans/decisions/0092-no-backwards-compat-before-publication.md)).
  No aliases for renamed symbols, no deprecation, no tolerant readers of our
  own retired formats. Break and migrate every consumer in one commit, and let
  tests adapt to code. Cross-runtime shims and tolerance toward external peers
  stay.

- Never hard-code or commit secrets. Wifi passwords, MQTT credentials, and API
  tokens live only in the gitignored `secrets.toml`.

- Pair every lint suppression with the reason.

- Write and edit files with the file tools. Never use `echo`, `printf`, `cat`,
  or a heredoc for file content. Commit messages are the one exception.

- Send large captures to `.scratch/`, which is gitignored.
  Disable pagers with `git --no-pager` or `| cat`.

- Run `python scripts/run.py setup` to fix imports, never `pip install -e`.

### Plans and decisions

- Check [`plans/patterns.md`](plans/patterns.md) for an established pattern
  before writing implementation code.

- Scaffold libraries through the
  [`new-library`](.github/skills/new-library/SKILL.md) skill. It owns directory
  layout, `__init__.py` and `testing.py` placement, test placement, the initial
  `VERSION` seed, `pyproject.toml`, and `__all__`. Reading an existing library
  to copy its layout is a fallback only.

- Route new ADRs through the
  [`new-decision`](.github/skills/new-decision/SKILL.md) skill, and read
  [`plans/decisions/README.md`](plans/decisions/README.md) before editing one.
  An ADR holds context, decision, invariant, rationale, and rejected
  alternatives. Mechanism goes to
  [`plans/workstreams/`](plans/workstreams/).

- A [`plans/workstreams/<name>.md`](plans/workstreams/) file is a directive.
  Execute its next unshipped phase, append one line to `## Validation history`,
  and update `Status:`. Never bounce to the user without a concrete blocker.

- Remove the matching [`plans/next-up.md`](plans/next-up.md) bullet when the
  work lands. One bullet per item, no sub-bullets, no `## Done` section
  (`CHU011`). Update
  [`plans/open-questions.md`](plans/open-questions.md) when an answer lands.

- A `Phase N` reference in a commit subject carries a topic, as in
  `Phase 6. Implement the transport seams`, never a bare `Phase 6`.

- User-specific preferences and per-session context live in the memory system.
  Rules that apply to every contributor live here.

## Working style

- Report the result. No status narration, no restating the request, no recap of
  the steps taken. Session narration belongs in
  [`plans/field-notes/`](plans/field-notes/).

- An error message is a symptom. Capture the next layer with
  `traceback.print_exc()`, a board stdout tail, or the kernel log before naming
  a cause.

- Read the code on both sides before critiquing an architectural split.

- Name the tradeoffs when several approaches work, and ask when the ambiguity
  affects correctness.

- On a judgment task, draft what the ideal version would say from the source
  first, then compare. What your draft holds and the actual lacks is a finding.

- Restate the referent before acting on a terse reply such as *yes*,
  *option 2*, or *drop it* when it could mean more than one thing.

- Execute reversible local work without asking: edits, tests, refactors, and
  plans updates.

- A named next step is a directive. Finishing item N and asking whether to
  continue is an off-ramp.

- Pass `model: "opus"` explicitly when invoking the Agent tool for research,
  audit, or judgment work.

- Rich asks go through the [`surfaces`](.github/skills/surfaces/SKILL.md)
  skill. `AskUserQuestion` handles one small choice; anything larger renders a
  surface.

- Small focused diffs, preflight green, and commit messages that name the rule
  or decision applied.

## Writing tone

Read each sentence aloud. If you would not say it that way to a colleague,
rewrite it. This governs replies and status updates as much as prose written
into files.

Four checks per sentence:

- **Concise.** Cut connectors that restate what the structure already implies.
- **Direct.** Lead with the load-bearing fact.
- **Concrete.** Name real classes, functions, and files. No `shape`, `surface`,
  `the algorithm`, or `the implementation`.
- **Professional.** No colloquialisms, implicit objects, or ambiguous pronouns.

Never ship:

- Em-dashes, enforced by `CHU037`.
- Litotes and disclaimers.
- Empty adjectives: `comprehensive`, `robust`, `seamless`, `cutting-edge`.
- Filler openers and history banners.
- An abstract subject paired with a weak verb.
- An abstract opener restated concretely after a colon.
- `the` in front of a forward reference or a brand name.

Degraded prose gets rewritten from a fresh read of what the thing does. It is
never trimmed again.

Prose documentation also follows
[Documentation tone](docs/contributing/style-guide.md#documentation-tone).
Worked examples, the per-noun article test, and the AI-tic regex live in
[agent-style-guide.md](docs/contributing/agent-style-guide.md).

## Trees

| Tree | Holds |
|---|---|
| [`libraries/`](libraries/) | Cross-runtime device libraries |
| [`workbench/`](workbench/) | Host-only laptop tools |
| [`support/`](support/) | Shared host packages, kept off the device bundle |
| [`demos/`](demos/) | End-to-end multi-library showcases |
| [`scripts/`](scripts/) | Mono-repo dev tooling |
| [`plans/`](plans/) | Decisions, work queue, workstreams, field notes |
| [`docs/`](docs/) | Contributor and user docs |

Per-tree code rules live in [`.claude/rules/`](.claude/rules/) and load when a
matching file is opened.
