import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {COLORS} from './theme';

export const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const titleIn = spring({frame, fps, config: {damping: 14, mass: 0.7}});
  const lineIn = spring({frame: frame - 14, fps, config: {damping: 200}});
  const footerIn = spring({frame: frame - 26, fps, config: {damping: 200}});

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <div
        style={{
          color: COLORS.text,
          fontSize: 110,
          fontWeight: 900,
          opacity: titleIn,
          transform: `scale(${interpolate(titleIn, [0, 1], [0.8, 1])})`,
        }}
      >
        Let&apos;s <span style={{color: COLORS.accent}}>build</span>.
      </div>

      <div
        style={{
          width: interpolate(lineIn, [0, 1], [0, 420]),
          height: 5,
          borderRadius: 3,
          backgroundColor: COLORS.accent,
          marginTop: 44,
        }}
      />

      <div
        style={{
          color: COLORS.muted,
          fontSize: 32,
          fontWeight: 600,
          letterSpacing: 5,
          textTransform: 'uppercase',
          marginTop: 44,
          opacity: footerIn,
        }}
      >
        Amber · Hack-Nation 7 · 2026
      </div>
    </AbsoluteFill>
  );
};
