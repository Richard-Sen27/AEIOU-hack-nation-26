# Amber product video

The 57-second walkthrough (1920×1080, 30 fps): six screen recordings, an
ElevenLabs voiceover, two captions and a logo outro. Until a file is in place,
its scene shows a placeholder card with the shot list, so the preview doubles
as the shooting guide.

## Drop files here

| Scene | Recording | Voiceover |
| --- | --- | --- |
| 1 Alex arrives (8.4 s) | `public/recordings/01-arrive.mp4` | `public/voiceover/01-arrive.mp3` |
| 2 The graph (11.3 s) | `public/recordings/02-graph.mp4` | `public/voiceover/02-graph.mp3` |
| 3 Dr. Wu (10.4 s) | `public/recordings/03-dr-wu.mp4` | `public/voiceover/03-dr-wu.mp3` |
| 4 The honest gap (10.8 s) | `public/recordings/04-gap.mp4` | `public/voiceover/04-gap.mp3` |
| 5 People (7.9 s) | `public/recordings/05-people.mp4` | `public/voiceover/05-people.mp3` |
| 6 Close (8.3 s) | `public/recordings/06-close.mp4` | `public/voiceover/06-close.mp3` |

- Recordings: 16:9 (e.g. 1920×1080 or 2560×1440), H.264 MP4. Their sound is
  muted. Scenes 3 and 6 put a caption over the lower-left corner, so keep that
  area free of anything important.
- Scene 6 shows the recording for about 5 s, then the logo fades in over it.
- Names must match exactly. A missing file is skipped; a take shorter than
  its slot freezes on its last frame.

## Preview

```console
npm i
npm run dev
```

Open `ProductVideo`. Each scene is also its own composition under `Scenes`.
Files you drop in show up in the open Studio after a few seconds.

## Voiceover

The narration lives in `src/content.ts` (with the shot lists and captions).
Put your key and voice in `.env` (git-ignored):

```
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

```console
npm run voiceover           # all six scenes
npm run voiceover -- gap    # only some scenes (ids: arrive graph dr-wu gap people close)
```

Each run costs ElevenLabs credits. Each clip plays from the start of its scene,
so it has to fit the slot (check in the preview).

## Adjust timing

- **Where a take starts and how fast it plays:** in `src/scenes/<Scene>.tsx`,
  on the `<Video>`: `trimBefore` is the first frame of the take to show
  (frames, 30 per second: `90` skips 3 s) and `playbackRate` is the speed
  (`2` is twice as fast). A slot of N frames uses N × `playbackRate` frames
  of the take after `trimBefore`. Both can also be edited in the Studio
  timeline.
- **Scene length:** `durationInFrames` on the scene's `<Series.Sequence>` in
  `src/ProductVideo.tsx`. Then set the same total on `ProductVideo` in
  `src/Root.tsx` (and the scene's own composition there). The preview and
  the render stop with an error if the scenes and the total disagree, or if
  the total passes 1800 frames (the 60 s limit).
- **Captions and outro:** `from` / `durationInFrames` on `<Caption>` and
  `<LogoOutro>` in `DrWuScene.tsx` and `CloseScene.tsx`.

## Render

```console
npm run render    # writes out/product.mp4
```

A render uses the files in `public/` at the moment it starts.
