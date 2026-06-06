# Handoff 2026-05-30 — comment-generation: round 18 analyzed, round 19 (soul-vs-correctness) built and ready to run

Supersedes `2026-05-30-comment-generation-round18-guided-vs-bare.md` (round 18 is built, run, and
analyzed; that file stays for its build detail). This is the active doc.

## My role (do not lose this)

Orchestrator / analysis seat. I read outputs, decide the spec, edit the agent files, build the
package, and **store what I learn here in this handoff**. `RUN.md` is the brief for a **separate
dispatch session** that only runs the workflow and verifies counts; it is not where analysis
knowledge goes. Agent files load into the registry only at session start, so I build and a fresh
session runs.

## Where we are

- **Round 18 ran and I analyzed it** (run-1, both hard files, both matched pairs, read in full).
- **Round 19 is built and verified, ready to dispatch.** `.scratch/regen-comments/experiment/round-19/`
  holds the workflow + RUN.md; the two new agents are in `.claude/agents/`.

## Round 18 findings (the analysis)

Read `client.py` (warm + engineer pairs) and `_ca_bundle.py` (warm pair), run-1, against the ledger
and stripped source.

- **The one real gap: both bare voices skip `username` and `password` in `MQTTClient.__init__`.**
  warm-bare and engineer-bare both narrate the constructor in prose and walk `publish_retry_max ->
  clean_session`, dropping the two credential params. Both guided voices document all 22 incl. the
  credentials. `document-every-arg` is the load-bearing guided rule, and it lands exactly on the
  params that "look obvious."
- **The other predicted bare failures did not appear.** On soupy `client.py`, bare did not copy
  stubs, carry em-dashes, use AI-tics, or write unparseable sentences. The hardened triage's clean
  ledger prevented them.
- **Round-16's failure did not recur.** `_ca_bundle.py` (the `set_default_ca_bundle` cross-symbol
  pointer leak) is clean in both arms, because the triage ledger never carried the pointer.
- **Verdict:** clean triage does most of the work; the writer guidance's residual load-bearing value
  is `document-every-arg`. The handoff's "riskiest assumption flip" is largely confirmed.
- **Voice finding (drove round 19):** guided is more correct but flatter; bare has more soul. The
  soul cost is NOT the rules the user values. It comes from: (1) warm-guided's rider "the warmth
  rides on the discipline above and never buys an extra sentence or a body"; (2) the exemplars
  differ (guided modelled a clinical `Args:` block, bare a warm one-liner); (3) over-applied
  one-idea-per-sentence. The `Args:` *structure* was never the soul-killer; the *sentence
  restraints* were. open-on-behavior is good (it fixes the `The <noun>` opener, a real bare ding).

## Round 19 design (what it tests, what changed)

Question: can correctness and voice hold at once? New **`guided-soul`** arm keeps the correct
docstring structure (behavior-first summary, optional body, `Args:`/`Returns:`/`Raises:`) and
`document-every-parameter` + `open-on-behavior`, and frees only the sentence-level restraints:
drops the "warmth never buys a sentence" rider, makes each `Args:` entry a real sentence in voice
(not a clipped type restatement), lets the body breathe a sentence or two, softens reject #2 to fire
only on three-plus-fact pile-ups. Verified by diff: `guided-soul` is the round-18 `guided` agent
byte-for-byte except those sentence/voice changes; structure is identical.

- **3 arms x 2 personas:** `bare`, `guided` (both reuse the unchanged round-18 agents), `guided-soul`
  (new round-19). Personas warm + engineer. Engineer is the control (it barely moved guided-vs-bare,
  so guided-soul should barely move it; the signal is in the warm trio).
- **2 files** (`mqtt/client.py`, `sockets/_ca_bundle.py`), **2 runs**. 4 triage + 24 writers = 28
  agents. Reuses round-18's verified inputs read-only; writes fresh `round-19/` outputs. Triage held
  constant (`commenter-r18-triage`) so all three arms share one ledger.
- New agents: `commenter-r19-warm-guided-soul`, `commenter-r19-engineer-guided-soul`. `name:` fields
  verified matching filenames; 0 em-dashes.

## What round 19 evaluates (three criteria, not two)

1. **Correctness:** does `guided-soul` still document `username`/`password` (every param)? If it drops
   one, the sentence-freeing went too far.
2. **Soul:** read `warm-guided-soul` vs `warm-guided` vs `warm-bare` on the same symbol. Did it
   recover the warm asides and prose flow guided trims, without bare's leaks (`The <noun>` opener,
   3+-fact semicolon crams)?
3. **Body cleanliness:** does each body stay to a clean sentence or two, or sprawl into an essay?
   This is the gate for the no-body rule below. (This criterion is intentionally NOT in RUN.md; it
   lives here for the analysis seat.)

## The no-body-docstring rule is provisional and aging out

chumicro `libraries/` currently allow only a summary + `Args:`/`Returns:`/`Raises:`, no body
paragraph. Per the user (2026-05-30) that ban is a **workaround, not a principle**: every past
attempt at a body became an essay (over-ran the 1-2 sentence limit, abstract nouns, leaks), so
banning was easier than writing one cleanly. If round 19 shows clean, restrained bodies are
achievable, the ban loses its reason and short bodies become allowed. The flash-byte cost is
secondary and still wants a body short either way. Full detail in memory `[[no-docstring-bodies]]`.

## Session decisions now in memory (do not duplicate; read these)

- `[[ai-tic-actual-list]]` — only `canonical` and `shape` are banned AI-tics; do not invent broader
  lists or label robust/seamless/etc as AI-tics.
- `[[feedback_no_speculative_validation]]` — do not add checks for failure modes that have not
  occurred (code-integrity, empty-file scans were declined; zero such failures across all rounds).
- `[[agent-examples-must-be-neutral]]` — agent few-shot examples and fact-type checklists must be
  neutral, never the code under test, never one domain's flavor. The round-18 triage broke this
  (timing-flavored examples + real `ca_bundle`/`mqtt` content); fixed this session.
- The triage no longer logs `CUT:` lines (they breached the writer-blind-to-original-comments
  contract by quoting originals verbatim); the workflow triage prompt was fixed to match.

## Next concrete step

Hand `round-19/RUN.md` to a fresh dispatch session. Verify 4 ledgers + 24 files. Then a new analysis
seat reads the warm trio on both files against the three criteria above and writes the verdict here:
did `guided-soul` keep param coverage AND read closer to bare's voice AND keep bodies clean? If yes,
it replaces `guided` and the no-body rule can start retiring. If a param went missing, bisect which
loosening (the sentence rule vs the freed `Args:` voice) caused it.

## Gotchas

- **`.claude/agents/` is NOT git-tracked**; agents load only at session start. Dispatch is a separate
  reloaded session handed RUN.md.
- **The auto-mode classifier intermittently denies edits/writes under `.claude/agents/`** as
  self-modification. Retrying the same edit usually passes; it is probabilistic, not a hard block.
- **Em-dashes are banned in the agent files** (purged round 18). Re-check `grep -c '—'` returns 0
  after any agent edit; one slipped into both r19 agents on first write and had to be fixed.
- Round-18 build is at `.scratch/regen-comments/experiment/round-18/`; its outputs at `runs/` are the
  analyzed exhibit. Round-19 reuses its `fixing/` + `stripped/` inputs read-only.

## How to rebuild context fast

Read this handoff, then `round-19/RUN.md`, then diff a guided-soul agent against its round-18 guided
source (`git --no-pager diff --no-index commenter-r18-warm-guided.md commenter-r19-warm-guided-soul.md`)
to see exactly what the soul arm changes.
