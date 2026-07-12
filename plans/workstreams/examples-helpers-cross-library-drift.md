# Workstream: examples/helpers.py cross-library drift

Status: **shipped 2026-07-11.** Surfaced 2026-05-20 by `/audit-workspace` in routed-finding mode against a duplication finding originally raised during the repo-wide `/audit-comments` sweep. The same 340-LOC `examples/helpers.py` ships in six network-using libraries, with four byte-identical copies and two already drifted after per-library audit-comments passes.

Shipped as option (b), scaffold + sync. The canonical body reconciles the dominant 340-line copy with the mqtt and websockets de-em-dashing, the requests docstring compressions, and a dropped set of `chumicro_timing` / `chumicro_wifi` internal cross-references; its top docstring now names `scripts/templates/examples_helpers.py` and the preflight drift check as its source of truth. That 330-line body lives at `scripts/templates/examples_helpers.py`, the new-library scaffold emits it, and all six library copies plus the scaffold payload template are resynced byte-for-byte. A new drift lint, `CHU035`, fails preflight when any copy diverges. By ship time the drift had spread past the two copies the evidence table below records: sockets, websockets, and the scaffold payload template had each drifted too, so seven copies were reconciled onto the canon, not six.

## Evidence

md5 + line counts at HEAD (`128297f3a22a859ad388645b851d8f89` is the dominant body):

| Library | md5 | lines | bytes |
|---|---|---|---|
| `http_server/examples/helpers.py` | `128297f3…` | 340 | 13867 |
| `ntp/examples/helpers.py` | `128297f3…` | 340 | 13867 |
| `sockets/examples/helpers.py` | `128297f3…` | 340 | 13867 |
| `websockets/examples/helpers.py` | `128297f3…` | 340 | 13867 |
| `mqtt/examples/helpers.py` | `ede0d8f9…` | 336 | 13521 |
| `requests/examples/helpers.py` | `5f9fb0f3…` | 327 | 12923 |

The mqtt and requests copies have been through `/audit-comments` passes that the other four have not, so the drift is the audit log, not random divergence. mqtt's diff swaps an em-dash, compresses two CYW43 comments, and rewrites the `_CYW43_MACHINES` module docstring. requests's diff goes further, dropping cross-references to `chumicro_timing` and `chumicro_wifi` internals plus the rationale that Decision 0013 owns better than an inline comment does.

11 example scripts across the six libraries import from `helpers`: `http_server/simple_server.py`, `mqtt/{bench,telemetry}.py`, `ntp/ntp_query.py`, `requests/periodic_get.py`, `sockets/{tcp_roundtrip,tls_with_custom_ca,udp_echo_client}.py`, `websockets/{client,server}.py`.

## Three defects ride on this drift

1. **Decision 0013 line 45 is false.** The ADR claims "Each library's helpers.py is identical (md5-verified)." Two of six copies are not.
2. **The file lies about its own source of truth.** Its top docstring says "the canonical source lives in the new-library scaffold so a fresh library starts with a working copy." Neither `scripts/new_library_scaffold.py` nor `scripts/templates/` contains a `helpers.py` source. A new network-using library scaffolded today gets no `examples/helpers.py` at all.
3. **The lint Decision 0013 line 47 defers** ("not yet shipped") is exactly the drift class Decision 0074 says must be deterministically linted.

## Decision space considered

(a) **Shared support package** under `support/example_helpers/`. **Ruled out** by Decision 0013 line 41, which restricts example imports to owning library, declared deps, or sibling files in `examples/`. A `support/` import is none of these, and on-device deploys would need to either ship the support tree to every device or invent a build-time inline step. The original bullet's "Promotion candidate for `support/example_helpers`" wording predates this re-read of 0013.

(b) **Scaffold + sync.** Pick a canonical body, place it in `scripts/templates/`, have the scaffold emit it for new libraries, add a drift lint that fails preflight when any `libraries/*/examples/helpers.py` diverges. **Recommended.** Matches what Decision 0013 already specifies, fills the lint gap Decision 0013 line 47 calls "not yet shipped", and aligns with Decision 0074.

(c) **Documented contract only.** Decision 0013 already documents the contract. Without enforcement, the contract is what's drifting today.

(d) **Accept the drift.** Discounts both ADRs and the cost of propagating a bug-fix across six copies (each new CYW43 MicroPython board would mean six edits, six chances to miss one).

## What "good" looks like

* One canonical body, in `scripts/templates/examples_helpers.py`.
* `python scripts/run.py preflight` fails when any `libraries/<lib>/examples/helpers.py` diverges from the template, with an error that names the diverging file.
* `python scripts/run.py new-library <name>` emits the helper into the new library's `examples/` directory, with the file's own docstring telling non-network libraries to delete it (the instruction already in the body).
* Decision 0013 line 45 is true again because the lint enforces it. The file's top docstring points at its real source of truth.

## Design surface (to resolve in the implementing session)

* **Which body becomes canon.** Two candidates:
  * The 340-line body in the four byte-identical copies, untouched by recent comment audits.
  * A re-audited body that folds mqtt's and requests's prose improvements into one canonical form. Preferred path: run `/audit-comments` on `http_server/examples/helpers.py` (cleanest starting point), accept the result as canon, then resync the other five onto it.
* **Template location.** `scripts/templates/examples_helpers.py`. Sibling files in that directory use a `.template` suffix only for files needing string substitution. `examples_helpers.py` ships verbatim, so plain `.py` is correct.
* **Scaffold trigger.** Always emit, matching the file's existing self-description that says non-network libraries should delete it. A `--network` flag is a YAGNI alternative.
* **Lint surface.** A new check in `workbench/checks/` (next-free `CHU` code) that compares each `libraries/*/examples/helpers.py` to `scripts/templates/examples_helpers.py` and flags any byte divergence.
* **Per-library variation.** None of the six current copies needs it. If a future library does, a sigil-delimited block (`# LIB-SPECIFIC BEGIN` / `# LIB-SPECIFIC END`) the lint ignores would be the extension point. Defer.

## Corrective ADR work

Decision 0013 line 45 currently claims md5-identity that doesn't hold. After this workstream lands, edit line 45 in place to read "Each library's helpers.py is byte-identical to `scripts/templates/examples_helpers.py`, enforced by preflight." Drop "md5-verified" because the mechanism is the lint, not a manual md5.

Decision 0013 line 47 is a *different* lint (example-import-rule enforcement, not drift). Leave that line untouched. This workstream ships drift enforcement only.

## Out of scope

* The example-import-rule lint of Decision 0013 line 47.
* Cross-library duplication in non-examples surfaces, including the `test_client_*.py` helper duplication tracked separately in `plans/next-up.md`.
* Renaming `examples/helpers.py` or restructuring example layout.

## Sizing

Medium. One new template file, ~30 LOC scaffold-emit code, ~80 LOC drift lint + tests, six `helpers.py` resyncs (verbatim copy once the canon is chosen), one ADR body edit. One focused session if the canon is picked up front, two if `/audit-comments` runs on the chosen leaf first.
