---
name: audit-publishable-isolation
description: Cross-repo audit for leaks of mono-repo-internal concepts into shipped artifacts — PyPI packages, READMEs, generated payloads, the workspace-template starter. Finds run.py / scripts/ / plans/ / Decision NNNN refs, upstream repo names, and directory-shape assumptions. Use when leaks feel sprinkled everywhere or before a release-prep pass.
---

# Publishable-isolation audit

Audit publishable artifacts for leaks of mono-repo-internal concepts.  The principle: **a standalone published artifact should have no awareness of how it's used downstream.**  A `pip install chumicro-foo` consumer doesn't have `scripts/run.py`, hasn't read `plans/decisions/`, and shouldn't be told to run `python scripts/run.py …` from a docstring or error message.  A user who clones the workspace template doesn't care that there's a mono-repo upstream.

This skill is narrower than `/audit-workspace` (which covers library shapes, dep graphs, decision drift) and broader than `CHU006` (which only scans `libraries/*/src/` + `workbench/*/src/` + `support/test_harness/src/` for a closed regex set).  Scope here: every shipped artifact in **both repos** — source, READMEs, generated payloads, error strings, scaffolder output — plus the reverse-direction leaks (the workspace-template knowing about the mono-repo).

## Scope

* **Mono-repo:** `$CHUMICRO_ROOT` (this repo)
  * `libraries/*/{src,README.md}`, `workbench/*/{src,README.md}`, `support/test_harness/src/`
  * Any payload generators in `scripts/` whose output reaches a consumer's machine (config-file generators, bundle-README generators, scaffolders).
* **Workspace-template repo:** `$WORKSPACE_TEMPLATE_ROOT` (sibling checkout of the workspace-template repo)
  * Whole repo — every file a fresh `git clone` of the starter receives.

Argument: none, or `--repo mono` / `--repo template` / `--pattern <N>` to scope.  Default is both repos, all eight patterns.

## What "publishable" means here

| Artifact | Reaches consumer via | In scope? |
|----------|---------------------|-----------|
| `libraries/<name>/src/**` | PyPI sdist/wheel + circup + mip bundle | yes |
| `workbench/<name>/src/**` | PyPI sdist/wheel | yes |
| `support/test_harness/src/**` | PyPI sdist/wheel (via `chumicro-test-harness`) | yes |
| `libraries/<name>/README.md`, `workbench/<name>/README.md` | PyPI long_description | yes |
| `libraries/<name>/docs/**` | published Zensical site | yes |
| Templates / payloads emitted by workbench tools (`secrets_yml_starter.py`, `boot_shim.py` payloads, scaffolder writes) | written to user's filesystem at deploy time | yes |
| Generators in `scripts/` whose **output** reaches a user (e.g. `bundle_manager.py` writes the bundle README; `generate_config_files.py` emits user-facing strings) | indirect — the generator itself is mono-repo-only, but its output ships | yes (audit the **emitted strings**, not the generator's own docstrings) |
| `ChuMicro-Workbench-Template/**` | clone-and-customize starter | yes |
| `scripts/run.py`, `plans/`, mono-repo `AGENTS.md`, internal CI | mono-repo-only — never lands on consumer machine | **out of scope** (talking about run.py inside `scripts/run.py` is fine) |
| Workbench `functional_tests/` and library `tests/` | mono-repo-only | **out of scope** unless they materialize content into a payload |

Tests and `scripts/` source are mono-repo-internal — they can name `Decision NNNN` and `plans/` freely.  The audit only fires when those names cross into something that *ships*.

## The eight patterns

Each pattern is a distinct leak shape with its own search recipe.  The names below are stable — refer to them as P1–P8 in the punch-list.

### P1. User-facing strings naming chumicro-internal tools

A standalone package's runtime error / log / docstring tells the user to "run `run.py`" or "run `scripts/run.py …`" — but the consumer has no `run.py` of their own (mono-repo) or has a different one (workspace template's shim).

**Example seen in the wild:**
```
"Run setup then `add-device <id> --address <port>` (via your workspace's run.py) to register your board for functional tests."
```
This is in `workbench/pytest-device/src/chumicro_pytest_device/plugin.py` — a `pip install`-able PyPI package.  CHU006's current regex requires the `scripts/` prefix, so it misses bare "run.py".

