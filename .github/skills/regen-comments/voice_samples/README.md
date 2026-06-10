# voice_samples — real-text excerpts per voice

One file per `voices.json` key, except `plain` (voiceless by design). Each file holds a short, unmodified excerpt of real text by the person the voice was drawn from, with source attribution.

Why natural-domain prose and not code comments: none of these people wrote docstrings, so the only real text that exists is in their own genre. Why unmodified: sentence breaks and pacing carry the voice, and flattening or clipping a sample destroys the signal it exists to provide.

Consumption: `voice_sample.py` extracts the `## Excerpt` prose (never this header metadata), and `regen_phase2.py` / `regen_symbol.py` substitute it into `writers_wf.js`, where voiced writer prompts carry it as a register sample — word choice, rhythm, and attitude, with the genre shape rules still owning the format. A second use stays open: distilling concrete mechanics from the excerpt into richer personas or curated in-genre exemplar docstrings.

Rights: `hemingway` is public domain in the USA; `torvalds` is a public mailing-list post; the rest are short attributed excerpts held as internal prompt data. Keep excerpts short, and trim further before any public release of this tree.

Transcript caveats: `linus` and `pewdiepie` are YouTube auto-captions, so expect ASR punctuation and occasional mis-hearings; each file's header notes any corrections or trims. The `linus` source show is two-host, so excerpts are cut to monologue stretches that are safely his.
