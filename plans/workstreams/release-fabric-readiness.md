# Workstream: release-fabric readiness — audit before first publish

Status: **audited AND remediated 2026-07-05.**  All five blockers fixed in code the same day; GitHub-side infra stood up (see Standup state below).  Remaining before first release: PyPI trusted publishers (28 new + 8 to verify), the ChuMicro-Bundle visibility decision, then the first-release sequence.  ci.yml + release.yml preflight-gate surgery (172c64b2) was the enabling step.

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
  - **Wired 2026-07-05**: `libraries-channel` job added to release.yml (experimental repo, date-tagged) and promote.yml (stable repo, gated to library promotions).  New secrets `LIBRARIES_DEPLOY_KEY` / `EXPERIMENTAL_LIBRARIES_DEPLOY_KEY` (SSH push only — the consumer reads raw `index.json` + codeload tag tarballs, so no GH release / `BUNDLE_TOKEN` is needed).  **Semantic to bless**: the producer only supports a *whole-tree snapshot* (it wipes + rebuilds every library, no per-library overlay), so both channels publish the entire `libraries/` tree at once and the stable channel tracks main-as-of-last-promotion for **all** libraries — not just the one being promoted, and possibly ahead of stable PyPI.  A per-library accumulate mode would be a producer change if that divergence is unacceptable.
- **B5 — tag-as-idempotency written mid-pipeline** (release.yml): PyPI publish has no `skip-existing`; four distinct permanent re-run traps (publish-ok/tag-fail → re-publish rejected forever; tag-ok/zip-attach-fail → version can never be promoted; tag-ok/bundle-fail → device bundle never produced, detect skips forever; partial matrix across runs → succeeded legs never bundled).  Fix: `skip-existing: true` on the publish step AND make the tag the last write (or add resume logic).  `workflow_dispatch --libraries` is the manual escape hatch meanwhile.

## Design flaws (should fix, not first-run-fatal)

- promote.yml: **no preflight-gate** (stable = immutable PyPI with zero re-checks; source is the frozen tested zip, but rebuilt with current tooling) and **no concurrency group** (racing bundle pushes have no non-fast-forward retry).
- `release_matrix.py` releases **everything untagged**, not what changed: first bump publishes all 18 packages at once; no `0.0.0` floor guard (a freshly scaffolded library would ship on the next unrelated bump).
- A VERSION bump whose preflight-gate fails is stranded — a follow-up fix commit not touching VERSION doesn't re-trigger release.yml (paths filter).  Recovery: re-touch VERSION or dispatch.
- Docs/channel inversion: every user-facing install default (INSTALL.md, all library READMEs, landing page, sister README, `library add` default `--channel stable`) points at **stable**, which only exists after manual promotion.  See Decision-point 2.
- Sister `test.yml` header claims tool-owned but `template_zones.py` classifies `.github/workflows/` USER_OWNED → `update` skips it; CI fixes never propagate to existing workspaces.
- mip dep refs pin `HEAD` in the bundle (`bundle_manager.py`), so an install pulls the dep's newest bundle state, not the version tested against.

## Decision points (user)

1. **Experimental-PyPI policy** — **RESOLVED 2026-07-05: option (a)** (user). `patch_experimental` (`scripts/bundle_manager.py`) now appends `-experimental` to the name portion of every intra-chumicro `[project].dependencies` entry (specifiers preserved), so the experimental channel stays pip-installable. Options as considered: (a) rewrite intra-chumicro deps to `-experimental` in the patch (keeps pip usable on the experimental channel; recommended) — **chosen**; (b) stop publishing experimental to PyPI entirely (bundle repos + source zips carry experimental; PyPI is stable-only via promote — halves the trusted-publisher count to 18 but removes the pip surface for early tool adopters).
2. **Launch story for stable** — the auto-experimental / manual-promote design is fine, but launch must include a **promotion wave** (all 13 active libraries + `chumicro-workspace`, `-deploy`, `-pytest-device`, `-checks`) or every documented instruction 404s on day one.  Alternative (not recommended): re-point all docs defaults at experimental.

## GitHub-side prerequisites (user; none verifiable from the bench account)

