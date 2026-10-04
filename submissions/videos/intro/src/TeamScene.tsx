import React from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {COLORS} from './theme';

export type Member = {
  name: string;
  linkedin: string;
  portrait: string;
  /** object-position for the circular crop */
  position?: string;
};

export const TeamScene: React.FC<{members: Member[]}> = ({members}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const headerIn = spring({frame, fps, config: {damping: 200}});

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        justifyContent: 'center',
        alignItems: 'center',
        gap: 70,
      }}
    >
      <div
        style={{
          color: COLORS.text,
          fontSize: 62,
          fontWeight: 800,
          opacity: headerIn,
          transform: `translateY(${interpolate(headerIn, [0, 1], [30, 0])}px)`,
        }}
      >
        The <span style={{color: COLORS.accent}}>team</span>
      </div>

      <div style={{display: 'flex', gap: 90}}>
        {members.map((member, i) => {
          const cardIn = spring({
            frame: frame - 10 - i * 7,
            fps,
            config: {damping: 16, mass: 0.8},
          });
          return (
            <div
              key={member.name}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: cardIn,
                transform: `translateY(${interpolate(
                  cardIn,
                  [0, 1],
                  [80, 0]
                )}px) scale(${interpolate(cardIn, [0, 1], [0.85, 1])})`,
              }}
            >
              <div
                style={{
                  width: 320,
                  height: 320,
                  borderRadius: '50%',
                  overflow: 'hidden',
                  border: `6px solid ${COLORS.accent}`,
                  boxShadow: '0 24px 60px rgba(0,0,0,0.55)',
                }}
              >
                <Img
                  src={member.portrait}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    objectPosition: member.position ?? '50% 50%',
                  }}
                />
              </div>
              <div
                style={{
                  color: COLORS.text,
                  fontSize: 44,
                  fontWeight: 800,
                  marginTop: 34,
                }}
              >
                {member.name}
              </div>
              <div
                style={{
                  color: COLORS.muted,
                  fontSize: 27,
                  fontWeight: 500,
                  marginTop: 10,
                }}
              >
                {member.linkedin}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
