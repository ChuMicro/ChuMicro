# Workstream: release-fabric readiness — audit before first publish

Status: **audited 2026-07-05 (three-agent sweep: pipeline / consumption / sister+docs), verdict: CI can flip on now; publishing cannot.**  ci.yml + release.yml preflight-gate surgery (172c64b2) is sound and out of scope here.  Everything below is the rest of the fabric.

## Verdict

The mip/circup device-bundle path is coherent and publish-ready end to end (producer, validator, bundle_push branch, docs all agree).  Every other path has at least one defect that fires on the very first real release.  Five blockers, two policy decisions, and a GitHub-side prerequisite bill must clear before the first VERSION bump publishes.

## The fabric (source → mechanism → consumer)

| path | mechanism | state |
|---|---|---|
| PyPI experimental | release.yml auto on VERSION bump; `patch-experimental` renames | wired; **B1 + B2 break it** |
| PyPI stable | promote.yml manual per experimental tag, replays frozen source zip | wired; **no preflight gate, no concurrency group** |
| Device bundle (mip/circup) | release.yml/promote.yml → ChuMicro-Bundle[-Experimental], date tags + circup zips | **ready** |
| Workspace library channel | `chumicro-workspace library add/browse/update` ← ChuMicro-Libraries[-Experimental] `index.json` + tag tarballs | consumer + producer (`scripts/libraries_channel.py`) exist, contract matches byte-for-byte, **producer wired into NO workflow** (Decision 0078 unimplemented) — **B4** |
| Sister repo bootstrap | `run.py setup` → pip install stable `chumicro-workspace`/`-pytest-device`/`-checks` | **B3 + B5**; only dev-mode (`chumicro-dev.toml` → sibling checkout) works today — why blockers are invisible locally |
| Docs | docs_deploy → gh-pages `<lib>/{stable,experimental}/` | wired; `/stable/` alias only created by first promote |

## Blockers (code fixes in this repo unless noted)

- **B1 — `patch-experimental` name derivation** (`scripts/bundle_manager.py` ~line 780): builds `chumicro-{dir.name}` → `chumicro-http_server`, but `libraries/http_server/pyproject.toml` says `chumicro-http-server` → `sys.exit` on every http_server release; a failed matrix leg also skips `bundle` + `validate-mip` for the WHOLE run (partial publish: PyPI yes, device bundle no).  Fix: read `[project].name` from pyproject instead of deriving from the directory.
- **B2 — experimental wheels declare stable deps**: patch rewrites only the package's own name; `chumicro-mqtt-experimental` ships `Requires-Dist: chumicro-config` etc.  Uninstallable at bootstrap (no stable projects exist), silent cross-channel mixing after.  PyPI path only — the bundle path rewrites deps correctly.  Fix per Decision-point 1 below.
- **B3 — sister `run.py setup` never installs `[dev]`** (`run.py` + workspace `cli/setup.py` both do bare `pip install -e .`): pytest/ruff/chumicro-checks absent → `run.py test` dies "No module named pytest"; worse, `run.py lint` prints a hint and **returns 0** when tools are missing — green lint that lints nothing (this is also why a CHU008 violation ships in `projects/example_sensor/app.py` — a Decision-0108 pointer in user-facing template code).  The sister pyproject comment falsely claims setup installs dev extras.
- **B4 — workspace library channel never published**: wire `scripts/libraries_channel.py` into release.yml/promote.yml (it shares `bundle_push`) and create the two ChuMicro-Libraries repos + deploy keys.  Until then every regular-mode `library add/browse/update` 404s — the sister repo's dedicated library-acquisition path does not function off-bench.
- **B5 — tag-as-idempotency written mid-pipeline** (release.yml): PyPI publish has no `skip-existing`; four distinct permanent re-run traps (publish-ok/tag-fail → re-publish rejected forever; tag-ok/zip-attach-fail → version can never be promoted; tag-ok/bundle-fail → device bundle never produced, detect skips forever; partial matrix across runs → succeeded legs never bundled).  Fix: `skip-existing: true` on the publish step AND make the tag the last write (or add resume logic).  `workflow_dispatch --libraries` is the manual escape hatch meanwhile.

