// Writes public/voiceover/*.mp3 from the narration in src/content.ts.
// Usage: npm run voiceover              (all ten clips)
//        npm run voiceover -- hello     (only the listed clip ids)
// Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID, from the environment or .env.
// Each run calls the paid ElevenLabs API once per clip.
// After a run, measure each clip with ffprobe and fill in CLIP_SECONDS in src/content.ts.

import {mkdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {CLIPS} from '../src/content.ts';

// Speaking rate (ElevenLabs allows 0.7 to 1.2; 1 is the voice's own pace).
const SPEED = 1.1;

const apiKey = process.env.ELEVENLABS_API_KEY;
const voiceId = process.env.ELEVENLABS_VOICE_ID;

if (!apiKey || !voiceId) {
  console.error(
    'Missing ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID. Put both in submissions/videos/intro/.env (git-ignored) or export them, then run again.',
  );
  process.exit(1);
}

const requested = process.argv.slice(2);
const clips = Object.values(CLIPS).filter(
  (clip) => requested.length === 0 || requested.includes(clip.id),
);

if (clips.length === 0) {
  console.error(
    `No clip matches ${requested.join(', ')}. Clip ids: ${Object.keys(CLIPS).join(', ')}.`,
  );
  process.exit(1);
}

const characters = clips.reduce((sum, clip) => sum + clip.narration.length, 0);
console.log(`Generating ${clips.length} clip(s), ${characters} characters.`);

const publicDir = path.join(import.meta.dirname, '..', 'public');

for (const clip of clips) {
  const response = await fetch(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
    {
      method: 'POST',
      headers: {
        'xi-api-key': apiKey,
        'Content-Type': 'application/json',
        Accept: 'audio/mpeg',
      },
      body: JSON.stringify({
        text: clip.narration,
        model_id: 'eleven_multilingual_v2',
        voice_settings: {stability: 0.5, similarity_boost: 0.75, style: 0.3, speed: SPEED},
      }),
    },
  );

  if (!response.ok) {
    console.error(
      `ElevenLabs returned ${response.status} for clip "${clip.id}": ${await response.text()}`,
    );
    process.exit(1);
  }

  const file = path.join(publicDir, clip.voiceover);
  mkdirSync(path.dirname(file), {recursive: true});
  writeFileSync(file, Buffer.from(await response.arrayBuffer()));
  console.log(`Wrote public/${clip.voiceover}`);
}
