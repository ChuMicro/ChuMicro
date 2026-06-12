# audit-branch — TESTPLAN

Empirical validation rows for the bundled scripts. Layer A rows fabricate their own fixture: a
throwaway git repo under `$(mktemp -d)` with two commits — commit 1 adds `pkg/mod.py` defining
`def greet(name): return "hi " + name`, `caller.py` containing `from pkg.mod import greet` plus
`def welcome(name): return greet(name)`, and `app.py` containing `from caller import welcome`
plus a module-level `print(welcome("world"))` (the transitive hop the tracer must find);
commit 2 edits `greet` to `def greet(name, loud=False)` and changes its return. Build it with
plain `git init` / `git add` / `git commit` (any session can fabricate this in five commands).
`$SKILL` = `.github/skills/audit-branch`, `$PIPE` = `.github/skills/audit-code`.

| # | What it exercises | Invocation | Expected observable | Mark |
|---|---|---|---|---|
| A1 | Range staging end-to-end (mechanical only) | `python3 $SKILL/branch_phase1.py HEAD~1 HEAD $(mktemp -d)/room --repo <fixture> --stage-only` | room holds `diff.patch` (non-empty), `head/pkg/mod.py`, `head_stripped/pkg/mod.py`, `base_stripped/pkg/mod.py`; `changed_symbols.json` lists `greet` for `pkg/mod.py` | self-executing |
| A2 | Usage tracing | same run as A1 | `usage_map.json` maps `greet` to `caller.py`; `usages/caller.py` exists and is stripped | self-executing |
| A3 | Stale-room refusal | re-run A1's command against a room already holding `eval.json` | exit 1; the message names rooms.py as the fix | self-executing |
| A4 | Empty change-set refusal | `python3 $SKILL/branch_phase1.py HEAD HEAD $(mktemp -d)/room --repo <fixture> --stage-only` | exit 1; the message says the change-set is empty | self-executing |
| A5 | Staged mode | stage an edit in the fixture, then `python3 $SKILL/branch_phase1.py --staged $(mktemp -d)/room --repo <fixture> --stage-only` | `manifest.json` has `"mode": "staged"`; `intent.txt` notes no commit messages exist yet | self-executing |
| A6 | Feature-context staging (mechanical) | `python3 $SKILL/branch_phase0.py HEAD~1 HEAD $(mktemp -d)/room0 --repo <fixture> --stage-only` | `room0/world/` holds base-side stripped sources; `world_manifest.txt` lists them | self-executing |
| A7 | Render from a hand-built room | fabricate `eval.json` (2 findings with `file`), `written.json`, `summary.json`, `patches.json`, `manifest.json` in a temp room; `python3 $SKILL/render_branch.py <room>` | `picker.html` exists; spec.json carries severity/angle/file facets and both cards folded | self-executing |
| A8 | Workflow script parses | with node present: `node --check` on a copy whose `export const meta` is rewritten to `const meta` and whose body is wrapped in `async function wf() { … }`. Without node (macOS): wrap the same string in `new Function(<json-encoded string>)` and run via `osascript -l JavaScript` | no SyntaxError (JXA path prints `SYNTAX OK`). The async wrapper matters because the Workflow tool runs scripts in an async context and a bare function body rejects top-level `await` | self-executing |
| A9 | Repro staging | `python3 -c` one-liner: import `write_repros` from `audit_phase1` (sys.path the audit-code dir), call with a temp dir and `{'patches':[{'id':3,'repro':'def test_x():\n    assert 1'},{'id':4,'repro':''}]}` | returns 1; the temp dir holds `repros/repro_3.py` and nothing for id 4 | self-executing |
| A10 | Repo-gate seam mapping | `python3 -c` one-liner: load `_shared/apply_gate.py` via importlib, call `gate_command` on `libraries/sockets/src/chumicro_sockets/x.py` and on `scripts/run.py` | first returns the `test-all-runtimes --libraries sockets` argv + a reason; second returns None | self-executing |
| A11 | Transitive usage trace | `python3 $PIPE/usage_trace.py trace --root <fixture> --seed greet --out <tmp>/usage_paths.json` | edges include greet ← `welcome` (caller.py, depth 1) AND welcome ← `<module>` (app.py, depth 2) — the second hop is the point; seeds/caps/stops recorded | self-executing |
| A12 | Path-finding merge + blind-verdict fold | in A7's fabricated room: write `path_findings.json` (1 finding with a `feature`) and `path_validation.json` (index 0, real=false), run `usage_trace.py merge <room> <findings>`, re-run `render_branch.py` | eval.json gains the next free id with `in_session`; validation.json carries the `(blind path check)` note and `any_unreal`; the new card defaults *discuss* with both the in-session and validator warnings; sections include the feature map | self-executing |
| B1 | Full pipeline on a real range | a 2–3 file range in this repo: `branch_phase1.py <base> <head> $RUN --voice plain` (background; minutes) | `phase1.json` reports findings with angles from the six-lens set; every finding has a patch naming its file | self-executing (slow) |
| B2 | Cross-runtime repo gate live | `python3 $PIPE/apply_fix.py runtests libraries/timing/src/chumicro_timing/heartbeat.py` | pytest passes, then the REPO GATE banner names timing's cross-runtime suite and it exits PASS | self-executing (slow) |
| C1 | Selection gate + apply loop | drive Step 5–7 of SKILL.md on B1's room in a cold session | the picker submits a blob the session parses; an applied fix runs `runtests` and shows a diff; nothing committed | needs-human |
| D1 | Trigger routing | `python3 .github/skills/_shared/run_trigger_evals.py $SKILL/trigger-evals.json --workers 4` | every row PASS (or a FAIL explicitly accepted with the reason in chat) | self-executing |