**Search recipes:**
```
grep -rn "run\.py\b" libraries/*/src/ workbench/*/src/ support/test_harness/src/
grep -rn "python scripts/" libraries/*/src/ workbench/*/src/
grep -rn -E "(via your workspace|in the mono-repo|chumicro-style)" libraries/*/src/ workbench/*/src/
# Bare scripts/run.py workflow names — "test-libraries-functional",
# "test-circuitpython", "verify-examples" etc. appear in docstrings
# without the `run.py` prefix, so the run.py grep above misses them.
grep -rn -E "\btest-(libraries-functional|all-runtimes|circuitpython|micropython|workbench-functional)\b|\bverify-examples\b|\bprepare-(circuitpython|micropython|mpy-cross)\b" libraries/*/src/ workbench/*/src/ support/test_harness/src/
# Workstream-file names referenced in comments / docstrings —
# "gap #6 of the workspace-template / dev-and-regular-mode-gaps
# audit" is the same shape as a plans/ ref but the slug appears
# bare.  Catch the audit + cleanup + reliability + followups suffix
# vocabulary the workstream filenames use.
grep -rn -iE "\b[a-z][a-z0-9-]+-(audit|cleanup|followups|reliability|hardening|gaps|research)\b" libraries/*/src/ workbench/*/src/ support/test_harness/src/
```

**Replacement:** generic phrasing that names the user-facing concept, not the upstream tool.  "Register a device with your workspace's CLI" — not "via your workspace's `run.py`".  "Configure with `runtime_config.msgpack`" — not "via `python run.py dump-config`".  For workstream-name leaks, inline the underlying fact ("treat null + absent identically") and drop the workstream-slug pointer entirely — the slug is plans-tree internal and means nothing to a PyPI consumer.

### P2. `Decision NNNN` references in shipped source

ADR pointers that mean nothing to a PyPI consumer who doesn't have `plans/decisions/`.  CHU006 catches `Decision 0NNN` and `ADR 0NNN`; gaps include hyphenated (`Decision-0042`) and lowercase (`decision 0042`) variants.

**Search recipes:**
```
grep -rn -E "\bDecision\s*0?[0-9]{3,4}\b" libraries/*/src/ workbench/*/src/ support/test_harness/src/
grep -rn -iE "\b(decision|adr)[\s-]*0?[0-9]{3,4}\b" libraries/*/src/ workbench/*/src/
grep -rn -E "\bDecision\s*0?[0-9]{3,4}\b" libraries/*/README.md workbench/*/README.md libraries/*/docs/
```

**Replacement:** inline the rule's gist.  "QoS-1 in-flight tracking is per-`packet_id`" — not "per Decision 0014 §3."  Rationale lives in `plans/decisions/`; the ADR pointer stays in mono-repo internals (commit messages, in-tree comments outside `src/`, planning docs).

### P3. `plans/...` references in shipped source

Same shape as P2 but pointing at `plans/patterns.md`, `plans/next-up.md`, `plans/workstreams/*.md`.

**Search recipes:**
```
grep -rn -E "\bplans/[A-Za-z0-9_./-]*(\.md)?\b" libraries/*/src/ workbench/*/src/ support/test_harness/src/
grep -rn -E "\bplans/[A-Za-z0-9_./-]*(\.md)?\b" libraries/*/README.md workbench/*/README.md libraries/*/docs/
```

**Replacement:** inline the relevant fact.  "FIFO queues use `collections.deque`" — not "see `plans/patterns.md` §FIFO queues."

### P4. README / docs telling users to invoke mono-repo tooling

A `pip install chumicro-foo`-able package's README tells the consumer to `python scripts/run.py test --libraries foo`.  PyPI long_description → consumers read this.

**Search recipes:**
```
grep -rn "python scripts/run\.py\|scripts/run\.py" workbench/*/README.md libraries/*/README.md libraries/*/docs/
grep -rn -iE "chumicro mono[\s-]?repo" workbench/*/README.md libraries/*/README.md libraries/*/docs/
grep -rn "carved out of\|extracted from the chumicro" workbench/*/README.md libraries/*/README.md
```

**Replacement:** the package's actual install + test instructions.  `pip install -e .` + `pytest`.  Provenance / "this package was carved out of …" framing belongs in CHANGELOG / release notes, not the README that lands on PyPI.

### P5. Workspace-template knowing mono-repo internals

