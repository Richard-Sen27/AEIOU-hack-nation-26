import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {COLORS} from './theme';

export const TitleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const letters = 'Amber'.split('');

  const subtitleIn = spring({frame: frame - 22, fps, config: {damping: 200}});
  const taglineIn = spring({frame: frame - 34, fps, config: {damping: 200}});

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <div style={{display: 'flex', gap: 10}}>
        {letters.map((letter, i) => {
          const pop = spring({
            frame: frame - i * 4,
            fps,
            config: {damping: 12, mass: 0.6},
          });
          return (
            <span
              key={i}
              style={{
                color: COLORS.accent,
                fontSize: 220,
                fontWeight: 900,
                letterSpacing: 8,
                display: 'inline-block',
                transform: `scale(${pop}) translateY(${interpolate(
                  pop,
                  [0, 1],
                  [60, 0]
                )}px)`,
                opacity: pop,
              }}
            >
              {letter}
            </span>
          );
        })}
      </div>

      <div
        style={{
          color: COLORS.text,
          fontSize: 44,
          fontWeight: 700,
          letterSpacing: 12,
          textTransform: 'uppercase',
          marginTop: 10,
          opacity: subtitleIn,
          transform: `translateY(${interpolate(subtitleIn, [0, 1], [30, 0])}px)`,
        }}
      >
        Hack-Nation 7 · 2026
      </div>

      <div
        style={{
          color: COLORS.muted,
          fontSize: 34,
          fontWeight: 500,
          marginTop: 28,
          opacity: taglineIn,
          transform: `translateY(${interpolate(taglineIn, [0, 1], [30, 0])}px)`,
        }}
      >
        Meet the team
      </div>
    </AbsoluteFill>
  );
};
