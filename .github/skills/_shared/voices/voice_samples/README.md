# voice_samples — real-text excerpts per voice

A file per `voices.json` key that has one, except `plain` (voiceless by design). Each file holds a short, unmodified excerpt of real text by the person the voice was drawn from, with source attribution. A voice with no file here still works: `load_voice_sample` returns `""` and the writer runs persona-only.

Why natural-domain prose and not code comments: none of these people wrote docstrings, so the only real text that exists is in their own genre. Why unmodified: sentence breaks and pacing carry the voice, and flattening or clipping a sample destroys the signal it exists to provide.

Consumption: `voice_sample.py` extracts the `## Excerpt` prose (never this header metadata), and `regen_phase2.py` / `regen_symbol.py` substitute it into `writers_wf.js`, where voiced writer prompts carry it as a register sample — word choice, rhythm, and attitude, with the genre shape rules still owning the format. A second use stays open: distilling concrete mechanics from the excerpt into richer personas or curated in-genre exemplar docstrings.

Rights: this tree is public, so only excerpts anyone may redistribute live here. `hemingway` is public domain in the USA; `torvalds` is a public mailing-list post. Excerpts held under fair use as internal prompt data were removed before the repo went public, and their voices now run persona-only. Do not add a sample whose rights you cannot state in its header, and keep every excerpt short.

## Sourcing a sample (when adding a voice)

The hunt is in-session orchestrator work (web search plus judgment), not script work. Rules that held up in practice:

- Real text only, in the person's natural domain. Pick the era whose register matches the persona — early and late writing by the same person can differ more than two different people, so a sample swap between eras is worth documenting in the file header. Register fit is the only era criterion: an exemplar teaches in-context, so it does not need to overlap the model's training data, and for transcripts a recent punctuated capture beats an older unpunctuated one every time.
- 1–3 whole paragraphs, unmodified, roughly 150–400 words total. Cut at paragraph boundaries; never flatten or clip mid-sentence — pacing carries the voice. Obvious OCR or ASR mis-hearings may be corrected with a note in the header.
- No person's name inside the excerpt prose. The loader strips only the header, so trim sign-offs and bylines and note the trim in the header.
- Attribution (person, source title, date, URL, register, rights) lives ONLY in the header bullets.
- Fetch routes that worked: LKML via the IU hypermail mirror (`lkml.iu.edu`, plain HTML — lkml.org and lore.kernel.org block automated fetches, and the Wayback Machine gets past both); `textutil -convert txt` extracts article HTML; YouTube transcripts via `youtube-transcript-api` in a `.scratch/` venv (recent uploads' auto-captions carry punctuation, but auto-captions on older videos — 2023 and earlier — are unpunctuated run-ons that destroy the rhythm signal, and older MANUAL caption tracks are often fan-made with editorial jokes that are not the speaker's words); paywalled Substack pages serve a different post's free preview, so verify the text matches the post you asked for; RealWorldTech forum threads (Torvalds' written-argument register) serve plain HTML, while the LTT forum sits behind a bot challenge.
- Verify before relying on it: `python3 ../voice_sample.py <key>` must print prose only.
