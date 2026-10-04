import React from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {COLORS, RADIUS} from './theme';

type Props = {
  src: string;
  eyebrow: string;
  caption: string;
  durationInFrames: number;
  /** 1 = zoom in, -1 = zoom out */
  zoomDirection?: 1 | -1;
  /** CSS object-position for the cover crop, e.g. "50% 30%" */
  objectPosition?: string;
  /** For portrait images: letterbox over a blurred copy instead of cropping */
  containOnBlur?: boolean;
};

export const PhotoScene: React.FC<Props> = ({
  src,
  eyebrow,
  caption,
  durationInFrames,
  zoomDirection = 1,
  objectPosition = '50% 50%',
  containOnBlur = false,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const progress = frame / durationInFrames;
  const scale =
    zoomDirection === 1
      ? interpolate(progress, [0, 1], [1.02, 1.14])
      : interpolate(progress, [0, 1], [1.14, 1.02]);
  const drift = interpolate(progress, [0, 1], [0, zoomDirection * -18]);

  const captionIn = spring({frame: frame - 8, fps, config: {damping: 200}});
  const captionY = interpolate(captionIn, [0, 1], [40, 0]);

  const imageStyle: React.CSSProperties = {
    width: '100%',
    height: '100%',
    transform: `scale(${scale}) translateX(${drift}px)`,
  };

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.background, overflow: 'hidden'}}>
      {containOnBlur ? (
        <>
          <Img
            src={src}
            style={{
              ...imageStyle,
              objectFit: 'cover',
              filter: 'blur(40px)',
            }}
          />
          <AbsoluteFill style={{backgroundColor: COLORS.background, opacity: 0.6}} />
          <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
            <Img
              src={src}
              style={{
                height: '88%',
                borderRadius: 16,
                boxShadow: '0 30px 80px rgba(0,0,0,0.18)',
                transform: `scale(${scale * 0.96})`,
              }}
            />
          </AbsoluteFill>
        </>
      ) : (
        <Img src={src} style={{...imageStyle, objectFit: 'cover', objectPosition}} />
      )}

      <AbsoluteFill
        style={{
          justifyContent: 'flex-end',
          padding: '0 90px 70px',
          opacity: captionIn,
          transform: `translateY(${captionY}px)`,
        }}
      >
        {/* light card behind the caption, so it stays legible on any photo */}
        <div
          style={{
            alignSelf: 'flex-start',
            backgroundColor: COLORS.surface,
            border: `2px solid ${COLORS.border}`,
            borderRadius: RADIUS,
            boxShadow: '0 20px 50px rgba(0,0,0,0.18)',
            padding: '28px 40px 32px',
          }}
        >
          <div
            style={{
              color: COLORS.accent,
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: 6,
              textTransform: 'uppercase',
              marginBottom: 14,
            }}
          >
            {eyebrow}
          </div>
          <div
            style={{
              color: COLORS.text,
              fontSize: 58,
              fontWeight: 800,
              lineHeight: 1.1,
              maxWidth: 1300,
            }}
          >
            {caption}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
