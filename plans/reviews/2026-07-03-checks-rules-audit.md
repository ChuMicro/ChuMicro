# Correctness hunt: workbench/checks (CHU rule engine)

Repo: mono-repo root @ audit time (tree mid-churn in libraries/demos; workbench/checks untouched).
Method: read engine + all 30 registered rules; every finding below was confirmed by a minimal probe run against the real rule implementation (probe harness in `.scratch/hunt-checks/probe_all.py`, `probe_refined.py`, `probe_engine.py`, `probe_last.py`; probe repos under `.scratch/hunt-checks/repos*/`). Unit lane `python -m pytest workbench/checks/tests -q` is green (532 passed), so none of these are covered by existing tests.

Excluded per brief: the audit-skill voice-question craft-check item and the CHU033-scripts/-rationale item (both tracked in `plans/next-up.md`); rule-policy debates.

---

### K1 · critical · workbench/checks/src/chumicro_checks/rules/chu009_chu010.py:219 — CHU009 never fires on `return`/`pass` ending an `except`, loop, or `with` body

**What happens.** `_silent_return_findings` checks exactly two shapes: a `Return`/`Pass` as the last statement of an `if` body (and real `else` body), and a bare `return`/`pass` that is a direct, non-final statement of the test body. A `return` that ends an `except` handler, a `for`/`while` body (or its `else`), or a `with` body is invisible — yet each of those ends the test early and orphans every assertion below it, which is precisely the silent-PASS class the rule exists to close. The `except OSError: return` form is the canonical "hardware missing → silently pass" shape the module docstring warns about.

**Confirmed trigger** (probe A1; control B1 confirms the if-shape still fires):

```python
# libraries/pkg/tests/test_probe.py — CHU009: NO-FIRE on all four
def test_except_return():
    try:
        hardware = object()
    except OSError:
        return          # ends the test, asserts below never run
    assert hardware is not None

def test_for_return():
    for attempt in range(3):
        return          # ditto
    assert attempt == 2
```

