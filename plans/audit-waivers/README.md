# audit waivers

The central, committed registry of audit findings a human has **skipped with a reason** — so a
skipped finding stops resurfacing as fresh noise on every re-audit, and every suppression traces
back to the decision that made it.

The `/audit-code` and `/audit-branch` skills write this file. You do not hand-edit it. When you
skip a finding *and leave a note*, the skill records one entry here; on a later audit of the same
code, staging copies the matching entries into the clean room, the pipeline's actionability gate
suppresses the matching findings, and the decision page renders them greyed with your quoted note
attached. The orchestrator never filters findings on its own authority (clean-room invariant 9) —
a finding is only ever suppressed because a real entry in this ledger matches it.

## Format

`ledger.jsonl` — one JSON object per line (JSON Lines), append-only. One line per waiver:

```json
{"date": "2026-07-05", "note": "intentional — the caller caps the frame size upstream, see Decision 0106", "fingerprint": {"file": "libraries/mqtt/src/mqtt.py", "basename": "mqtt.py", "symbol": "Client._recv_exact", "symbol_leaf": "_recv_exact", "defect": "recv_exact loops without a byte bound; a short read spins", "tokens": ["bound", "byte", "loops", "read", "recv_exact", "short", "spins"]}, "angle": "hazard", "severity": "med", "target": "libraries/mqtt/src/mqtt.py", "skill": "audit-code", "run": "mqtt-20260705T101010Z"}
```

- **date** — when the waiver was recorded (UTC).
- **note** — the quoted human reason, verbatim. This is what the suppressed card shows.
- **fingerprint** — how the finding is re-identified on a later run: its **file** + **symbol** +
  a normalized **defect** token-set. Matching is fuzzy: a file that moved (basename fallback), an
  enclosing class that was renamed (symbol-leaf fallback), and a reworded defect (token overlap)
  still match; two genuinely different findings on the same symbol do not. Line numbers are never
  part of it — they shift every run.
- **angle / severity / target** — provenance, for reading the ledger by eye.
- **skill / run** — which skill wrote it, and the persisted run it came from.

## Retiring a waiver

A waiver stays in force until you delete its line. If the code changed such that the waived
concern is now a real bug you want surfaced again, remove the line — the next audit will raise the
finding normally. JSON Lines keeps this a clean one-line deletion in the diff.
