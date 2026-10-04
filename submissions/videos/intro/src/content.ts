// The single source of the narration and the voiceover file names.
// Read by src/Intro.tsx (scene timing, audio) and by
// scripts/generate-voiceover.ts (the text sent to ElevenLabs). Keep this file
// free of imports and of TypeScript-only runtime syntax (enums, namespaces),
// so Node can run the voiceover script on it by stripping types.

export type ClipId =
  | 'hello'
  | 'studies'
  | 'school'
  | 'robotics'
  | 'vienna'
  | 'hackathons'
  | 'challenges'
  | 'goal'
  | 'awards'
  | 'challenge'
  | 'members'
  | 'decision';

export type Clip = {
  readonly id: ClipId;
  // Spoken verbatim ("Tum" is written so the voice says it as a word).
  readonly narration: string;
  // Path inside public/.
  readonly voiceover: string;
};

// In playback order. Intro.tsx assigns each clip to the scene it plays over.
export const CLIPS = {
  hello: {
    id: 'hello',
    narration: 'Hey, we are three students from Austria,',
    voiceover: 'voiceover/01-hello.mp3',
  },
  studies: {
    id: 'studies',
    narration: 'starting our studies at Tum next week.',
    voiceover: 'voiceover/02-studies.mp3',
  },
  school: {
    id: 'school',
    narration: 'We got to know each other at the age of 12,',
    voiceover: 'voiceover/03-school.mp3',
  },
  robotics: {
    id: 'robotics',
    narration:
      'when our journey as tech enthusiasts started at grammar school in the specialisation class for robotics.',
    voiceover: 'voiceover/04-robotics.mp3',
  },
  vienna: {
    id: 'vienna',
    narration:
      'After two years there, we continued at specialised technical high schools in Vienna, where we were taught traditional software engineering.',
    voiceover: 'voiceover/05-vienna.mp3',
  },
  hackathons: {
    id: 'hackathons',
    narration:
      'Over the years we also started to attend hackathons, with winning results.',
    voiceover: 'voiceover/06-hackathons.mp3',
  },
  challenges: {
    id: 'challenges',
    narration:
      'We love to tackle challenges in the real world that connect multiple of our interests.',
    voiceover: 'voiceover/07-challenges.mp3',
  },
  goal: {
    id: 'goal',
    narration:
      'Our goal is always to use the power of AI to solve real world problems and make a difference.',
    voiceover: 'voiceover/08-goal.mp3',
  },
  awards: {
    id: 'awards',
    narration:
      'By following these values we were able to win the national AI championship and the national AI for Green award.',
    voiceover: 'voiceover/09-awards.mp3',
  },
  challenge: {
    id: 'challenge',
    narration: 'But today a new challenge caught our interest.',
    voiceover: 'voiceover/10-challenge.mp3',
  },
  members: {
    id: 'members',
    narration: 'Two members in our team are affected by a rare disease,',
    voiceover: 'voiceover/11-members.mp3',
  },
  decision: {
    id: 'decision',
    narration:
      'so when we heard of the challenge at the hackathon it was clear for us to take on this problem.',
    voiceover: 'voiceover/12-decision.mp3',
  },
} as const satisfies Record<ClipId, Clip>;

// Clip lengths in seconds, measured with
//   ffprobe -v error -show_entries format=duration -of csv=p=0 public/voiceover/<file>.mp3
// Every scene's length is derived from this table. While a value is null the
// scene uses an estimate of ESTIMATED_WORDS_PER_SECOND instead.
export const CLIP_SECONDS: Record<ClipId, number | null> = {
  hello: null,
  studies: null,
  school: null,
  robotics: null,
  vienna: null,
  hackathons: null,
  challenges: null,
  goal: null,
  awards: null,
  challenge: null,
  members: null,
  decision: null,
};

export const ESTIMATED_WORDS_PER_SECOND = 2.6;

export const clipSeconds = (id: ClipId): number => {
  const measured = CLIP_SECONDS[id];
  if (measured !== null) {
    return measured;
  }
  const words = CLIPS[id].narration.split(/\s+/).filter(Boolean).length;
  return words / ESTIMATED_WORDS_PER_SECOND;
};