Same file under CHU010: NO-FIRE too (the asserts exist, they're just unreachable) — so nothing in the engine catches this class.

**Blast radius.** The "library tests cannot silently pass" invariant is open for every guard written as try/except or loop-return instead of if-return. A sweep of the current tree (probe_engine.py) found 5 live `pass`-ends-except sites, all benign cleanup today — but the violating form is the most natural thing an agent writes for a hardware-precondition skip, and the gate will green it.

**Suggested fix.** In `_silent_return_findings`, generalize the "last statement of an `if` body" check to the last statement of any compound-statement body reachable in `_ifs_in_scope`-style traversal: `ExceptHandler.body`, `For/While.body` and `.orelse`, `With.body`, `Try.finalbody`. The existing nested-def stop and the final-statement carve-out stay as-is.

---

### K2 · critical · workbench/checks/src/chumicro_checks/rules/chu030.py:182-186 — CHU030 misses `from chumicro_workspace import pipeline` (from-parent import of a forbidden submodule)

**What happens.** For `ast.ImportFrom` the rule tests only `node.module` against the forbidden prefixes. `_FORBIDDEN_PREFIXES` entries like `chumicro_workspace.pipeline` therefore only match when the submodule appears in the `from` clause. Importing the same forbidden module as a *name* from the parent package — `from chumicro_workspace import pipeline` — has `node.module == "chumicro_workspace"`, which matches nothing, and the imported names are never examined.

**Confirmed trigger** (probe C1; control C2 fires):

```python
# demos/blink/driver.py — CHU030: NO-FIRE
from chumicro_workspace import pipeline, device_runner
pipeline.compose()
```

```python
# control — CHU030: FIRE
from chumicro_workspace.pipeline import compose
```

**Blast radius.** The demo-surface contract ("demos may only reach deploy_api") is enforced against only one of the two canonical import spellings. `from chumicro_workspace import pipeline` is arguably the *more* idiomatic spelling; any demo written that way reaches deploy plumbing with a green gate. Same hole for `device_runner`, `deploy_source`, `import_graph`, `device_orchestration`, and the two retired `chumicro_pytest_device` homes. No live instance in `demos/` today.

**Suggested fix.** In the `ImportFrom` branch, additionally test `f"{node.module}.{alias.name}"` for each alias against `_is_forbidden_module`.

---

### K3 · critical · workbench/checks/src/chumicro_checks/rules/chu006.py:109 — bare-`run.py` pattern is dead inside `libraries/*/examples/`, `*/tests/`, and any path with a template-named segment

**What happens.** `_outside_runpy_owners` exempts any file whose path contains a part in `_TEMPLATE_PATH_SEGMENTS = {"packages", "projects", "shared", "examples", "tests"}`. The intent is top-level workspace-template trees, but the check runs over **all** path parts. In the mono-repo, every publishable package has `examples/` and `tests/` subdirectories, so the bare-`run.py` pattern can never fire there — and library `examples/` ship to bundle consumers, which is exactly the audience the pattern protects.

**Confirmed trigger** (probe D, refined): four files carrying `run.py` refs under one package —

```
libraries/pkg/src/mod.py        -> FIRE
libraries/pkg/docs/guide.md     -> FIRE
libraries/pkg/examples/demo.py  -> NO-FIRE   (part "examples")
libraries/pkg/tests/test_x.py   -> NO-FIRE   (part "tests")
```

**Blast radius.** Shipped example scripts (the most-read files in a bundle) may tell consumers to run `./run.py deploy …`, a shim that doesn't exist on their machines, with a green CHU006. Also silently exempts `workbench/*/tests/`. No live instance today (grep clean), but examples are the highest-traffic place for this exact leak.

**Suggested fix.** Resolve the exemption against repo-root-relative paths: only exempt when the *first* part (relative to repo root) is a template segment — which requires threading `repo_root` into the scope predicate (LeakRule currently passes only `filepath`), or pre-computing scan-root-relative paths in `LeakRule.check`.

---

### K4 · critical · workbench/checks/src/chumicro_checks/rules/chu013.py:66-83 — refetch via a `ticks` parameter or an imported `ticks_ms` is never flagged

**What happens.** `_is_ticks_ms_call` only matches calls whose receiver is rooted at `self` (`self._ticks.ticks_ms()`, `self._ticks_ms()`). The dominant DI style in library code passes the ticks provider as a parameter or imports it (`from chumicro_timing import ticks` … `ticks.ticks_ms()` — see `libraries/requests/src/chumicro_requests/generators.py:144`, `libraries/mqtt/src/chumicro_mqtt/client.py:439`). A function that takes `now_ms` and refetches through that parameter breaks the one-instant-per-tick guarantee just as thoroughly, and the rule stays silent.

**Confirmed trigger** (probe H, refined — 0 findings on both):

```python
# libraries/pkg/src/service.py — CHU013: NO-FIRE on both functions
from chumicro_timing import ticks_ms

def poll(now_ms, ticks):
    late = ticks.ticks_ms()   # refetch through DI param
    return late

def drain(now_ms):
    late = ticks_ms()         # refetch through imported name
    return late
```

The `self._ticks.ticks_ms()` control in the same probe fires.

**Blast radius.** The "one shared instant per tick" invariant is enforced only for self-attribute providers. Module-level generator helpers — the shape `chumicro_requests` / `chumicro_sockets` actually use — are entirely outside the matcher, so the rule protects the pattern the codebase is moving *away* from and not the one it's moving *to*.

**Suggested fix.** Extend `_is_ticks_ms_call` to also match (a) `Name` receivers (`ticks.ticks_ms()` for any local/param named binding) and (b) bare `Name` calls where the callable id is `ticks_ms`, keeping the `now_ms is None` guard exemption unchanged.

---

### K5 · critical · workbench/checks/src/chumicro_checks/rules/chu017.py:59-65 — any overclaim sentence containing "no"/"not"/"n't" is exempt

**What happens.** The `_EXEMPT` regex includes `\bnot\b` and `\bno\b` as negation markers. But the exemption is applied per-*sentence*, and "no" appearing anywhere in the sentence — in any role — mutes the finding. An affirmative whole-codebase coverage overclaim that happens to contain the word "no" sails through.

**Confirmed trigger** (probe F, refined — expect 2, got 1):

```markdown
Line-A: The gate holds 95% of shipped code and there are no exceptions.   <- NO-FIRE
Line-C: The gate holds 95% of shipped code, full stop.                    <- FIRE
```

**Blast radius.** The coverage-honesty gate is trivially (and accidentally) bypassed by common intensifiers: "no exceptions", "no gaps", "not counting docs", "with no caveats" — all of which make the overclaim *stronger* while muting the rule.

**Suggested fix.** Narrow the negation half of `_EXEMPT` to negations adjacent to the claim (e.g. `not\s+(?:a\s+)?(?:guarantee|whole|the case)` / `is not|does not|never`) or require the negator within N chars of the percent/overclaim match, keeping the honest-scope-qualifier half as-is.

---

### K6 · high · workbench/checks/src/chumicro_checks/rules/chu002to005_018.py:95-131 — whitespace family never scans package `README.md`, `docs/`, or other package-root files, while the docstring claims tree-wide coverage

**What happens.** `_iter_text_files` walks top-level `scripts/`, `plans/`, `docs/` plus only `src/`, `tests/`, `functional_tests/`, `examples/` under each package. Package-root files (`README.md`, `pyproject.toml`, `mkdocs.yml`, `VERSION`) and the per-package `docs/` tree are never visited. The module docstring (lines 4-7) claims the rules walk "any `.py`, `.md`, … under `libraries/`, `workbench/`, `support/`, `scripts/`, `plans/`, `docs/`". Real packages have exactly these files: e.g. `libraries/mqtt/README.md`, `libraries/mqtt/docs/guide.md`.

**Confirmed trigger** (probes K1/K2 — both NO-FIRE):

```
libraries/pkg/README.md      "# Title   \n…"   (trailing ws)      CHU004: NO-FIRE
libraries/pkg/docs/guide.md  "trailing   \n"                      CHU004: NO-FIRE
libraries/pkg/README.md      "# Title\n\n\n\n"  (4 EOF newlines)  CHU002: NO-FIRE
```

**Blast radius.** CHU002/003/004/018 hygiene silently does not apply to the most user-visible publishable prose (package READMEs, generated `docs/guide.md`) — the exact "doc trees ruff never sees" the package README advertises coverage for. CRLF (CHU018) in a package README would also pass.

**Suggested fix.** Either add `docs` to `_PACKAGE_SUBDIRS` and include package-root `README.md` (the deliberate metadata exclusions can stay), or fix the module docstring + `workbench/checks/README.md` to state the real scope. Coverage extension is the direction that matches the rule's stated purpose.

---

### K7 · high · workbench/checks/src/chumicro_checks/rules/chu027.py:111 — `tokenize.TokenizeError` doesn't exist; a tokenizer-tripping file crashes the whole checks run

**What happens.** `_extract_comment_blocks` guards `tokenize.generate_tokens` with `except (tokenize.TokenizeError, SyntaxError, IndentationError)`. The `tokenize` module has no attribute `TokenizeError` (the real name is `TokenError`; verified `hasattr(tokenize, "TokenizeError") is False` on the repo's Python 3.14.6). When the tokenizer raises (e.g. unterminated triple-quote → `TokenError`), evaluating the except tuple raises `AttributeError`, which propagates out of `CHU027.check` and aborts the entire CLI run — earlier rules' findings are discarded and later rules never run.

**Confirmed trigger** (probe T2):

```python
# libraries/pkg/src/bad.py
x = '''unterminated
```
→ `CHU027 CRASHED: AttributeError: module 'tokenize' has no attribute 'TokenizeError'`

**Blast radius.** Fail-noisy, not fail-silent (preflight still goes red), but the failure is an unrelated traceback that masks every real finding of that run, and any file that trips the tokenizer while parsing (they exist transiently mid-churn — exactly the current tree state) turns the whole gate into a crash. The `except SyntaxError` intent is dead code because `ast.parse`-style errors from `tokenize` are `TokenError`, not `SyntaxError`, on this interpreter.

**Suggested fix.** `except (tokenize.TokenError, SyntaxError, IndentationError)`. Cheap regression test: run CHU027 over a file containing an unterminated triple-quoted string.

---

### K8 · high · workbench/checks/src/chumicro_checks/rules/chu020.py:54-66 — apostrophes in contractions/possessives count as quote delimiters; flanked AI-tic phrases are exempt

**What happens.** `_is_paired_quoted` counts `'` occurrences before the match and requires one after. English contractions and possessives are apostrophes, so a banned adjective with any contraction earlier in the line and any apostrophe later is treated as "quoted data" and skipped.

**Confirmed trigger** (probe G, refined — expect 3, got 1):

```markdown
It's a comprehensive guide, isn't it.                          <- NO-FIRE
A comprehensive guide.                                          <- FIRE
Don't call it robust unless the user's tests prove it.          <- NO-FIRE
```

**Blast radius.** The AI-tic gate on `docs/`, `plans/decisions/`, and `AGENTS.md` has a hole shaped like ordinary conversational prose — the register agent-generated docs drift into. Two apostrophes on the line (one each side) is all it takes.

**Suggested fix.** Treat `'` as a delimiter only when it isn't intra-word: require a non-word character (or start/end of line) on the outside of each counted `'` (e.g. count matches of `(?<![A-Za-z])'` before the match), or restrict the pairing exemption to backticks and double quotes and handle single quotes with an explicit `'phrase'` span match.

---

### K9 · medium · workbench/checks/src/chumicro_checks/_noqa.py:19 — bare-noqa regex prefix-matches prose like `# noqa-tracking`, muting every rule on the line

**What happens.** `#\s*noqa(?::\s*([A-Z0-9, ]+))?` has no boundary after `noqa`. Any comment or prose token *starting with* `# noqa` and not followed by a colon — `# noqa-tracking`, `# noqa-adjacent note`, "the `# noqa` mechanism" in Markdown — matches as a **bare** noqa, which `line_suppresses` treats as suppress-everything for that line. Every noqa-respecting rule (all of CHU001-033 that do per-line suppression) is muted on such lines.

**Confirmed trigger** (probe M1):

```python
# libraries/pkg/src/mod.py — CHU006: NO-FIRE
"""Decision 0042 rationale lives upstream.  # noqa-tracking follow-up"""
```

(The `Decision 0042` leak pattern fires without the trailing token; with it, silence.)

**Blast radius.** Engine-wide suppression primitive: one stray hyphenated tag or prose mention of noqa co-located with a violation greens the line for every rule. Also inconsistent with the repo's own "pair every suppression with a why" discipline — the parser can't tell a directive from prose about directives.

**Suggested fix.** Add a boundary: `#\s*noqa\b(?!-)` (and same for the HTML form), or require end-of-token: `#\s*noqa(?::\s*([A-Z0-9, ]+))?(?=\s|$|#)`.

---

### K10 · medium · workbench/checks/src/chumicro_checks/rules/chu006.py:39-49 — `_under_subdir` matches path segments *above* the repo root; a checkout under `…/workbench/checks/` exempts the predicate-scoped patterns repo-wide

**What happens.** The scope predicates (`_outside_chumicro_checks`, `_outside_chumicro_workspace`) scan the file's **absolute** path parts for an adjacent (`workbench`, `checks`) / (`workbench`, `workspace`) pair. Any repo cloned under a directory whose path happens to contain those adjacent names — `~/workbench/checks/myrepo/…`, a CI workspace, this repo's own `.scratch/` — satisfies the predicate for every file, disabling all `_outside_chumicro_checks`-scoped patterns (plans-paths, scripts/run.py, CHU-code-in-prose, AGENTS.md refs, `.scratch/`; everything except the Decision/ADR pattern, which is `everywhere`).

**Confirmed trigger** (probe E, refined):

```
repos2/e_nest/workbench/checks/userrepo/libraries/pkg/src/mod.py
  containing "plans/next-up.md"        -> CHU006: NO-FIRE
repos2/e_control/…/same file           -> CHU006: FIRE
```

**Blast radius.** Environment-dependent false pass of most of the CHU006 pattern set. Harmless on this laptop's current checkout path; a latent trap for CI runners, worktrees, and downstream users (the package ships to PyPI and advertises "drop it on any workspace").

**Suggested fix.** Compute the predicate against the path relative to the scan root / repo root (same plumbing change as K3: predicates need repo-root-relative parts, not absolute).

---

### K11 · medium · workbench/checks/src/chumicro_checks/rules/chu016.py:66-84 — annotated `__chumicro_runtimes__` declaration disables the rule for the whole file

**What happens.** `_declared_runtimes` only recognizes `ast.Assign`. An annotated assignment (`__chumicro_runtimes__: tuple = (…)`) is `ast.AnnAssign`, yields no declared runtimes, and the rule exits early for the file — every cross-runtime import conflict in it passes.

**Confirmed trigger** (probe N1; control N2 fires):

```python
# libraries/pkg/examples/demo.py — CHU016: NO-FIRE
import board
__chumicro_runtimes__: tuple = ("circuitpython", "micropython")
```

**Blast radius.** One agent "improving" an example with a type annotation silently switches off the flagship-example-crashes-on-the-other-runtime gate for that file. All current examples use plain assignment, so no live victim today.

**Suggested fix.** Handle `ast.AnnAssign` (target `ast.Name`, `node.value` tuple/list) alongside `ast.Assign` in `_declared_runtimes`.

---

### K12 · medium · workbench/checks/src/chumicro_checks/rules/chu001.py:61-73 — comprehension and `async for` targets are not exempted; false-fails on idiomatic Python

**What happens.** `_for_loop_target_ids` collects only `ast.For` targets. Comprehension/generator-expression targets (`ast.comprehension`) and `ast.AsyncFor` targets are `Name(Store)` bindings, so a single-letter comprehension variable is flagged even though the rule's documented intent exempts loop targets ("`for i in range(n):` is allowed").

**Confirmed trigger** (probe I1):

```python
# libraries/pkg/src/mod.py — CHU001: FIRE ("single-letter name 'x'")
total = sum(x for x in values)
```

**Blast radius.** False fail: legit idiom needs a rename or `# noqa: CHU001`. The green current tree implies contributors already route around it, i.e. the rule is shaping code away from ordinary comprehensions (or forcing noqa) — a friction bug, not a gate hole.

**Suggested fix.** Also collect `ast.comprehension.target` (and `ast.AsyncFor.target`) names, including nested-tuple elements, into the exemption set; while there, handle `ast.Starred` and nested `ast.Tuple` elements which the current unpacking loop misses.

---

### K13 · medium · workbench/checks/src/chumicro_checks/rules/chu001.py:84-91 — single-letter import aliases and class names are bindings the rule never sees

**What happens.** `_collect_hits` inspects `Name(Store)`, `arg`, `ExceptHandler.name`, and `FunctionDef` names — but not `ast.alias.asname` (`import struct as s`, `from os import path as p`) or `ast.ClassDef` names (`class T:`). All are single-letter module-scope bindings the rule's contract ("no single-letter … bindings") covers.

**Confirmed trigger** (probe I2 — 0 findings):

```python
import struct as s
from os import path as p

class T:
    pass
```

**Blast radius.** False pass on a small but real class; single-letter aliases are a common compression habit in agent-written code, and the banned-abbreviation check (`import subprocess as cmd`) is likewise dodged via aliasing.

**Suggested fix.** Add `ast.alias` (when `asname` is set) and `ast.ClassDef` to the targets list in `_collect_hits`.

---

### K14 · medium · workbench/checks/src/chumicro_checks/rules/chu002to005_018.py:80-86 — CHU005 opener regex misses multi-line signatures and `async def`

**What happens.** `_BLOCK_OPENER` requires the keyword and the trailing `:` on one physical line. A multi-line `def`/`class`/`if` whose closing `):` sits on its own line never registers as an opener, so a blank line immediately after it is not flagged. `async def` / `async for` / `async with` don't match either (no `async` alternative), nor do `match`/`case` blocks.

**Confirmed trigger** (probes J1/J2 — both NO-FIRE):

```python
def fetch(
    url,
):

    return 1
```

```python
async def fetch():

    return 1
```

**Blast radius.** Multi-line signatures are routine in the workbench tree, so the blank-after-opener style gate quietly doesn't apply to a common function shape. The async variants only matter in `scripts/`/`plans/`/`docs/` code snippets (CHU033 bans async in packaged trees).

**Suggested fix.** Track bracket nesting so an opener that started with `def `/`class `/etc. is recognized when its `:` closes on a later line (or use the `tokenize` module); add `async\s+` as an optional prefix in `_BLOCK_OPENER`.

---

### K15 · medium · engine-wide (e.g. workbench/checks/src/chumicro_checks/rules/chu033.py:97-99) — a file with a syntax error silently passes every AST rule

**What happens.** Every AST-based rule (CHU001, 007, 009/010, 013, 015, 016, 027-docstrings, 030, 033) wraps `ast.parse` in `except SyntaxError: return []`. An unparseable file produces zero findings and no signal that it was skipped.

**Confirmed trigger** (probe L1):

```python
# libraries/pkg/src/mod.py — CHU033: NO-FIRE
import asyncio

async def run():
    await asyncio.sleep(1)

def broken(:      # SyntaxError swallows the whole file
    pass
```

**Blast radius.** Within full preflight other lanes (ruff, pytest) catch broken syntax, so the practical window is narrow — but `chumicro-checks` standalone (its own advertised use: "drop it on any workspace") reports green on a tree whose files it could not read. A deliberate `--select CHU033` run is meaningless against unparseable input with no warning.

**Suggested fix.** Emit a low-cost finding (or at minimum a stderr warning) when a scanned in-scope file fails to parse: `<path>:<line>: CHU0NN file skipped: syntax error` — one shared helper, used by all AST rules.

---

### K16 · medium · workbench/checks/src/chumicro_checks/cli.py:38-48 — nearest-ancestor root discovery makes any package directory a "repo root": silent green from `libraries/<pkg>`, bogus findings from `workbench/checks`

**What happens.** `_find_repo_root` stops at the first ancestor with `pyproject.toml` **or** `.git`. Every package directory in the mono-repo has a `pyproject.toml`, so running `chumicro-checks` from inside one lints that package as the whole repo: most rules no-op (no `libraries/`, `plans/`, `AGENTS.md` under it) and the CLI exits 0 having checked nothing; rules whose scan-tops include generic names (`tests`) fire on the wrong tree with self-exemptions broken (`_SELF_EXEMPT_RELPATHS` are mono-repo-relative).

**Confirmed trigger** (probe S, driving `cli.main([])` directly):

```
cwd=libraries/mqtt    -> exit 0   (green; zero rules had any scope)
cwd=workbench/checks  -> exit 1   with 23 bogus CHU012 findings against
                         the rule's own test fixtures (tests/test_chu012.py)
```

**Blast radius.** Preflight is safe (`scripts/run.py` pins `cwd=ROOT`), but any direct invocation — a developer in a package dir, an editor task, a future hook — gets a confident green (or confident garbage) with no hint the root was wrong. This is the documented resolution order working as written, so the fix is a guard, not a redesign.

**Suggested fix.** Prefer `.git` over `pyproject.toml` in `_find_repo_root` (keep walking until `.git`; fall back to outermost `pyproject.toml` ancestor), and/or print the resolved root on stderr when it wasn't given via `--root`.

---

### K17 · medium · workbench/checks/src/chumicro_checks/rules/chu019.py:64-67 — a marker-carrying record with no parseable `Status:` line escapes all marker checks

**What happens.** `_check_file` returns `[]` when `_STATUS` (`^Status:` at line start) finds nothing, treating the file as "not a decision record". But the file was already selected by the `NNNN*.md` glob, and a filename carrying `-SUPERSEDED-BY-` or `-INERT-` asserts a lifecycle that the body then can't contradict — the exact inconsistency the rule exists to flag. Any styling drift that breaks the regex (`**Status:** accepted`, indented field, missing line) turns the whole rule off for that file.

**Confirmed trigger** (probe P1 — NO-FIRE):

```
plans/decisions/0042-SUPERSEDED-BY-0043-old-thing.md
  # Decision 0042: old thing
  Some prose without any status field.
```

**Blast radius.** The filename-is-the-index invariant degrades precisely on the malformed records most in need of flagging; a botched supersession edit that deletes or restyles `Status:` greens the file.

**Suggested fix.** When `status_match is None` but the stem matches `_PREFIX` (or carries either marker), emit a "decision record has no parseable `Status:` line" finding instead of returning `[]`.

---

### K18 · medium · workbench/checks/src/chumicro_checks/rules/chu028.py:54-63 — fenced code-block *content* hashes as principle prose; identical code samples across ADRs false-fail

**What happens.** `_SCAFFOLDING_PATTERNS` treats the ``` fence lines as paragraph boundaries but the lines *between* fences are collected as normal paragraph content. Two ADRs quoting the same ≥20-token config/code sample get flagged as "principle duplicated".

**Confirmed trigger** (probe Q1 — 2 findings on a shared 20-token fence):

```
plans/decisions/0001-a.md:6: CHU028 ADR principle duplicated across 2 ADRs …
plans/decisions/0002-b.md:6: CHU028 ADR principle duplicated across 2 ADRs …
```

**Blast radius.** False fail: sharing a canonical config snippet or command transcript across two ADRs (a legitimate, even desirable practice) trips the gate and pushes authors toward paraphrasing code samples or sprinkling noqa markers.

**Suggested fix.** Track fence state in `_extract_paragraphs` (toggle on `^\s*```) and treat all in-fence lines as boundaries/non-content, mirroring what the docstring already implies.

---

### K19 · low · workbench/checks/src/chumicro_checks/rules/chu024.py:34-41 — `### Update (…)` and `## Update YYYY-MM-DD` banner variants not matched

**What happens.** The Update pattern requires exactly-`##` (the `\s+` after `##` rejects a third `#`) and a literal `(` after "Update". An h3 banner or a paren-less dated banner passes.

**Confirmed trigger** (repos4 probe — 0 findings):

```markdown
### Update (2026-01-02)

## Update 2026-01-03
```

**Blast radius.** Small: the ADR-banner discipline is dodged by the two nearest-neighbor spellings of the banned shape. Same closed-set fragility applies to `## Updates` (plural) etc.

**Suggested fix.** `^\s*#{2,}\s+Updates?\b` (drop the paren requirement; the dated-revision and revision-narrative patterns already cover prose forms).

---

### K20 · low · workbench/checks/src/chumicro_checks/rules/chu011.py:44-46 — numbered sub-lists evade the sub-bullet cap

**What happens.** The bullet-cap counts only `- ` markers. Sub-structure written as `1.` / `2.` ordered-list items under a top-level bullet is invisible, though it is exactly the "needs structure → promote to a workstream" shape the rule documents.

**Confirmed trigger** (probe O1 — NO-FIRE):

```markdown
- big item with hidden structure:
  1. sub-step one
  2. sub-step two
  3. sub-step three
```

**Blast radius.** plans/next-up.md brevity invariant has an ordered-list-shaped bypass. (Also unhandled: `* ` bullets — same class.)

**Suggested fix.** Count `^\s*(?:[-*+]|\d+[.)])\s` markers in `_count_bullet_markers` / `_is_any_bullet` (top-level detection can stay `- `-only to match the file's convention).

---

### K21 · low · workbench/checks/README.md:8 + workbench/checks/src/chumicro_checks/cli.py:20-25 — doc drift: rule range, missing table rows, and the "exit 2 on bad config" claim

**What happens.**
- `README.md:8` says the package covers "`CHU001`–`CHU026`" and the rule table (lines 42-66) ends at CHU028. CHU029, CHU030, CHU031, CHU032, CHU033 are registered, gating in preflight, and undocumented. (CHU021-023 are absent from both registry and README — consistent, presumably retired.)
- `cli.py` docstring promises exit code 2 for "bad config", but a malformed `pyproject.toml` propagates `tomllib.TOMLDecodeError` out of `load_config` (its docstring says so) → uncaught traceback, interpreter exit 1, not 2. Unknown rule codes in the config `ignore` list are silently tolerated (only CLI flags are validated), which is fail-safe but undocumented.

**Blast radius.** Docs only — the `--list` output is complete and correct; no gate behavior changes.

**Suggested fix.** Refresh the README range/table; either catch `TOMLDecodeError` in `main()` and return 2, or reword the exit-code contract.

---

## Verified-clean areas (for the record)

- CHU014 command-table parity: registered-vs-documented extraction matches the real CLI convention (annotated `subparsers` params; nested `verbs.add_parser` correctly not counted); 0 findings on the live repo.
- CHU019/025/029 header regexes match the live ADR corpus format (`Status: \`accepted\``, `Superseded by: [Decision NNNN](…)`).
- CHU018 CR detection reads raw bytes (correctly bypasses universal-newline translation); line attribution correct.
- LeakRule de-dups overlapping scan roots; `strip_noqa` prevents noqa-directive self-matching.
- Walker: single-file roots, missing roots, egg-info/dist/build/site exclusions, deterministic ordering all behave as documented.
- CHU011 fenced `- ` lines do not inflate a preceding bullet's count (they start new extents — wrong model, benign outcome).
- Exit-code aggregation: findings → 1, none → 0; a crashing rule fails loudly (see K7 for the one crash path found).
- No live instances in the current tree of the K1/K2/K3 violation classes (grep + AST sweep), so no preflight-green violations are being shipped *today*.
