# Decision 0060: `chumicro-checks` package as the home for CHU lint rules

Status: `accepted`
Date: `2026-05-09`
Summary: New `chumicro-checks` workbench package owns CHU lint rules; each rule self-scopes (walks nothing where targets don't exist); per-repo opt-out via `[tool.chumicro-checks] ignore`.
Related: Decision 0032 (workbench host tools), Decision 0052 (workbench packages don't import library packages), Decision 0058 (CHU009 / CHU010), and the workspace-template starter at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template).

## Context

Workspace-internal lint rules numbered `CHU0NN` enforce policies that ruff can't express — naming (CHU001), no mono-repo refs in publishable trees (CHU006), workbench-doesn't-import-library (CHU007), no silent test skips (CHU009 / CHU010), plans-doc brevity (CHU011), no dated narration in comments (CHU012).  All currently live in `scripts/check_*.py` and run as part of `python scripts/run.py lint`.  Suppression syntax is `# noqa: CHU0NN` (`<!-- noqa: CHU0NN -->` for Markdown), with the per-line *why* required.

A new rule, **CHU008**, was sketched as a workspace-template repo isolation lint: flag prose in [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) (and any user workspace cloned from it) that frames the project as a derivative of an upstream — leftover `Decision NNNN` pointers, leftover `plans/...md` paths, "chumicro mono-repo" framing.  Same machinery as CHU006, different forbidden-pattern set.

CHU008 cannot live in `chumicro/scripts/`.  The mono-repo can run scripts there because `scripts/` is right next to the source it lints; the workspace-template repo is a separate Git repo with no `scripts/` tree, and its eventual users (who clone the template into their own workspace) only have what they `pip install`.  A linter that can't reach the template repo can't enforce template-repo isolation.

Two further candidates were captured alongside CHU008 — a *speculative-public-API* check and a *cargo-cult-class-method* check — both of which need to grep multiple repos at once to know if a symbol has zero callers.  That's a different distribution problem from the in-repo CHU rules.

This ADR resolves: where do CHU lint scripts physically live so the template repo (and downstream user workspaces) can run the rules that apply to them?

## Decision

**A new publishable workbench package, `chumicro-checks`, owns the CHU lint rules.**

### 1. Package home

`workbench/checks/` → published as `chumicro-checks` on PyPI.  Console-script entry point is `chumicro-checks`.  Per Decision 0032 this is host-only tooling (CPython); per Decision 0052 it does not import any `chumicro_*` library package — text linting needs no library code.

### 2. Rules ship together; each rule self-scopes

Every CHU rule lives in the package.  Each rule walks the paths it targets — CHU006 walks `libraries/<pkg>/` + `workbench/<pkg>/` + `support/test_harness/`; CHU008 walks the template repo's project trees.  In a repo where its target paths don't exist, a rule walks nothing and passes silently.

Repo-specific rules stay distinct codes (CHU006 *and* CHU008, not one configurable "leak" rule).  Rule codes are stable identifiers — they appear in commit history, `# noqa:` suppressions, and AGENTS.md prose.  Implementation reuse happens via a shared `LeakRule` base class that takes a pattern set + rule code; `LeakRule(code="CHU006", patterns=PUBLISHABLE_LEAK_PATTERNS)` and `LeakRule(code="CHU008", patterns=TEMPLATE_LEAK_PATTERNS)` share the file walker and suppression machinery without conflating diagnostics.

### 3. Per-repo opt-out via `pyproject.toml`

Repos that want to skip a rule that would otherwise apply add it to an ignore list:

```toml
[tool.chumicro-checks]
ignore = ["CHU012"]
```

Default is "all rules on".  Self-no-op handles the common case (CHU006 in the template repo finds no `libraries/` tree to walk and passes); the ignore list handles deliberate opt-out (a user workspace decides it doesn't care about dated-narration in its own notes).

CLI overrides the config: `chumicro-checks --select CHU006,CHU012` or `chumicro-checks --ignore CHU011` for one-shot runs.

### 4. Suppression syntax unchanged

Per-line `# noqa: CHU0NN` (Python, TOML, etc.) and `<!-- noqa: CHU0NN -->` (Markdown) continue to work.  Existing suppressions across the mono-repo migrate untouched.

### 5. Mono-repo plumbing

`python scripts/run.py lint` shells out to `chumicro-checks` after running ruff.  The current `scripts/check_*.py` files retire — their `main()` callers in `run.py` move to a single `chumicro-checks` invocation.  `repo_layout.ROOT` discovery moves into the package as a "find the repo root" helper.

### 6. Cross-repo checks are out of scope

The speculative-public-API and cargo-cult-class-method candidates need to scan multiple repos simultaneously — a `chumicro-checks --workspace ../mono-repo --workspace ../template` shape that conflicts with the per-repo "lint this tree" model above.  Those checks become an agent skill (`audit-cross-repo` or similar) that an agent runs by grepping the relevant repos.  This ADR does not design that skill; it just declares the cross-repo problem out of scope for `chumicro-checks`.

## Rejected

**Fold into `chumicro-workspace`.**  Rejected: couples linting to workspace lifecycle.  Users who want just the linter (e.g. CI on a downstream workspace) drag in the workspace tool's transport / device-registry / firmware deps.  The workspace package's surface is already broad; adding lint rules to it makes its `--help` even harder to scan.

**Stay in `scripts/` only.**  Rejected: the original constraint that triggered this ADR is that CHU008 cannot reach the template repo from `chumicro/scripts/`.  Keeping the status quo means rejecting CHU008 (and any future cross-repo lint with the same shape).

**Generify CHU006 + CHU008 into one parameterized "leak" rule.**  Rejected: rule codes are stable identity.  Conflating them weakens diagnostics ("CHU006: leak" gives less context than "CHU006: mono-repo ref in publishable tree" vs. "CHU008: upstream-derivative framing in template repo") and would require renaming every existing `# noqa: CHU006` suppression in the mono-repo to a new code.  Implementation reuse via a shared `LeakRule` base captures the code-org win without the public-API churn.

**`CHUX001`-style extension rule namespace.**  Rejected: implies a public extension API.  Only the chumicro mono-repo will ever own these rules in practice; the template repo gets the same package with a different `pyproject.toml` config.  An extension namespace adds machinery without adding capability.

**`--strict` CLI flag for the mono-repo vs. looser elsewhere.**  Rejected: binary modes age badly.  An ignore list in `pyproject.toml` is more flexible (each repo lists exactly what it doesn't want), matches every other lint tool's shape (ruff, mypy), and survives future rule additions without "what does --strict include now?" drift.  A `--preset` flag with named presets was considered as a refinement and rejected for the same reason — the config is the durable source of truth; presets would just be sugar.

**Multi-repo CLI for `chumicro-checks` itself.**  Rejected: conflates two problems.  In-repo linting (every current CHU rule + CHU008) and cross-repo grep (speculative-public-API, cargo-cult-class-method) have different invocation shapes, different result aggregation, and different suppression semantics.  Splitting them keeps `chumicro-checks` focused.

## Consequences

- A new publishable package surface, `chumicro-checks`, joins the existing four (`chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`).  Per Decision 0032 it's host-only tooling.
- Existing CHU rules (CHU001, CHU006, CHU007, CHU009, CHU010, CHU011, CHU012) migrate from `scripts/check_*.py` into the new package.  Suppression syntax stays the same; existing `# noqa: CHU0NN` markers across the mono-repo continue to work.
- `python scripts/run.py lint` becomes a thin shell-out: ruff + `chumicro-checks`.  Per-rule callers in `run.py` collapse into a single invocation.
- AGENTS.md "Non-negotiable rules" prose currently links to `scripts/check_*.py` files.  Those links migrate to the package's source layout (`workbench/checks/src/chumicro_checks/rules/`) when the migration lands.  This ADR doesn't pre-emptively edit AGENTS.md — the rule-source pointers update with the move.
- CHU008 unblocks.  The template repo gains a `[tool.chumicro-checks]` block in its `pyproject.toml` enabling the rules that apply to it (CHU008, CHU012); CHU006 / CHU007 / CHU011 self-no-op there because the paths they target don't exist.
- Cross-repo checks (speculative-public-API, cargo-cult-class-method) move to a future agent skill.  This ADR is the right place to capture that they were considered and split out — a future ADR can pick up the skill design when those checks have a forcing function.
- No backwards-compatibility burden: nothing outside this repo and the template repo has shipped against the current `scripts/check_*.py` API, and the public surface (CLI + `# noqa:` syntax) doesn't change.  The migration is a code move, not a breaking change.
- Repo template gets a real isolation gate.  Today the no-mono-repo-refs-in-downstream-repos policy is enforced by hand-review; CHU008 makes it durable lint.
