# Secondary library docs consistency spec

Date: 2026-07-28
Status: working input for the respec pass

The GA docs pass (2026-07-19) rewrote all 14 library README + guide pairs to
one consistency spec. This spec extends the same bar to the three secondary
pages each library carries: `docs/index.md`, `docs/api.md`, and
`docs/testing.md`. Recon on 2026-07-28 found 92 em-dashes across 33 of the 34
secondary pages, five different api.md heading conventions, broken quick
examples on four index pages, and one page documenting a removed API. The
scaffold templates (`chumicro_workspace/_payloads/library_template/`) must
match this spec too, so a new library starts life on it.

Voice: the style guide's "Documentation tone" and "Voice" sections apply in
full. Zero em-dashes, including table cells and comments. No sibling-package
redirects. No type-system jargon. Measured claims trace to code or get cut.

## index.md

Shape, in order:

1. `# chumicro-<name>` (the PyPI project name)
2. Bold one-liner on its own line.
3. Body paragraph, one to four sentences.
4. `## Quick example` with a snippet that imports and runs against the
   installed package. Where a radio is needed, construct it the way the root
   README hero does (verify against `README.md` and
   `chumicro_wifi.WifiService`); never reference an undefined `wifi` name.
5. `## Documentation` bullets. Separator is a colon, and each description
   names real content:
   - `- [User Guide](guide.md): <the guide's actual top-level topics>`
   - `- [API Reference](api.md): <one concrete clause>`
   - `- [Testing Helpers](testing.md): using <FakeX> in your tests`
     (only where testing.md exists; name the actual fake class)
6. The standard footer div (`chumicro-footer`, back-link, then
   Source / PyPI / Bundle / Experimental Bundle on `· \` continuations).

The one-liner and body must agree with the library's own README (same scope,
same runtime claims). A parked library carries the same parked banner its
README carries.

## api.md

- No scaffold guidance comments. Delete them; authoring guidance lives in
  `docs/contributing/new-library.md`.
- Heading convention: one `## ` heading per documented module, the fully
  qualified module path in backticks (for example `` ## `chumicro_sockets.generators` ``).
- One `:::` section per public module a consumer imports from. Private
  modules (leading underscore) are not documented.
- Footer: the same footer div as index.md, with `· \` line continuations.
- PyPI links use the hyphenated project slug.

## testing.md

- Consumer-framed: the section previously titled "Usage from other
  libraries" is `## Using these fakes in your own tests`, and its body
  addresses the reader's test suite, not sibling libraries.
- Every testing.md states the bundle exclusion up front (the `testing`
  module is excluded from device bundles by name; verify against
  `chumicro_deploy` sources before asserting).
- Closing line, exactly: `Project convention: libraries that expose
  injectable services ship their own test fakes alongside the production
  code.`
- Signatures shown as the code defines them (keyword-only stays
  keyword-only). Every documented symbol exists and is public.
- No repo-relative pointers (`tests/test_...py`); show the pattern inline.
- Paragraphs unwrapped (no hard wrap at a fixed column).

A library ships a testing.md if and only if it ships a `testing.py`.
