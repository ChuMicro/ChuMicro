# Broad library triage (library-aware mode)

Used only in the library-aware path (multiple files in one library). Run as ONE `claude -p` from the run
room, with the library's source subtree copied under `./lib/` (preserving subpackages). It emits
`./LIBRARY_FACTS.md` — the compact cross-file ledger that then rides into every per-file room as context
(the per-file triage + writers consult it; the per-file CODE stays source-of-truth for that file).

Invocation: `claude -p "$(cat this-prompt)" --allowedTools Read Grep Glob Write --permission-mode acceptEdits --model opus`

## Prompt

You are doing BROAD LIBRARY triage (fixture-agnostic, no prior knowledge of this library). Read EVERY
Python file under ./lib/ (including subpackages). Produce a COMPACT library ledger of CROSS-CUTTING facts
that a per-file docstring writer needs but cannot get from any single file alone. Three sections only:

1. DOMAIN: what this library does, in plain real-world terms (1-2 sentences).
2. CONTRACTS: any protocol / interface / abstract base / shared dataclass defined in one file and
   implemented or consumed by others. Name it, its key methods + invariants, and WHICH files
   implement/use it. This is the spine of library-awareness.
3. GLOSSARY: terms, types, or concepts used across multiple files that carry a specific meaning here
   (telegraphic definitions).

Rules: telegraphic, no invented facts (verify against the code), do NOT dump per-file internal detail
(that is the per-file triage's job), no fixture/test knowledge. Write to ./LIBRARY_FACTS.md. After
writing, reply DONE.
