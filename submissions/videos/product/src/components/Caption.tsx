import type React from 'react';
import {Interactive, type InteractivitySchema} from 'remotion';
import {COLORS, FONT} from '../theme';

type CaptionProps = {
  readonly children: string;
  readonly style?: React.CSSProperties;
};

// Lower third: sits over the lower-left corner of the recording frame,
// inside the safe area and clear of the frame's centre.
const CaptionInner: React.FC<CaptionProps> = ({children, style}) => {
  return (
    <Interactive.Div
      style={{
        position: 'absolute',
        left: 228,
        bottom: 141,
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        padding: '18px 30px 18px 22px',
        borderRadius: 12,
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.1), 0 8px 24px rgba(0, 0, 0, 0.12)',
        color: COLORS.text,
        fontFamily: FONT,
        fontSize: 44,
        fontWeight: 500,
        lineHeight: 1.2,
        ...style,
      }}
    >
      <div
        style={{
          width: 5,
          alignSelf: 'stretch',
          borderRadius: 3,
          backgroundColor: COLORS.accent,
        }}
      />
      {children}
    </Interactive.Div>
  );
};

const captionSchema = {
  children: {type: 'text-content', default: '', description: 'Text'},
} as const satisfies InteractivitySchema;

export const Caption = Interactive.withSchema({
  Component: CaptionInner,
  componentName: '<Caption>',
  schema: captionSchema,
  wrapInSequence: true,
});
