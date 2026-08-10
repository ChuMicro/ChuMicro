# Workstream: workspace → workbench rename

Status: **template repo renamed 2026-08-10** (user call 2026-08-10): GitHub repo is now `ChuMicro/ChuMicro-Workbench-Template` (rename redirect live, template flag intact), and the product concept is renamed with it — the fork-and-own project repo a consumer works in is now "a workbench", not "a workspace".  The maintainer's own fork is `chuxmaker-workbench` (self-hosted Forgejo).  This file tracks the chumicro-side follow-through, none of which is urgent because the GitHub redirect keeps every old URL working.

## Why the collision needs managing

This repo already uses "workbench" for something else: the host-side tools suite under `workbench/` ("workbench packages": chumicro-deploy, chumicro-repl, chumicro-workspace, chumicro-pytest-device, chumicro-checks; Decisions 0032, 0052).  After the rename the word carries two meanings — the tools suite, and the consumer's forked repo — and the workspace CLI package sits at the intersection with the old name (`chumicro-workspace`, the tool that manages workbenches, living at `workbench/workspace/`).  The docs have to either commit to one meaning per surface or finish the rename so the meanings merge.

## Near-term (small PR, mechanical) — LANDED 2026-08-10

Everything in this section shipped in one PR (workspace 0.54.1 → 0.54.2): the constant, the pinned test, the 13 files of doc links, and the two rule comments.  Kept for the record:

1. **`DEFAULT_TEMPLATE_URL`** — `workbench/workspace/src/chumicro_workspace/template_apply.py:79` still points at `.../ChuMicro-Workspace-Template`.  Works via redirect; should say the new name.  The only hard test coupling is `workbench/workspace/tests/test_template_apply.py:128` (`assert DEFAULT_TEMPLATE_URL.endswith("ChuMicro-Workspace-Template")`), which fails the moment the constant changes — update both together.
2. **Doc links (17 sites)** — `INSTALL.md:93`; `README.md:204,207,243` (the `:207` clone command is copy-pasted by users); `CONTRIBUTING.md:328`; `workbench/README.md:21,51,53`; `workbench/workspace/README.md:23,205`; `demos/README.md:17`; `.github/skills/audit-publishable-isolation/SKILL.md:33,131,135` (`:135` is a live grep pattern in an agent skill — silently stops matching post-rename); `.github/skills/audit-workspace/SKILL.md:37`; `.github/skills/audit-docs/SKILL.md:291,424`.
3. **Comment-only** — `workbench/checks` rules `chu008.py:3` and `chu006.py:77` name the old repo in prose; behavior is name-independent.
4. **Historical plans/decisions prose (~45 lines)** — leave as history.

## Deferred: the full rename (size before committing)

Measured 2026-08-10; decide per-surface, cheapest first:

- **Hosted docs path** `chumicro.github.io/ChuMicro/workspace/stable/`: only 4 hardcoded lines (`workbench/workspace/mkdocs.yml:2` site_url + repo_url, `workbench/workspace/README.md:189,199`, `libraries/config/docs/guide.md:157`).  `scripts/docs_deploy.py` derives the publish prefix from the directory name, so renaming `workbench/workspace/` moves the published path automatically; the gh-pages branch keeps a stale `workspace/` tree needing a redirect or prune.
- **`workspace_runtime` boot module**: retired terminology — the live boot shim is `from app import run; run()` and the string survives only in tests/docs negatives (26 lines, 11 files).  Delete the term rather than rename it.
- **CLI entry point** `chumicro-workspace` → `chumicro-workbench`: 1 pyproject line plus hint strings; `runner_invocation()` already routes most hints through `python3 run.py`, shrinking the blast radius.
- **PyPI package** `chumicro-workspace` → `chumicro-workbench`: 509 occurrences / 172 files (plus `workbench/pytest-device/pyproject.toml:40` depends on it).  Needs a PyPI rename strategy (new name + old-name shim release, or a clean break while consumer count is one).
- **Python module** `chumicro_workspace` → `chumicro_workbench`: 722 occurrences / 195 files — the largest mechanical surface.
- **`workspace.yml` filename**: the migration-hostile one.  91 lines across 27 files under `workbench/workspace/src/` (single constant `WORKSPACE_MARKER` at `workspace.py:40`), but every existing consumer repo has the old filename on disk, so it needs a fallback read or an `update`-driven rename.  Also the template's gitignore/docs and the monorepo's own root `workspace.yml`.

Roughly 200 files / ~1,300 lines for everything, ~60% of it historical plans prose that can legitimately stay.

## Interim docs stance (until/unless the full rename)

One meaning per surface: in consumer-facing docs (template repo, workbench/workspace guide) "workbench" means the consumer's repo, and the tools suite is referred to by package name or as "the host tools"; inside this monorepo's contributor docs "workbench packages" keeps its established meaning.  The known collision spots to reword when touched: `workbench/README.md:21` ("Host CLI ... for ChuMicro project workspaces" one row under the workbench-tools heading), `workbench/README.md:23` (third sense of "workspace"), top-level `README.md:228` ("## Bench tools" heading vs `:259` repo-map "workbench/"), `chumicro-workspace new --workbench <name>` (`docs/contributing/workbench.md:25`), and `docs/contributing/workbench.md:51`.
