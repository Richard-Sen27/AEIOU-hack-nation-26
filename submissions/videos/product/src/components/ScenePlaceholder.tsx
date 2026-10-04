import type React from 'react';
import type {SceneContent} from '../content';
import {COLORS} from '../theme';

// Stands in for a missing recording and doubles as its shooting guide.
export const ScenePlaceholder: React.FC<{readonly scene: SceneContent}> = ({
  scene,
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        // Extra bottom padding keeps the card clear of the lower-third caption.
        padding: '64px 96px 160px',
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          color: COLORS.accent,
          fontSize: 40,
          fontWeight: 600,
          letterSpacing: 2,
          textTransform: 'uppercase',
        }}
      >
        Scene {scene.number} of 6
      </div>
      <div
        style={{
          fontSize: 88,
          fontWeight: 700,
          lineHeight: 1.1,
          marginTop: 12,
        }}
      >
        {scene.name}
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          marginTop: 40,
        }}
      >
        {scene.shots.map((shot, index) => (
          <div
            key={shot}
            style={{
              display: 'flex',
              gap: 24,
              fontSize: 44,
              lineHeight: 1.25,
            }}
          >
            <span style={{color: COLORS.muted, minWidth: 32}}>{index + 1}</span>
            <span>{shot}</span>
          </div>
        ))}
      </div>
      <div
        style={{
          color: COLORS.muted,
          fontSize: 32,
          marginTop: 44,
        }}
      >
        Missing public/{scene.recording}
        {scene.caption ? ' · keep the lower left clear for the caption' : ''}
      </div>
    </div>
  );
};
