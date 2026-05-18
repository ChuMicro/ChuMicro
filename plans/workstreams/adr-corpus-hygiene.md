# ADR corpus hygiene

Opened 2026-05-18 from a full audit of all 75 decision records. The
user's read — "we have way too many of them; some should be archived,
some don't merit being ADRs, some should combine" — is correct. The
sprawl is the same disease the `deploy-path-unification` workstream
names one layer down: divergent records for one evolving decision,
never reconverged. Only 2 of 75 were marked `superseded` despite ~15
later ADRs explicitly unifying / extending / collapsing / splitting /
amending earlier ones.

This workstream carries the audit findings and the remediation
punch-list. The **archive rule itself** (the user's headline ask) is
its own unit — ADR 0076 + `decisions/README.md` + AGENTS step 3 +
`new-decision` skill + CHU019 — and ships first; the rest is the
backlog it enables.

## The classification rule applied

Per `plans/decisions/README.md`, *partial* replacement means **edit the
old body in place, status stays `accepted`** — only a *fully replaced*
ADR becomes `superseded`. Most sub-agent "SUPERSEDED" verdicts were
over-eager against that rule. Sorted correctly:

### A. Genuinely `superseded` (frozen, archive-marked)

- **0035 runtime-config-structure** — its nested section-namespaced
  dict (`config["wifi"]["ssid"]`) is fully replaced by the flat
  dotted-key model (`wifi.ssid`) that **0036** now documents as the
  live API. Verified: 0036 body states the shape "evolved … flat dict
  with dotted keys … rather than nested sections"; 0035 §1 still
  mandates the dead nested shape. The clearest *new* supersession in
  the corpus. → `Status: superseded`, `Superseded by: 0036`, archive
  marker. **Done in the 0076 first batch.**
- **0006**, **0008** — already `superseded` and correctly pointed.
  They only needed the archive marker. **Done in the 0076 first batch.**

### B. Stale body, stays `accepted` — edit in place to kill drift

Not archived; these still govern. Each needs the affected paragraphs
rewritten so a cold reader gets the current rule, with an inline
forward cross-link (no banners — README rule):

- **0047 §3** auto-switch mechanism absorbed by **0068**'s unified
  resolver; §1 default-flip + §2 `requires_flash` still in force.
  Rewrite §3.
- **0016** — the `_pytest` filename convention was retired by **0070**;
  the directory table and "real devices" claim are now wrong.
- **0037** — the test-support concern was split out by **0069**;
  §3's `("cpython",)`-on-`testing.py` description is superseded by the
  `__chumicro_test_support__` marker.
- **0048** — phase-parallelism still in force, but the
  subprocess-capture mechanism was replaced by **0054**'s dispatchers.
  Rewrite the output-mechanism paragraph.
- **0003 / 0016 → 0049**: 0049 is the umbrella *principle* (CPython is
  the test seam). Per README this is **not** supersession — add an
  inline "founding principle: Decision 0049" cross-link, no status
  change.

### C. Spent / inert — governs nothing now (archive, not `superseded`)

No replacing ADR; the reasoning is spent, not wrong. Stays `accepted`
(no 5th status); archive marker + `Archived:` field carries "historical
only".

- **0004 sample-library-first-slice** — "ChuMicro needs a *first*
  publishable library"; every seam it deferred (networking, storage)
  has long shipped. Confirmed inert. **Done in the 0076 first batch.**
- **0005 windows-wsl2-unix-port-validation** — dated environment note;
  doesn't recur in any live testing/bundle/deploy decision. *Lower
  confidence — flagged for user sign-off, NOT auto-applied in the
  first batch.* Decide: archive as inert, or keep (does anyone still
  rely on the WSL2 path as the documented Windows story?).

### D. Not an ADR — rewrite + relocate (separate unit)

- **0017 circuitpython-ringio-bug** — ~110 lines of compile-error
  forensics, "why CI doesn't catch it", "why not the coverage variant",
  "upstream tracking". The README explicitly routes postmortem /
  code-block-heavy writeups to `docs/troubleshooting/`. One real
  ~6-line decision is buried in it ("build `VARIANT=standard` with
  `-DMICROPY_PY_MICROPYTHON_RINGIO=0`, not the coverage variant").
  Action: slim the ADR to that decision; move the forensics to
  `docs/troubleshooting/circuitpython-ringio.md`. Not an archive — a
  content split.

### E. Below the ADR bar but harmless — note, do not churn

Rewriting history to tidy these costs more than it returns. Leave;
stop creating this class going forward (the `new-decision` skill's
"don't create a decision for tooling defaults" line should bite here).

- **0056** — one transport kwarg signature (`extra_files: dict`).
- **0012** — IDE stub version pins.
- **0026** — editable installs as setup convention.

### F. Observation, no action

- **0068 → 0071 → 0072** are legitimate *sequential* refinements of
  one "how the on-device sweep survives a 256 KB board" decision; each
  resolves the prior's "not closed" thread and cross-links. Per the
  README that temporal chain is allowed to stay split. **Not** a
  consolidation target.
- **0043** (sockets UDP) is a scoped extension of **0031**; fine
  standalone. Add a one-line forward-ref from 0031's consequences.
- **0062 / 0063** correct/document **0042**'s factory sub-rule; keep
  separate (a correction earns its own record) but ensure 0042 cites
  0062 in its consequences.

## Phases

**Phase 0 — the archive rule (ships first, its own commit).** ADR 0076
+ `decisions/README.md` + AGENTS step 3 + `new-decision` skill +
CHU019, and the **first batch** (0035 → superseded-by-0036; 0004 →
inert; 0006 / 0008 → marker-renamed; fix the lone inbound link
`0009 → 0008`). 0005 left as a flagged candidate here.

**Phase 1 — drift edits (class B).** Five in-place body rewrites.
Independent; can be one commit or split by ADR.

**Phase 2 — 0017 split (class D).** Slim ADR + relocate forensics to
`docs/troubleshooting/circuitpython-ringio.md`. Update inbound refs.

**Phase 3 — 0005 disposition.** After user sign-off: archive-inert or
keep. Cross-refs from 0003 / 0016 if archived.

Phase 0 is the load-bearing one and the only one the user explicitly
asked for. Phases 1–3 are the backlog it surfaces; none blocking.

## Status

Opened 2026-05-18. Phase 0 in progress. Phases 1–3 pending, not
blocking anything.