The starter repo (a fresh `git clone` for users) names the upstream mono-repo, links to its `plans/`, describes itself as a "downstream" or "scaled-down" version, or hard-codes the upstream directory shape (`<chumicro_path>/libraries/*` walks).

**Search scope:** entire `$WORKSPACE_TEMPLATE_ROOT`.

**Search recipes:**
```
cd "$WORKSPACE_TEMPLATE_ROOT"
grep -rn -iE "chumicro mono[\s-]?repo|monorepo" .
grep -rn -E "github\.com/ChuMicro/ChuMicro\b" .
grep -rn -E "\bDecision\s*0?[0-9]{3,4}\b" .
grep -rn -E "\bplans/[A-Za-z0-9_./-]*(\.md)?\b" .
grep -rn -E "<chumicro_path>|chumicro_path/(libraries|workbench)" .
grep -rn -iE "scaled[- ]?down|downstream of|sibling of (internal )?libraries" .
```

**Replacement:** self-describing prose.  The template documents *itself* as a project starter.  The `chumicro_path` dev-mode plumbing stays (it's a real feature for co-developing libraries against a checkout); the docstring just stops describing the mono-repo's directory shape and says "co-develop sibling packages — see `chumicro-dev.toml` for the schema."  Cross-links to mono-repo docs become inline prose.

### P6. Workbench packages naming the workspace-template repo

A workbench package's source / docs / fixtures hard-code the specific GitHub URL `ChuMicro/ChuMicro-Workbench-Template` or assert directory-shape invariants of that one repo.  Default starter URL in `template_apply.py` is fine *as a default* (overridable, configurable), but README prose framing the package as "the package that ships the workspace template" is leak.

**Search recipes:**
```
grep -rn -E "ChuMicro-Workbench-Template|ChuMicro/ChuMicro\b" workbench/*/src/ workbench/*/README.md workbench/*/docs/
grep -rn -E "workspace[- ]template repo" workbench/*/src/ workbench/*/README.md
grep -rn "starter repo\|starter clone" workbench/*/src/   # often paired with implicit assumptions about layout
```

**Distinguish:** a configurable default URL is fine.  Hard-coded URL + prose claiming "this is the canonical one" + functional tests asserting the specific repo's path shape is leak.

**Replacement:** `template_apply.py`'s default URL stays (with a comment noting it's overridable); functional tests use a fixture-controlled URL; READMEs frame the package's role as "renders a starter from any chumicro-shaped template repo," not "ships *the* template."

### P7. Bundle / config / scaffolder generators baking in mono-repo identity

`scripts/bundle_manager.py` writes the bundle README that ships *to consumers*.  `scripts/generate_config_files.py` emits user-facing strings written into user workspaces.  These generators are mono-repo-internal, so audit their **output** — what string the consumer ultimately sees — not the generator's own implementation.

**Search recipes:**
```
grep -rn -E "_SOURCE_REPO|GITHUB_ORG|ChuMicro/ChuMicro\b" scripts/
grep -rn -E "f-?strings? .* (run\.py|scripts/|plans/|Decision \d)" scripts/
# Then trace the literal strings each generator writes — _what reaches the user?_
```

**Distinguish:** the constant `GITHUB_ORG = "ChuMicro"` is fine *if* it parameterises a configurable upstream URL; it's leak if it ends up in copy-pasted prose like "see https://github.com/ChuMicro/ChuMicro for …" emitted to a downstream consumer.

**Replacement:** generators emit generic prose; the upstream URL appears in mono-repo-internal docs (release notes, CHANGELOG) but not in the artifact that lands on a user's machine.

### P8. Test-harness scaffolding in publishable `src/`

Code in `libraries/*/src/` or `workbench/*/src/` that exists *only* to keep test infrastructure stable — `__all__` placeholders that re-export private names solely so `monkeypatch.setattr` paths don't churn, lazy in-function imports introduced to silence import cycles caused by test-extracted modules, "kept around so monkeypatch paths keep working" comment blocks.  These are mono-repo-test-shape concerns leaking into shipped code; a `pip install` consumer has no monkeypatch paths to preserve.

Surfaced during the deploy library audit: an extraction landed re-exports + an `__all__` declaration in `circuitpython_transport.py` whose entire purpose was to keep test patch paths stable.  Per user feedback in that session: *"code that exists to support a test harness that isn't a part of testing.py or a part of mockability shouldn't be in the package code."*

