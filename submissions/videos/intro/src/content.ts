// The single source of the narration and the voiceover file names.
// Read by src/Intro.tsx (scene timing, audio) and by
// scripts/generate-voiceover.ts (the text sent to ElevenLabs). Keep this file
// free of imports and of TypeScript-only runtime syntax (enums, namespaces),
// so Node can run the voiceover script on it by stripping types.

export type ClipId =
  | 'hello'
  | 'school'
  | 'robotics'
  | 'vienna'
  | 'hackathons'
  | 'challenges'
  | 'goal'
  | 'awards'
  | 'challenge'
  | 'decision';

export type Clip = {
  readonly id: ClipId;
  // Spoken verbatim. "T.U.M." is only a spelling hint so the voice says the letters.
  readonly narration: string;
  // Path inside public/.
  readonly voiceover: string;
};

// In playback order; each clip plays over one scene (see Intro.tsx).
export const CLIPS = {
  hello: {
    id: 'hello',
    narration:
      'Hey, we are three students from Austria, starting our studies at T.U.M. next week.',
    voiceover: 'voiceover/01-hello.mp3',
  },
  school: {
    id: 'school',
    narration: 'We got to know each other at the age of 12,',
    voiceover: 'voiceover/02-school.mp3',
  },
  robotics: {
    id: 'robotics',
    narration:
      'when our journey as tech enthusiasts started at grammar school in the specialisation class for robotics.',
    voiceover: 'voiceover/03-robotics.mp3',
  },
  vienna: {
    id: 'vienna',
    narration:
      'After two years there, we continued at specialised technical high schools in Vienna, where we were taught traditional software engineering.',
    voiceover: 'voiceover/04-vienna.mp3',
  },
  hackathons: {
    id: 'hackathons',
    narration:
      'Over the years we also started to attend hackathons, with winning results.',
    voiceover: 'voiceover/05-hackathons.mp3',
  },
  challenges: {
    id: 'challenges',
    narration:
      'We love to tackle challenges in the real world that connect multiple of our interests.',
    voiceover: 'voiceover/06-challenges.mp3',
  },
  goal: {
    id: 'goal',
    narration:
      'Our goal is always to use the power of AI to solve real world problems and make a difference.',
    voiceover: 'voiceover/07-goal.mp3',
  },
  awards: {
    id: 'awards',
    narration:
      'By following these values we were able to win the national AI championship and the national AI for Green award.',
    voiceover: 'voiceover/08-awards.mp3',
  },
  challenge: {
    id: 'challenge',
    narration:
      'But today a new challenge caught our interest. Two members in our team are affected by a rare disease,',
    voiceover: 'voiceover/09-challenge.mp3',
  },
  decision: {
    id: 'decision',
    narration:
      'so when we heard of the challenge at the hackathon it was clear for us to take on this problem.',
    voiceover: 'voiceover/10-decision.mp3',
  },
} as const satisfies Record<ClipId, Clip>;

// Clip lengths in seconds, measured with
//   ffprobe -v error -show_entries format=duration -of csv=p=0 public/voiceover/<file>.mp3
// Every scene's length is derived from this table. While a value is null the
// scene uses an estimate of ESTIMATED_WORDS_PER_SECOND instead.
export const CLIP_SECONDS: Record<ClipId, number | null> = {
  hello: null,
  school: null,
  robotics: null,
  vienna: null,
  hackathons: null,
  challenges: null,
  goal: null,
  awards: null,
  challenge: null,
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
