# Amber technical video

The 60-second technical video (1920×1080, 30 fps, 1,788 frames, 59.6 s) for the
Hack-Nation 7 submission: how Amber is built, shown as animated diagrams in
the web app's light colour scheme, with two Atlas screenshots and an
ElevenLabs voiceover (voice "Alice"). The product video next door covers the
user journey; this one covers the engineering.

Facts, names and numbers come from `docs/current-state.md` (data version
`2026-10-04.24`) and from GET requests to the local API; `src/content.ts`
says which, per block.

## Scenes

| # | Scene | Frames | Shows |
| --- | --- | --- | --- |
| 1 | Sources | 242 | 13 public sources → `atlas-pipeline` stages → node, edge and evidence-row totals |
| 2 | Verified extraction | 322 | A real abstract (PMID 24434335), the extracted relation, `quote_in_text`, 1,188 / 1,202 quotes, 697 inferred relations excluded |
| 3 | Confidence | 323 | The confidence formula, the 40 evidence rows of Dravet syndrome → SCN1A, a computed link stopped at the 0.79 cap |
| 4 | Clusters by mechanism | 277 | SCN1A with Dravet syndrome (loss of function) and familial hemiplegic migraine 3 (gain of function) pushed into CLUSTER:4 and CLUSTER:55 |
| 5 | Checked agent | 347 | Presidio → LangGraph turn (safety, entities, agent with 6 tools, postcheck) → one draft claim removed at the gate |
| 6 | Atlas | 277 | Atlas screenshots, server-to-WebGL chain, line style per origin, logo |

On-screen text is limited to labels (names, ids, numbers, the formula); it
never repeats the narration.

## Files

- `src/content.ts`: narration, measured voiceover lengths and the data each
  diagram shows. The only place to change words.
- `src/theme.ts`: colour tokens copied from `apps/frontend/src/app/globals.css`
  (light), fonts (Archivo, JetBrains Mono), safe area.
- `src/TechnicalVideo.tsx`: the timeline and the duration guard.
- `src/Root.tsx`: `TechnicalVideo` and one composition per scene (folder `Scenes`).
- `src/scenes/*.tsx`: one file per scene; `src/components/SceneFrame.tsx`:
  backdrop, code-location label and voiceover.
- `public/voiceover/*.mp3`, `public/screens/*.jpg` (captured from the running
  app as a signed-out guest), `public/brand/amber-logo.webp`.
- `scripts/generate-voiceover.ts`: ElevenLabs text-to-speech, one clip per scene.

## Preview

```console
npm i
npm run dev
```

Open `TechnicalVideo`, or a scene under `Scenes`.

## Regenerate a voiceover clip

Put the key and voice in `.env` (git-ignored):

```
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

```console
npm run voiceover -- clusters     # one scene (ids: sources extract confidence clusters agent atlas)
npm run voiceover                 # all six; spends about 820 characters of quota
```

Then measure the clip and update `voiceFrames` for that scene in
`src/content.ts` (frames at 30 fps, rounded up):

```console
ffprobe -v error -show_entries format=duration -of csv=p=0 public/voiceover/04-clusters.mp3
```

## Change timing

- **Scene length:** `durationInFrames` on the scene's `<Series.Sequence>` in
  `src/TechnicalVideo.tsx`, the scene's own `<Composition>` in `src/Root.tsx`,
  and the `TechnicalVideo` total in `src/Root.tsx`. The preview and any render
  stop with an error if the total passes 1,800 frames (60 s), if the scenes
  and the total disagree, or if a scene is shorter than its voiceover
  (`VOICE_DELAY` + `voiceFrames`).
- **When things appear inside a scene:** the `T` table at the top of each
  scene file (frames from the scene start, with the narration timing noted
  above it).

## Render

```console
npm run render                      # writes out/technical.mp4
npm run still -- out/frame.png --frame=900
```