- Repos existing, default branch `main`: `ChuMicro-Bundle`, `ChuMicro-Bundle-Experimental` (+ `ChuMicro-Libraries`, `ChuMicro-Libraries-Experimental` once B4 is wired).
- Secrets on the source repo: `BUNDLE_DEPLOY_KEY`, `EXPERIMENTAL_BUNDLE_DEPLOY_KEY`, `BUNDLE_TOKEN` (PAT, contents:write on bundle repos), `GH_PAGES_DEPLOY_KEY` (promote docs job); `pypi` **environment** configured.
- PyPI trusted publishers (OIDC, per project): 18 experimental names via release.yml + 18 stable names via promote.yml = **36 pending-publisher configs** (drops to 18 under Decision-point 1b).  Parked `logging` excluded.
- Tag-protection/ruleset bypass for `github-actions[bot]` on `chumicro-*` tags.
- Branch-protection required-status-checks list still names the **old** workflow's 13 checks (observed in push output 2026-07-05: "13 of 13 required status checks are expected — bypassed"); replace with the new job names or prune to `preflight`.
- Sister repo hygiene before any publicity: untracked bench probes (`projects/frag_probe*`, `mqtt_bake*`, TLS `ca.pem`/`ca.der`, etc.) — `.gitignore` does NOT cover `projects/*`, one `git add -A` away from publishing bench material; tracked orphan `projects/wifi_only/project_config.toml` (app.py untracked).

## Standup state (2026-07-05, end of day)

Live inventory replaced the audit's assumptions: the April release infrastructure mostly survived.  Executed same day (Claude via chuxmaker gh where the permission model allowed, user via `.scratch/standup_release_infra.sh` otherwise):

- **Done**: repo-level Actions re-enabled (was the entire reason nothing fired since 2026-04-18 — workflows were individually active); main ruleset required checks retargeted to the new five (`preflight`, `compatibility (3.11/12/13)`, `Validate mpy bytecode`); fresh write deploy key + rotated secret for ChuMicro-Bundle-Experimental (repo key had been deleted); new `LIBRARIES_DEPLOY_KEY` / `EXPERIMENTAL_LIBRARIES_DEPLOY_KEY` pairs; empty Bundle-Experimental remote seeded with a `main` branch.  BUNDLE_TOKEN confirmed still valid (user).  `pypi` environment, `BUNDLE_DEPLOY_KEY`, `GH_PAGES_DEPLOY_KEY` already existed.
- **All five blockers + promote hardening landed in code** (B1/B2/B5 + concurrency + tag-last/skip-existing on promote too, 0.0.0 floor, `--include-tagged` escape hatch, libraries-channel jobs in both workflows, sister `[dev]` install + loud-fail lint + zone fix + hygiene).
- **New first-run trap found and fixed during review**: `bundle_manager.py` imports `chumicro_deploy` at module level (0090 strip reuse, post-dated the April green runs), so every job invoking it (release legs' patch-experimental, both bundle jobs, ci.yml validate-mpy) now runs `run.py setup` instead of bespoke pip installs.
- **Accepted-for-launch semantics**: the stable libraries channel is a whole-tree snapshot of main-at-promotion (producer has no per-library overlay), so it can run ahead of stable PyPI between promotions.  Livable while promotions happen in waves; a per-library accumulate mode is the follow-up if the divergence starts to bite.
- **PyPI reality**: 8 of 36 projects already exist (compat / msgpack / runner / timing, both channels, old 0.1.x versions — no collision with current versions).  Remaining: verify those 8 publisher configs (workflow file + `pypi` environment), register the other 28 — web-UI only, Chrome-drive queued (rate limit 100/24 h, fits one sitting).
- **Open user decision**: ChuMicro-Bundle is PRIVATE; must go public before the first stable promotion (mip/circup fetch raw files anonymously).

## Sequence

1. ~~Verify first ci.yml run green~~ — VERIFIED 2026-07-05: run 28752439230 all five checks green.  The three shakedown failures were each real catches (platform-gated wedge test, threadbare compatibility install, tarfile filter deprecation fatal only on 3.12/3.13 under `-W error`) — fixed at the root, no lanes relaxed.
2. ~~Land the monorepo code fixes~~ — DONE 2026-07-05 (B1, B2, B5 + promote skip-existing/tag-last, concurrency, 0.0.0 floor, B4 wiring, run.py-setup in every bundle_manager-invoking job).
3. ~~Land the sister/workspace fixes~~ — DONE 2026-07-05 (B3 `[dev]` install + loud-fail lint, test.yml zone classification, CHU008 fix, tree hygiene, wifi_only orphan).
4. GitHub/PyPI prerequisites — GitHub side DONE except the Bundle visibility flip (deferred, see 5); PyPI publishers (verify 8 + register 28) can happen any time, they expose nothing.
5. **DOCS GATE (user call 2026-07-05): nothing goes public until the docs/guides redo lands.**  `Release` and `Deploy Documentation` workflows are `disabled_manually` so an accidental VERSION bump or push can't publish to PyPI/bundles/gh-pages meanwhile; CI stays active.  The docs redo also absorbs the channel-inversion fixes (D1) and the launch promotion-wave story.
6. Going public (after the docs redo): re-enable both workflows, flip ChuMicro-Bundle public, then first release: one VERSION bump → experimental wave (expect all 18) → verify bundle + validate-mip + libraries-channel → promotion wave per Decision-point 2 → docs `/stable/` aliases live → sister CI green on a fresh runner is the acceptance test.
