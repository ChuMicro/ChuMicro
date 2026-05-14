# Decision 0038: Workspace bootstrap via clone, not pip-installed scaffolder

Status: `accepted`
Date: `2026-04-26`
Related: Decision 0029 (project workspace shape — restores §1's intent), Decision 0032 (libraries vs workbench split), Decision 0029 §9 (three-zone ownership model).

## Context

Decision 0029 §1 stated the workspace is "a git repo (or zip) containing `run.py`, configuration files, and an empty `things/` directory." Phase 4b drifted — a `chumicro-workspace-template` workbench package was published with a `_payloads/default_template/` tree of 12 starter files, an `apply.py` that copies the payload to a directory, and an `update` command that re-flows tool-owned paths from the package's bundled payload. Bootstrap became:

```
pip install chumicro-workspace-template
chumicro-workspace-template init my-house
cd my-house && python run.py setup
```

Three things are wrong with that shape:

1. **The skeleton is invisible until the tool runs.** A user evaluating ChuMicro can't browse the workspace tree on GitHub. They have to install a package and run a CLI to see what they'd be getting.
2. **`pip install` of an unfamiliar package as the entry point is the wrong trust handshake.** The mono-repo itself uses `git clone` + `python scripts/run.py setup`. The workspace bootstrap should match.
3. **Template logic hides inside a Python package.** The `_payloads/default_template/` tree, `dot_gitignore` rename trick, and `apply.py` walk are all invisible to a user who just wants to read a starter workspace's source.

`chumicro-workspace-template` and `chumicro-workspace-runtime` were also two packages doing one job: `template` owns scaffolding, `runtime` owns commands the workspace runs daily. With the template baked into a real repo, the package-level split has nothing to distinguish.

## Decisions

### 1. The canonical workspace template lives in a separate Git repo

`ChuMicro/ChuMicro-Workspace-Template` (private, flagged as a GitHub template repo; goes public when the rest of ChuMicro goes public). The repo's tracked tree is the workspace skeleton — `run.py`, `workspace.yml`, `projects/_template/`, `_templates/` (template sources for files like `secrets.yml`; see §5), etc. README and AGENTS.md at the repo root explain what the workspace is. Browsable on GitHub before any install.

Bootstrap is either:

```
# A. GitHub UI: click "Use this template" → fresh repo, then clone it
# B. Direct clone:
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workspace-Template my-house
cd my-house && rm -rf .git && git init
python3 run.py setup
```

`python3 run.py setup` is self-bootstrapping — creates `.venv`, installs `chumicro-workspace` (and transitive deps), then re-execs in the venv for any subsequent command. No prerequisite pip install of any ChuMicro package; system Python 3 is enough.

Third parties can fork the template repo, customize, and consume their fork by changing the clone URL. Same shape as forking any cookie-cutter starter.

**Rejected:** keeping the template as `_payloads/` inside a workbench package. Hides the skeleton, forces a pip-install entry point, makes forking awkward.

### 2. `chumicro-workspace-runtime` → `chumicro-workspace`

Rename the package. The "-runtime" suffix existed to distinguish the daily-command package from the template-scaffolder package. With template scaffolding folded in (decision 3 below), the suffix distinguishes nothing. `chumicro-workspace` is the one CLI a workspace user reaches for.

The folder `workbench/workspace-runtime/` becomes `workbench/workspace/`. The Python package `chumicro_workspace_runtime` becomes `chumicro_workspace`. PyPI name `chumicro-workspace-runtime` becomes `chumicro-workspace`. CLI `chumicro-workspace-runtime <cmd>` becomes `chumicro-workspace <cmd>`. The local `python run.py <cmd>` shim continues to forward unchanged, just to a renamed import path.

VERSION stays at 0.0.0; nothing was published under the old name.

### 3. `init` and `update` fold into `chumicro-workspace`

`chumicro-workspace-template` (the workbench package, not the repo) is deleted. Its public surface — `init`, `update`, three-zone manifest — moves into `chumicro-workspace` as subcommands:

- `chumicro-workspace init <target> [--from <git-url>] [--ref <ref>]` clones a template repo to *target*, runs `rm -rf .git`, runs `git init`. Defaults `--from` to `https://github.com/ChuMicro/ChuMicro-Workspace-Template`. Thin wrapper; the *real* canonical bootstrap path is the documented `git clone` recipe.
- `chumicro-workspace update [<target>] [--from <git-url>] [--ref <ref>]` fetches the template upstream into a temp clone and re-flows files in the `Zone.TOOL_OWNED` slice (using the same three-zone manifest from Decision 0029 §9, generalized to the whole tree). User-owned and init-only zones are skipped.

The three-zone manifest lives inside `chumicro-workspace` (carried over from `chumicro_workspace_template.manifest`) so the package can classify upstream files without having to read a manifest from the template repo. The classification is logically owned by the *tooling*, not by individual templates — every template a user might fork shares the same workspace shape.

**Rejected:** retire `init` / `update` entirely and document only the `git clone` recipe. The recipe remains the primary path, but `update` (re-flow tool-owned files when the template evolves) is genuine work that benefits from a single command. `init` as a thin wrapper costs almost nothing and gives users a forkable name to invoke when they don't want to remember the recipe.

### 4. The `_payloads/default_template/` tree migrates into the new repo, with templated config files

The 12 files in `workbench/workspace-template/src/chumicro_workspace_template/_payloads/default_template/` move to the new repo's root with the `dot_*` rename pre-applied (so `dot_gitignore` becomes `.gitignore` in the repo, not a payload trick). The `run.py` shim is replaced with a self-bootstrapping version (creates `.venv` + installs `chumicro-workspace` on first run; re-execs for subsequent runs).

After migration, `workbench/workspace-template/` is deleted from the mono-repo. No transitional fallback period — at 0.0.0 there are no consumers to break.

### 5. Templated config files generated at setup, never copied by hand

Files the user owns and edits — `workspace.yml` is the canonical example (Decision 0057 retired the original `secrets.yml` + `!secret` design in favor of one gitignored file) — should not ship as `.example` files the user has to copy. Same pattern as the chumicro mono-repo's `scripts/generate_config_files.py`: ship a *template source* and have the tooling materialize the *user-edited file* at preparation time.

Concretely, the template repo carries a top-level `_templates/` directory:

```
_templates/secrets.yml      # comments + key skeleton
_templates/...              # any other "you'll edit this" file
```

`python run.py setup` walks `_templates/` and, for each entry, creates the corresponding file at the workspace root if it does not already exist. The user never sees a `.example` file or has to remember to `cp`. They open `secrets.yml` directly, edit, save.

Three-zone classification absorbs the new directory:

- `_templates/` is **tool-owned** — `update` re-flows new versions of the template sources as the canonical template repo evolves.
- The materialized files (`secrets.yml`, etc.) are **user-owned** — `update` never touches them.

The current `secrets.yml.example` shape is retired — there is no example file alongside the real one, just a template source under `_templates/` and the user's actual file.

This pattern applies to any future workspace-root file that is "user-edited but starts from a skeleton." `workspace.yml` and `devices.yml` keep their current shape (shipped directly as user-owned skeletons; `add-device` mutates `devices.yml` in place) — moving them into `_templates/` would be more indirection without payoff. Re-evaluate if a third such file emerges with the same shape as `secrets.yml`.

**Rejected:** keep `secrets.yml.example` and document a manual `cp` step. Forces the user to remember the copy + creates a third file (`example`, `actual`, `gitignore`) that adds nothing.

### 6. `check-version` allows 0.0.0 → 0.0.0 self-bumps

The current `scripts/check_version.py` requires VERSION bumps when a package's tracked files change. While packages sit at 0.0.0 (pre-release), this manifests as nuisance "you bumped a file but not VERSION" CI failures. The check is updated to treat 0.0.0 as a frozen pre-release floor — changes against a 0.0.0 baseline don't require bumps, and the gate only kicks in once a package crosses to a non-zero version.

This is independent of the template pivot but is bundled into the same change because the rename of `chumicro-workspace-runtime` would otherwise force a VERSION bump that has no semantic meaning at 0.0.0.

## Consequences

- One fewer publishable package (`chumicro-workspace-template` deleted).
- One renamed package (`chumicro-workspace-runtime` → `chumicro-workspace`).
- One new repo (`ChuMicro/ChuMicro-Workspace-Template`), private until the rest of ChuMicro goes public.
- The bootstrap docs change: the canonical README path becomes "git clone + setup," not "pip install + init."
- `python run.py update-template` (or equivalent) becomes a `chumicro-workspace update` invocation rather than a `chumicro-workspace-template update` invocation.
- Decision 0029 §1's "the workspace is a git repo" promise is restored; Phase 4b's pip-install-scaffolder shape is retired.
- Phase 4b in `plans/workstreams/archive/project-workspace.md` gets a closing-summary update reflecting the pivot; Phase 4c is dissolved into this decision (no separate "companion repo phase" — the repo IS the bootstrap).
- Phase 7 (first sensor project template) executes against the new shape.
