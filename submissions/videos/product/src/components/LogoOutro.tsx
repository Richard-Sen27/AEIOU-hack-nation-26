import type React from 'react';
import {
  AbsoluteFill,
  CanvasImage,
  Easing,
  Interactive,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from 'remotion';
import {OUTRO} from '../content';
import {COLORS, FONT} from '../theme';

type LogoOutroProps = {
  readonly style?: React.CSSProperties;
};

// Closing card: logo, name and line. Frame 0 is the start of the outro.
const LogoOutroInner: React.FC<LogoOutroProps> = ({style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        fontFamily: FONT,
        justifyContent: 'center',
        alignItems: 'center',
        ...style,
      }}
    >
      <CanvasImage
        name="Logo"
        src={staticFile(OUTRO.logo)}
        width={300}
        height={300}
        fit="contain"
        premountFor={fps}
        style={{
          opacity: interpolate(frame, [0, 12], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
          scale: interpolate(frame, [0, 24], [0.94, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            output: 'perceptual-scale',
          }),
        }}
      />
      <Interactive.Div
        name="Name"
        style={{
          color: COLORS.text,
          fontSize: 120,
          fontWeight: 700,
          lineHeight: 1,
          marginTop: 36,
          opacity: interpolate(frame, [6, 18], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
        }}
      >
        {OUTRO.name}
      </Interactive.Div>
      <Interactive.Div
        name="Tagline"
        style={{
          color: COLORS.muted,
          fontSize: 52,
          fontWeight: 500,
          marginTop: 28,
          opacity: interpolate(frame, [12, 24], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
        }}
      >
        {OUTRO.tagline}
      </Interactive.Div>
    </AbsoluteFill>
  );
};

const logoOutroSchema = {} as const satisfies InteractivitySchema;

export const LogoOutro = Interactive.withSchema({
  Component: LogoOutroInner,
  componentName: '<LogoOutro>',
  schema: logoOutroSchema,
  wrapInSequence: true,
});
