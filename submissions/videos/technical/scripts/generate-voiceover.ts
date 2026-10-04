// Writes public/voiceover/*.mp3 from the narration in src/content.ts.
// Usage: npm run voiceover                 (all six scenes)
//        npm run voiceover -- clusters     (only the listed scene ids)
// Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID, from the environment or .env.
// Each run calls the ElevenLabs API once per scene and spends characters
// from the account's quota; the script prints how many.

import {mkdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {SCENES} from '../src/content.ts';

const apiKey = process.env.ELEVENLABS_API_KEY;
const voiceId = process.env.ELEVENLABS_VOICE_ID;

if (!apiKey || !voiceId) {
  console.error(
    'Missing ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID. Put both in submissions/videos/technical/.env (git-ignored) or export them, then run again.',
  );
  process.exit(1);
}

const requested = process.argv.slice(2);
const scenes = Object.values(SCENES).filter(
  (scene) => requested.length === 0 || requested.includes(scene.id),
);

if (scenes.length === 0) {
  console.error(
    `No scene matches ${requested.join(', ')}. Scene ids: ${Object.keys(SCENES).join(', ')}.`,
  );
  process.exit(1);
}

const publicDir = path.join(import.meta.dirname, '..', 'public');
let characters = 0;

for (const scene of scenes) {
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
        text: scene.narration,
        model_id: 'eleven_multilingual_v2',
        voice_settings: {stability: 0.5, similarity_boost: 0.75, style: 0.3},
      }),
    },
  );

  if (!response.ok) {
    console.error(
      `ElevenLabs returned ${response.status} for scene "${scene.id}": ${await response.text()}`,
    );
    process.exit(1);
  }

  const file = path.join(publicDir, scene.voiceover);
  mkdirSync(path.dirname(file), {recursive: true});
  writeFileSync(file, Buffer.from(await response.arrayBuffer()));
  characters += scene.narration.length;
  console.log(`Wrote public/${scene.voiceover} (${scene.narration.length} characters)`);
}

console.log(`Sent ${characters} characters to ElevenLabs.`);
