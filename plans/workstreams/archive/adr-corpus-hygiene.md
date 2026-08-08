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

**Phase 1 — drift edits (class B). DONE — mostly phantom.**
Verification against the actual ADR bodies (not the sub-agent
reports, which described the *relationship* not the file state)
found 0047 §3, 0016's `_pytest`/directory paragraphs, 0037 §3, and
0048 §3 were **already maintained in place** when their superseders
landed — each already carries the current rule + an inline forward
cross-link. The only genuine gap was the missing *upward* link: 0049
(the umbrella) cited 0003/0016 but neither cited up to 0049. Fixed:
0003 gained a `Related:` + one Context clause naming Decision 0049 as
the founding principle; 0016 gained a proportionate `Related:`
pointer (its body already explains the three-runtime model). No
status changes — all stay `accepted`.

**Phase 2 — 0017 split (class D). DONE.** 0017 slimmed from ~149 to
~45 lines (Context / Decision incl. the "why not the coverage
variant" rejected-alternative / Consequences). Forensics relocated to
[`../../docs/troubleshooting/circuitpython-ringio.md`](../../../docs/troubleshooting/circuitpython-ringio.md),
listed in that directory's README (Guides + Related-ADR, mirroring
the 0033 ↔ macos-circuitpy precedent). 0017 stays `accepted` and
keeps its filename, so the `scripts/prepare_circuitpython.py` comment
ref and CHU019 are unaffected.

**Phase 3 — 0005 disposition. DONE — archived inert.** Verified
inert: an explicitly provisional early-phase Windows-host intent,
never operationalized (no live setup doc adopted "native CPython +
WSL2"; only an *archived* workstream restates it), and the current
posture moved past it (deploy hard-refuses native Windows; docs say
Windows unsupported). No successor ADR → not `superseded`. Renamed
`0005-INERT-...`, `Status:` stays `accepted`, `Archived:` field
added; the one inbound link (an archived workstream) fixed.

Phase 0 was the load-bearing one and the only one the user explicitly
asked for; Phases 1–3 are the backlog it surfaced, now cleared. The
class-E ADRs (0056 / 0012 / 0026) are deliberately left as-is — the
note stands: stop *creating* that class, don't churn history to tidy
it. Class-F polish DONE: 0031's Consequences gained a one-line forward-ref
to Decision 0043 (UDP extends the TCP/TLS charter, doesn't replace
it); 0042's `Related:` now lists 0062/0063 (its body already cited
0062 three times — only the header back-pointer was missing). No
status changes.

## Status

Opened 2026-05-18. Phase 0 shipped (commit `de2d96dd`). Phases 1–3
complete in the working tree, **uncommitted** — the user is
orchestrating one combined commit with handoff notes alongside a
concurrent agent's work; this workstream's remaining edits (the
0003/0016 `Related:`+clause, the 0017 split + new troubleshooting
doc, the 0005 inert rename) ride in that commit. Nothing blocking.
