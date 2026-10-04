import {Audio} from '@remotion/media';
import type React from 'react';
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {VOICE_DELAY, type SceneContent} from '../content';
import {COLORS, FONT, MONO, SAFE} from '../theme';
import {usePublicFile} from '../use-public-file';

// Light backdrop with the app's map grid, the scene's code location in the
// top-left corner, and the scene's voiceover. Frame 0 is the scene start.
export const SceneFrame: React.FC<{
  readonly scene: SceneContent;
  // Where in the repository the scene's mechanism lives (a label, not a sentence).
  readonly codePath: string;
  readonly children: React.ReactNode;
}> = ({scene, codePath, children}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const voiceoverSrc = usePublicFile(scene.voiceover);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        backgroundImage: `linear-gradient(${COLORS.gridLine} 1px, transparent 1px), linear-gradient(90deg, ${COLORS.gridLine} 1px, transparent 1px)`,
        backgroundSize: '48px 48px',
        fontFamily: FONT,
        color: COLORS.foreground,
        // Short fade in and out so cuts between scenes are soft.
        opacity: interpolate(
          frame,
          [0, 6, durationInFrames - 6, durationInFrames],
          [0, 1, 1, 0],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
        ),
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: SAFE.left,
          top: SAFE.top,
          fontFamily: MONO,
          fontSize: 26,
          color: COLORS.mutedForeground,
          letterSpacing: 0.2,
        }}
      >
        {codePath}
      </div>
      {children}
      {voiceoverSrc ? (
        <Audio
          key={voiceoverSrc}
          name="Voiceover"
          src={voiceoverSrc}
          from={VOICE_DELAY}
          volume={1}
          premountFor={fps}
        />
      ) : null}
    </AbsoluteFill>
  );
};