**Search recipes:**
```
# Re-export blocks with a test-stability comment.
grep -rnB2 -E "monkeypatch|test patch|patch path" libraries/*/src/ workbench/*/src/ | grep -iE "re-export|kept around|so tests|so monkeypatch"
# Function-scope imports in publishable src — usually a smell;
# legitimate cases (lazy-loading heavy deps) get a one-line comment
# naming the dep.  Bare ones often turn out to be cycle workarounds.
grep -rnB1 -E "^\s{4,}(from|import) \.[a-zA-Z_]" libraries/*/src/ workbench/*/src/ | grep -B1 -v "pragma: no cover\|TYPE_CHECKING\|noqa: PLC0415"
# __all__ that includes private names (leading underscore) — almost
# always a test-harness re-export tell.
grep -rnB1 -E "^\s*['\"]_[a-zA-Z_]" libraries/*/src/ workbench/*/src/  | grep -B1 "__all__"
```

**Distinguish:**

* Lazy imports that exist to avoid loading a heavy optional dep on every import (e.g. PyYAML inside a config-loader function) are fine — they have a clear one-line "Late import so importing :mod:`config` alone does not pull in PyYAML" comment.
* Public-API re-exports from a parent `__init__.py` are normal — `chumicro_deploy/__init__.py` re-exporting `Device` from `device.py` is *the* public surface, not a test crutch.
* The leak is specifically: re-exports of private names (leading underscore), or `__all__` declarations whose justification is "tests patch this here."

**Replacement:** delete the re-export; update test patch paths to follow the actual definition module (e.g. `chumicro_X.helpers._do_thing` instead of `chumicro_X.transport._do_thing`).  Break import cycles caused by extractions with a shared leaf types module (e.g. `recovery_kind.py` holding the types that both `recovery.py` and `recovery_plans.py` import) instead of lazy in-function imports.  See `/audit-library`'s "Extraction patterns" section.

## Process

1. **Run all eight greps**, both repos.  Use `--include` filters to keep noise down (`grep -rn --include='*.py' --include='*.md' --include='*.toml'`).  Pipe results into `.scratch/audit-isolation-<date>.txt` so the punch-list survives compaction.
2. **Spot-check 3–5 hits per pattern** before reporting.  Greps generate false positives — `Decision` in a class name (`DecisionTreeClassifier`) or `run.py` inside a generator's literal string that *is* meant to land on a user's machine via the workspace-template (legitimate self-reference).  The user's verify-sub-agent-claims memory applies: report only after reading.
3. **Group by pattern, not by file.**  Punch-list shape:
   ```
   P1  workbench/pytest-device/src/chumicro_pytest_device/plugin.py:1092
       "via your workspace's run.py" — generic "register a device with your workspace's CLI"
   P1  libraries/config/src/chumicro_config/section.py:81
       "python run.py dump-config <project>" — drop the run-command suggestion entirely; raise points at the config key
   ```
4. **Score by remediation cost.**
   * **Trivial** — string rephrase, no behavior change.  P1 / P2 / P3 / P4 are mostly trivial.
   * **Modest** — touches docs across repos, requires sign-off on new wording.  Most P5 items.
   * **Structural** — P6 / P7 hits that imply API changes (e.g., parameterising a hard-coded URL).
