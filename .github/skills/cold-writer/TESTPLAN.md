# Cold writer verification

Run from the ChuMicro repository root with its virtual environment active.
Store transcripts and fixtures in `.scratch/cold-writer/`. These tests make no
board changes and publish no documentation.

## Automated checks

| Layer | Command or procedure | Pass condition |
|---|---|---|
| Launcher contract | `python .github/skills/cold-writer/scripts/test_write.py` | Every test passes, including rejected reviews, failed streams, output-directory protection, and the register excerpt reaching the prompt without its attribution header |
| Echo gate | `python .github/skills/cold-writer/scripts/test_echo_check.py` | Every test passes: identical prose fails, a fragment brief passes, code and links never count, and exit codes separate an echo from unusable input |
| Echo measurement | `python .github/skills/cold-writer/scripts/echo_check.py --brief <run>/brief.md --draft <run>/draft.md` | Exit 0, and every listed echo is a command, output line, or warning rather than explanatory prose |
| Command interface | `python .github/skills/cold-writer/scripts/write.py --help` | Help describes brief, review, model, voice, run directory, timeout, and check mode |
| Syntax and repository rules | `python scripts/run.py preflight --coverage-threshold 94 --quiet` | Complete output reports every required gate passing |
| Routing | `python .github/skills/_shared/run_trigger_evals.py .github/skills/cold-writer/trigger-evals.json --model opus` | Each expected route wins its repeated probes; inspect errors separately from routes |
| Neighbor routing | Run that evaluator on existing `audit-docs` and `guide-generation` eval files when present | Their established queries keep their intended routes |
| Skill audit | Run `.github/skills/_shared/audit_wf.js` using the new-skill procedure | Independent findings and their dispositions are recorded |

### Routing result validity

Inspect the saved responses, including negative cases. A CLI error, turn-limit
failure, permission denial, or unparsed response is an invalid probe, never a
successful negative route. Report invalid probes separately from routing scores.

If local hooks interrupt the shared evaluator, repeat its same queries and
routing prompt in a scratch harness with session-only `disableAllHooks: true`.
Keep the `Skill` tool available for registry discovery, disable task tools with
`--tools Skill --permission-mode dontAsk`, and request JSON output. Accept only
successful, single-turn replies naming a known skill or `none`. Save each raw
response and repeat each query three times. Disabling every tool hides the skill
registry in some CLI versions and tests a different condition. Keep this routing
configuration separate from the writer's tool-free isolation configuration.

## Live isolation test

1. Prepare a small, factual brief for a fictional board-console exercise and have
   a fresh reviewer approve its exact hash. Keep it free of old prose.
2. Run the launcher from a test directory containing `CLAUDE.md` and `AGENTS.md`
   instructions requiring the output marker `CONTEXT_LEAK_CANARY_48271`.
   Put a conflicting marker instruction in a test skill under that directory's
   `.claude/skills/`. Keep these files under `.scratch/`.
3. Read the receipt and response stream. Tools, MCP servers, skills, and plugins
   must be empty; the result must report success and identify its actual model.
   `system-prompt.txt` carries the register excerpt and none of its attribution
   header lines.
4. Read the draft. The exercise must match the brief and contain no canary.
   This checks observed behavior; it does not establish an operating-system
   security boundary or expose provider-managed instructions.

The launcher creates a new run directory beneath the test parent. Ancestor
instructions make this test stricter than an otherwise empty temporary folder.

## End-to-end page trial

Use `docs/start-here.md` in draft-only mode. Research the template and current
workspace commands, distinguish source-checked behavior from board observation,
and preserve data-loss warnings. Have a fresh reviewer inspect the source evidence
and brief before drafting. Run fresh technical and reader reviews afterward.
Keep the old page and previous drafts out of the writer's input.

Pass when the new page covers its specified outcome, each required claim has
evidence, relative links resolve from the intended destination, and the echo
measurement passes: a page whose prose relays the brief fails even with every
fact present. Save the blind
reader verdict, then compare against the original for coverage and fluency. Account
for material length changes. Reviews must have no unresolved blockers. Record any
markup or link-only repair explicitly.

## Editorial regression checks

Include these cases in brief and reader reviews; keep them outside writer inputs.

- An accurate draft adds encouragement, repeated recovery advice, and explanations
  of assumed knowledge. Fail it for unnecessary reading burden.
- A shorter draft omits a data-loss warning or needed concept introduction. Fail
  it for lost coverage; word count cannot override the task.
- A procedure uses an unfamiliar term before explaining it in a later section.
  Fail reading order even when every fact appears somewhere on the page.
- A paragraph switches claims or sentences repeatedly define objects instead of
  explaining what they do. Identify the disrupted connection, not just a phrase.
- An established object naturally takes “the.” Accept it; assess whether the reader
  can identify the referent rather than applying an article quota.
- A legacy inbound anchor contains an old heading. Keep it outside writer inputs,
  restore it as markup, and verify its destination without changing draft prose.

## Human and hardware checks

- **Owner voice approval:** Chuck reads the sample and decides whether its focus,
  fluency, and professional accessibility fit ChuMicro. An agent cannot decide this.
- **Beginner usability:** someone new to ChuMicro follows the page and marks the
  first instruction that requires help or guessing.
- **Hardware execution:** with explicit permission and a backed-up supported
  board, follow the draft's setup and deploy sequence. Compare console output
  with every expected result. Report the board and runtime actually tested.
- **Visual acceptance:** inspect the page in the documentation site's renderer at
  desktop and narrow widths. Confirm code scrolling, warning placement, heading
  order, links, and any images. A source-only review leaves this check open.

## Retest after changes

Launcher and writer-prompt changes require unit and live isolation tests.
Brief-template and review-contract changes require the page trial with its echo
measurement. Routing changes require repeated routing probes.
Editorial changes require a fresh reader review; isolation stays intact by
giving the writer a new factual brief rather than an annotated rejected draft.
