// regen-comments VOICE-PREVIEW workflow. Run inside ONE `claude -p` from a /tmp room. Renders each voice
// against ONE fixed neutral subject in free prose (NO code), so the sample exposes the true voice for the
// pick menu. Each voice writes its paragraph to <RUNDIR>/previews/<key>.txt; the driver merges them into
// voices.json under "previews". Orchestrator substitutes __RUNDIR__ and __VOICES_JSON__ ([{key, para}]).

export const meta = {
  name: 'regen-voice-preview',
  description: 'Render each voice against a fixed no-code subject so the pick menu can preview the voice.',
  phases: [{ title: 'Preview', detail: 'one sample per voice, fixed subject' }],
}

const RUNDIR = '__RUNDIR__'
// Fixed across all voices: meaty enough to expose voice, technical register (these voices document code),
// but NO code, so the voice itself carries the sample rather than the syntax.
const SUBJECT = 'Explain what a FIFO buffer (a first-in, first-out queue) is and why it matters, in 3 to 5 sentences.'
const VOICES = __VOICES_JSON__ // [{ key, para }]

const OUT = { type: 'object', additionalProperties: false, properties: { path: { type: 'string' } }, required: ['path'] }

phase('Preview')
await parallel(VOICES.map((v) => () =>
  agent(
    'Write 3 to 5 sentences on the SUBJECT, in the VOICE. Prose only: NO code, NO lists, NO headings, NO '
    + 'preamble -- just the paragraph, so the voice is what shows. Write ONLY your paragraph (plain text, no '
    + 'quotes, no JSON) to ' + RUNDIR + '/previews/' + v.key + '.txt and reply DONE.\n\n'
    + 'VOICE: ' + v.para + '\n\nSUBJECT: ' + SUBJECT,
    { label: 'preview:' + v.key, phase: 'Preview', model: 'opus', agentType: 'general-purpose', schema: OUT },
  )
))
return { generated: VOICES.map((v) => v.key) }