5. **Two-pass split.**  Don't bundle src/ rephrases with README rewrites in one commit.  Separate diffs: (a) shipped src/ leaks, (b) README + docs leaks, (c) workspace-template leaks, (d) generator-output leaks.  Each commits separately.
6. **Per-batch task-checkpoint.**  Run `python scripts/run.py preflight --coverage-threshold 94` after each commit batch.  Read the `git-commit` skill before committing.
7. **Lint hardening — what's automated.**  Three CHU rules in the [`chumicro-checks`](../../../workbench/checks/) package cover common leak shapes so the manual audit can focus on prose nuance.
   * **CHU006** — mono-repo isolation.  `\bscripts/run\.py\b`, `\brun\.py\b` (bare), `\b(?:Decision|ADR)\s*0\d{3}\b`, `\bplans/(?:decisions|workstreams|next-up|patterns|learnings)\b`, and "chumicro mono-repo" framing.  Walker covers `src/`, `docs/`, `tests/`, `functional_tests/`, `examples/`, `README.md`, and `pyproject.toml`.  Exempts the whole `workbench/workspace/` tree (the package that legitimately owns the workspace shim) and `workbench/checks/` (rule descriptions need to name what they catch).  Suppress with `# noqa: CHU006`.
   * **CHU007** — workbench packages don't import library packages (Decision 0052).  AST scan of `workbench/*/src/`; flags any `import chumicro_<libname>` or `from chumicro_<libname>` where `<libname>` matches a `libraries/` package.  Allows imports of other workbench packages (`chumicro_deploy`, `chumicro_workspace`) and support packages (`chumicro_test_harness`).  Suppress with `# noqa: CHU007`.
   * **CHU008** — workspace-template repo isolation.  Same `LeakRule` machinery as CHU006 with a different scan-root resolver and forbidden-pattern set: bare `run.py` is *allowed* (the template ships its own); forbidden are Decision/ADR refs, `plans/...md` paths, `scripts/run.py`, and "chumicro mono-repo" framing.  Self-no-ops in repos without a `packages/` directory (the template-shape signal), so it's safe to register everywhere; downstream user workspaces and the template starter both pick it up via `pip install chumicro-checks`.
   Each lint addition lands in its own commit *after* the cleanup that makes it green, so adding the rule never breaks an existing build.

## Anti-patterns

* **Don't refactor while auditing.**  The pass produces a punch-list; cleanups land in their own commits per step 5.  Stopping mid-grep to fix one finding loses the cross-pattern view.
* **Don't suppress with `# noqa: CHU006` to clear the audit.**  Suppression is for legitimate exceptions (a string that ships *with* the mono-repo context — e.g. a help message inside `scripts/run.py` itself).  Audit findings are leaks; rephrase, don't silence.
* **Don't conflate the mono-repo and the template.**  P5 (template→mono-repo) and P6 (mono-repo→template) are different bugs with different fixes.  Keep them separate in the punch-list and the cleanup commits.
* **Don't propose deleting the dev-mode plumbing.**  The workspace template's `chumicro_path` argument and `_workspace_template/` materialization are real features; only the **prose** describing them as "the chumicro mono-repo's libraries directory" is leak.  Audit the words, leave the wires.
* **Don't fix README leaks one library at a time.**  Once you've decided on the new wording for "how to test this package," apply it to every workbench / library README in one batch — otherwise reviewers see N inconsistent rephrasings.

## Output format

```
Publishable-isolation audit
============================

Repos audited:
  mono       $CHUMICRO_ROOT
  template   $WORKSPACE_TEMPLATE_ROOT

Pattern hits (P1–P8):

  P1  user-facing strings naming chumicro-internal tools           N hits
      <file:line>  <snippet>  →  <proposed rephrase>
      ...

  P2  Decision NNNN refs in shipped source                          N hits
      <file:line>  Decision <NNNN>  →  inline gist: <proposed>

  P3  plans/... refs in shipped source                              N hits
      ...

  P4  README / docs invoking mono-repo tooling                      N hits
      ...

  P5  workspace-template knowing mono-repo internals                N hits
      ...

  P6  workbench packages naming the workspace-template repo         N hits
      ...

  P7  generators baking mono-repo identity into emitted artifacts   N hits
      ...

  P8  test-harness scaffolding in publishable src/                  N hits
      <file:line>  <snippet>  →  delete + update test patch path

CHU006 lint gaps surfaced:

  - <pattern>: would catch <which findings>; proposed regex: <regex>

Remediation plan:

  Commit 1  P1 + P2 + P3 src/ rephrases (mono-repo)              <N files>
  Commit 2  P4 README + docs rephrases                            <N files>
  Commit 3  P5 workspace-template self-description rewrite        <N files>
  Commit 4  P6 + P7 generator + workbench-package decoupling      <N files>
  Commit 5  CHU006 hardening (lint extensions)                    scripts/check_no_repo_refs.py
```

## Sequencing recommendation

Run after a feature workstream lands and before a release-prep / docs pass.  Couples well with `/audit-workspace` (which surfaces the *structural* drift) — `/audit-publishable-isolation` then sweeps the *prose* drift those structural changes left behind.  Run `/audit-publishable-isolation` last so it cleans up phrasing the structural pass introduced.
