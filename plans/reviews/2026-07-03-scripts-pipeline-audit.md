# scripts/ correctness hunt — findings

Scope: `scripts/` build/release/publish pipeline + task runner. Every candidate below was
confirmed by reading source and either a probe (in `.scratch/hunt-scripts/`) or an exact
trace through the code + release workflows. No repo files edited; nothing published/pushed.

---

### S1 · high · scripts/bundle_manager.py:522 (build_circup_zips) + :261 (build_bundle) — circup bundles ship stale / removed modules

**What happens.** The mip/circup device bundle is published by overlaying freshly-staged
files onto a *fresh clone of the accumulated bundle repo*, with no delete step:

- `.github/workflows/release.yml:266` and `promote.yml:217`: `cp -r .bundle-staging/* .bundle-repo/`
  merges the new release over the clone (which holds every prior release's files). A module that
  was deleted or renamed between releases is **not** removed from `.bundle-repo`.
- `bundle_manager.build_bundle` (:260-261) stages into `staging_dir/<package>` with
  `mkdir(parents=True, exist_ok=True)` and **never cleans** the output dir first — unlike its
  sibling producer `libraries_channel.stage_libraries_channel` (:119-128), which deliberately
  wipes staging "so a stale library never rides a release."
- `build_circup_zips` then ships whatever is *present on disk*: the source zip globs
  `package_dir.rglob("*.py")` (:522) and the bytecode zip globs `mpy_dir.rglob("*")` (:536)
  over `.bundle-repo`. Any stale `.py` / `.mpy` from a prior release is globbed in.

The mip channel is protected because `build_bundle` regenerates each `package.json` fresh
(:308, :404) listing only current files, and mip fetches only manifest URLs. **circup is
glob-based, so it has no such protection.** A renamed module ships under both old and new
names (import-shadowing risk on device); a deleted library's `chumicro_<name>/` dir persists
in the bundle repo and stays installable forever.

**Confirmed trigger.** Traced end-to-end: fresh `git clone` of the bundle repo (release.yml:260)
→ `cp -r` overlay with no `rm`/`rsync --delete` (release.yml:266) → `build_circup_zips` globs the
merged tree (bundle_manager.py:520-541). Asymmetry verified against the manifest-regeneration
path (mip safe, circup not).

**Blast radius.** circup users (CircuitPython channel) receive removed/renamed modules in both
the `-py-` and `-10.x-mpy-` zips of every release after a source-tree deletion or rename. Pre-1.0
"no legacy support" reduces urgency, but a rename shipping both names can break device imports.
mip/PyPI/source-tree channels unaffected.

**Suggested fix.** Either make `build_circup_zips` ship only files the current `build_bundle`
run declared (thread the staged file list through instead of re-globbing the repo), or add a
delete-sync in the workflow (`rsync -a --delete .bundle-staging/ .bundle-repo/` per package dir,
preserving `.git`), or have `build_bundle` wipe each `staging_dir/<package>` before staging like
`libraries_channel` does. The glob-then-ship in `build_circup_zips` is the load-bearing gap.

---

### S2 · medium · scripts/run.py:1056 + :1178 (_PytestOutputFilter) — ANSI-colored pytest summary parsed as `0 passed` (display-only; gates verified safe)

**What happens.** `_PYTEST_RESULT_FULL` (:1056) anchors on `^=+`, and `_PYTEST_SLOW_HEADER`/
`_PYTEST_COVERAGE_FAILURE` similarly match unstyled text. Under a `FORCE_COLOR` shell, pytest
wraps its summary in SGR escapes (`\x1b[32m===== …5 passed… =====\x1b[0m`), so the line no
longer starts with `=`. `consume()` returns `False`, the colored line leaks to the log
unfiltered, and `passed`/`skipped`/`deselected`/`duration_s` all stay 0. No ANSI stripping
exists anywhere in `run.py` or `shared.py`.

**Confirmed trigger.** `.scratch/hunt-scripts/probe_ansi.py` under `FORCE_COLOR=3`:
`plain` line → `consumed=True passed=5 deselected=2`; `colored` line → `consumed=False
passed=0 deselected=0 dur=0.0`.

**Blast-radius scoping (the requested verify).** No gate keys off the parsed counts — all
pass/fail is exit-code driven:
- Phase pass/fail: `_run_parallel_phases` (:2228-2231) returns the first non-zero phase
  *exit code*; the pytest exit code flows from `_run_pytest_capturing` (:986). Color cannot
  turn a real failure (pytest exit 1) green.
- Coverage gate: enforced by per-library `--cov-fail-under` inside pytest (→ exit code) and by
  the combined `coverage report --fail-under` subprocess `report_exit_code`
  (`_combine_and_report_coverage` :757-767). Independent of parsed counts.
- The only consumers of the parsed counts are display: `_format_pytest_phase_summary`
  (:1247-1260) and `_tally_pytest_counts` (:2287) → the "Preflight passed … N tests ran"
  banner (:1872-1879). Under color these read `test: 0 passed in 0.00s` and the "N tests ran"
  clause silently drops.

So the impact is **observability only**: the rolled-up summary reads zero, and the
deselected-count surfacing (:1239-1241 — "a `-k` filter silently removed test files") and the
SLOW-durations notices never fire under color (their block header also fails to match). No
false green. Matches next-up.md's own note; this confirms and bounds it.

**Suggested fix.** Strip ANSI before matching in `_PytestOutputFilter.consume` (one
`re.sub(r"\x1b\[[0-9;]*m", "", text)` at entry), or pass `--color=no` on the internal pytest
invocations. Add a regression probe feeding a colored summary through the filter.

---

### S3 · medium · scripts/check_api.py:96 + scripts/repo_layout.py:604 (release_tags) — API-breakage baseline can be an `-experimental` tag ranked above stable, under-reporting breakage

**What happens.** `check_api._check_one_package` uses `tags[0]` (:93-96) as the griffe
`--against` baseline. `release_tags` (:604-619) globs `chumicro-<name>-v*` — which matches
**both** stable `chumicro-<name>-v<ver>` and `chumicro-<name>-v<ver>-experimental` tags — and
sorts with `--sort=-v:refname`. With git's default config (no `versionsort.suffix`), the
`-experimental` suffix ranks *above* the bare version of the same number.

**Confirmed trigger.** Throwaway repo probe (`/tmp/gitsort`), tags timing v0.3.0 / v0.9.0 /
v0.10.0 in both channels:
```
$ git tag --list 'chumicro-timing-v*' --sort=-v:refname   # what release_tags runs
chumicro-timing-v0.10.0-experimental   <- tags[0]
chumicro-timing-v0.10.0
chumicro-timing-v0.9.0
...
```
`git config --get versionsort.suffix` is unset in this repo (verified).

**Blast radius.** Experimental releases cut from `main` continuously; stable is promoted less
often, so the newest experimental version is normally `>=` the newest stable. `check_api`
therefore usually compares the PR's source against the **latest experimental** tag, not the
last stable release. When experimental already contains a breaking change not yet promoted, the
comparison sees no breakage, and the VERSION-bump-sufficiency check (:160-190) can pass with a
patch/minor bump even though the change is breaking relative to what stable-channel PyPI users
have. That is a release-gate under-enforcement (false-pass path). Version *parsing* is
unaffected (`_parse_version` ignores the `-experimental` suffix), so no crash — the gate just
picks the wrong baseline.

**Suggested fix.** For the stable-channel gate, filter `release_tags` to bare-version tags
(drop `-experimental`), or set `versionsort.suffix=-experimental` on the git invocation so
stable outranks experimental of the same version, or take the newest tag *matching the channel
being released*. A `release_tags(name, stable_only=True)` variant is the cleanest.

---

### S4 · medium · scripts/strip_comments.py:105-148 (_strip_comments) — multi-line-string `#` corruption, no code-equivalence guard

**What happens.** `_strip_comments` is a per-line scanner that resets `in_string = None` at the
top of every line (:114), so it never tracks triple-quoted strings across lines. A `#` on any
interior line of a multi-line string literal (that is not a docstring — docstrings are already
removed) is misread as a comment: a line whose lstrip starts with `#` is dropped whole (:110-113);
an inline `# …` after non-quote text is truncated (:138-148). The corrupted output still parses,
so the module's only safety check — `ast.parse(cleaned)` in `strip_file` (:176) — **does not
catch it**. This is the same scanner as the deploy-time `workbench/deploy/source_minify.py`, but
that module added a `_code_signature` parse-tree equivalence guard (source_minify.py:53) that
returns the input verbatim on any mismatch. `strip_comments.py` has no equivalent guard.

**Confirmed trigger.** `.scratch/hunt-scripts/probe_strip.py`:
- `BANNER = """\nUsage:\n  # not a comment…\n…"""` → the `# not a comment` line is deleted;
  `ast.literal_eval` of the string value before vs after differs (`string value preserved: False`).
- `TEMPLATE = """\nfoo = bar   # looks like a comment\n…"""` → truncated to `foo = bar`.
- Both outputs still `ast.parse` clean, so the corruption is silent.

**Blast radius.** `scripts/strip_comments.py` is wired only to the `run.py strip-comments`
subcommand (run.py:3645), which produces the clean-room baseline for comment-generation — **not**
a shipped-artifact path (the shipped deploy strip is `source_minify.py`, which is guarded). So
this corrupts the baseline a comment-writer reads, not published code. A scan of `libraries/*/src`
for non-docstring multi-line strings with `#` found only docstrings today (mqtt `_wire.py:460`,
wifi/kvstore `__init__` docstrings — all removed anyway), so no live trigger in library source;
but the tool accepts any tree (examples, demos, tests) and the latent bug is a code-transformer
that can silently alter string data.

**Suggested fix.** Port the `_code_signature` parse-tree equivalence guard from
`source_minify.strip_source` into `strip_file` (return input verbatim on any code-level
mismatch), or carry string state across lines in the scanner. The `ast.parse`-only check is
insufficient.

---

### S5 · low · scripts/bundle_push.py:71 (push_bundle) — partial-failure re-run returns 0 without pushing the tag

**What happens.** `push_bundle` gates all work on `_has_staged_changes` (`git diff --cached
--quiet`, :52-58). If a prior run committed but then failed at `git tag`/`git push` (:80-88),
a re-run over the **same** `.bundle-repo` finds the working tree already matches HEAD →
`_has_staged_changes` False → "No changes to commit" → returns 0, never re-attempting the tag
push. The release "succeeds" with no tag on the remote; mip/circup consumers resolving by tag
get nothing for that release.

**Blast radius.** Narrow: CI uses a *fresh clone* each run (release.yml:260), so the failed
commit never reached remote and a fresh-clone re-run re-diffs and recovers. The gap bites only
a hand-invoked re-run against a reused local `.bundle-repo`. No silent data corruption, just a
misleading exit 0.

**Suggested fix.** After the no-staged-changes branch, also verify the target tag exists on the
remote before returning 0; if HEAD is committed but the tag is missing/unpushed, (re)create and
push it.

---

### S6 · low · scripts/run.py:986 (_run_pytest_capturing) — exit-5 normalization + no zero-tests floor lets a fully-deselected run report green

**What happens.** pytest exit code 5 ("no tests collected") is normalized to 0 (:986). There is
no cross-check anywhere that a non-zero number of tests actually ran (the parsed counts feed
only display — see S2). A `-k`/marker filter that deselects everything, or a package that
collects zero tests, yields a green phase. Coverage would normally catch a zero-test package
(0% < threshold → exit 1), but coverage is skipped when a `filter_expression` is set
(`skip_coverage_gate`, run.py:837), so a filtered sweep matching nothing passes silently.

**Blast radius.** Low: full `preflight`/`test --all` always selects real packages (change
detection returns "run everything" on no diff), so this only affects narrow `-k` runs — which
are developer-initiated and expected to be scoped. Worth a floor check so a typo'd `-k` doesn't
read as a clean pass.

**Suggested fix.** When a `-k`/library filter is active and the summed parsed count is 0 (after
fixing S2's ANSI blindness), emit a loud "0 tests selected" warning or non-zero exit.

---

### S7 · low · scripts/sdist_content.py:94 (check_library_sdist) — "full content" gate checks dirs but not declared data files

**What happens.** `sdist_content` exists to fail the build if a curated-consumer sdist drops
required content, but it only asserts `tests/`, `examples/`, `docs/` are present
(`REQUIRED_SDIST_DIRS`, :26; loop :94-99). It does not verify that a module's declared
`__chumicro_data_files__` (e.g. `chumicro_sockets/_ca_bundle.der`) is in the sdist — the same
missing-data-file failure class as the recent C7 fix, but for the PyPI/curated path.

**Blast radius.** Currently masked: sockets' `pyproject.toml` sdist `only-include` lists
`"src/"` wholesale (verified libraries/sockets/pyproject.toml:52), so files under `src/`
(including the `.der`) always ride along, and the deploy walker reads them from the curated
tree. The gap is latent — a future library whose sdist config narrows `src/` to `*.py`, or a
data file placed outside `src/`, would drop the data file with this gate still green.

**Suggested fix.** Extend `check_library_sdist` to read each module's `__chumicro_data_files__`
(reuse `bundle_manager._data_files_from`) and assert each declared sibling is a member of the
built tarball.
