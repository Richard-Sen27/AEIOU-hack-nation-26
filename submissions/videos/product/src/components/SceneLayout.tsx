import type React from 'react';
import {AbsoluteFill} from 'remotion';
import {COLORS, FONT, FRAME} from '../theme';

// Dark backdrop shared by every scene.
export const SceneLayout: React.FC<{readonly children: React.ReactNode}> = ({
  children,
}) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        fontFamily: FONT,
        color: COLORS.text,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

// A restrained 16:9 frame that holds the screen recording or its placeholder.
export const RecordingFrame: React.FC<{readonly children: React.ReactNode}> = ({
  children,
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: FRAME.left,
        top: FRAME.top,
        width: FRAME.width,
        height: FRAME.height,
        borderRadius: 16,
        overflow: 'hidden',
        backgroundColor: COLORS.surface,
        boxShadow:
          '0 0 0 1px rgba(0, 0, 0, 0.1), 0 32px 80px rgba(0, 0, 0, 0.16)',
      }}
    >
      {children}
    </div>
  );
};