## Design flaws (should fix, not first-run-fatal)

- promote.yml: **no preflight-gate** (stable = immutable PyPI with zero re-checks; source is the frozen tested zip, but rebuilt with current tooling) and **no concurrency group** (racing bundle pushes have no non-fast-forward retry).
- `release_matrix.py` releases **everything untagged**, not what changed: first bump publishes all 18 packages at once; no `0.0.0` floor guard (a freshly scaffolded library would ship on the next unrelated bump).
- A VERSION bump whose preflight-gate fails is stranded — a follow-up fix commit not touching VERSION doesn't re-trigger release.yml (paths filter).  Recovery: re-touch VERSION or dispatch.
- Docs/channel inversion: every user-facing install default (INSTALL.md, all library READMEs, landing page, sister README, `library add` default `--channel stable`) points at **stable**, which only exists after manual promotion.  See Decision-point 2.
- Sister `test.yml` header claims tool-owned but `template_zones.py` classifies `.github/workflows/` USER_OWNED → `update` skips it; CI fixes never propagate to existing workspaces.
- mip dep refs pin `HEAD` in the bundle (`bundle_manager.py`), so an install pulls the dep's newest bundle state, not the version tested against.

## Decision points (user)

1. **Experimental-PyPI policy** — pick one: (a) rewrite intra-chumicro deps to `-experimental` in the patch (keeps pip usable on the experimental channel; recommended); (b) stop publishing experimental to PyPI entirely (bundle repos + source zips carry experimental; PyPI is stable-only via promote — halves the trusted-publisher count to 18 but removes the pip surface for early tool adopters).
2. **Launch story for stable** — the auto-experimental / manual-promote design is fine, but launch must include a **promotion wave** (all 13 active libraries + `chumicro-workspace`, `-deploy`, `-pytest-device`, `-checks`) or every documented instruction 404s on day one.  Alternative (not recommended): re-point all docs defaults at experimental.

## GitHub-side prerequisites (user; none verifiable from the bench account)

- Repos existing, default branch `main`: `ChuMicro-Bundle`, `ChuMicro-Bundle-Experimental` (+ `ChuMicro-Libraries`, `ChuMicro-Libraries-Experimental` once B4 is wired).
- Secrets on the source repo: `BUNDLE_DEPLOY_KEY`, `EXPERIMENTAL_BUNDLE_DEPLOY_KEY`, `BUNDLE_TOKEN` (PAT, contents:write on bundle repos), `GH_PAGES_DEPLOY_KEY` (promote docs job); `pypi` **environment** configured.
- PyPI trusted publishers (OIDC, per project): 18 experimental names via release.yml + 18 stable names via promote.yml = **36 pending-publisher configs** (drops to 18 under Decision-point 1b).  Parked `logging` excluded.
- Tag-protection/ruleset bypass for `github-actions[bot]` on `chumicro-*` tags.
- Branch-protection required-status-checks list still names the **old** workflow's 13 checks (observed in push output 2026-07-05: "13 of 13 required status checks are expected — bypassed"); replace with the new job names or prune to `preflight`.
- Sister repo hygiene before any publicity: untracked bench probes (`projects/frag_probe*`, `mqtt_bake*`, TLS `ca.pem`/`ca.der`, etc.) — `.gitignore` does NOT cover `projects/*`, one `git add -A` away from publishing bench material; tracked orphan `projects/wifi_only/project_config.toml` (app.py untracked).

## Sequence

1. Verify first ci.yml run green (user flips/watches Actions) — independent of everything below.
2. Land the monorepo code fixes: B1, B5, promote gate + concurrency, 0.0.0 floor, B2 per Decision-point 1, B4 wiring.
3. Land the sister/workspace fixes: B3 (setup installs `[dev]`; lint fails loudly when tools missing), test.yml zone classification, CHU008 violation in example app, tree hygiene, wifi_only orphan.
4. User does the GitHub/PyPI prerequisite checklist.
5. First release: one VERSION bump → experimental wave (expect all 18) → verify bundle + validate-mip → promotion wave per Decision-point 2 → docs `/stable/` aliases live → sister CI green on a fresh runner is the acceptance test.
