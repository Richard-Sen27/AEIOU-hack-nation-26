import type React from 'react';
import {
  AbsoluteFill,
  CanvasImage,
  Easing,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {ORIGINS, OUTRO, SCENES} from '../content';
import {COLORS, FONT, MONO, RADIUS, SAFE, SHADOW} from '../theme';

const scene = SCENES.atlas;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "laid out on the server" 6-90,
// "drawn in WebGL" 90-171, "solid ... cited; dashed ... computed" 178-226.
const T = {
  mapIn: 6,
  serverIn: 30,
  wireIn: 66,
  clientIn: 100,
  detailIn: 172,
  legendIn: 176,
  outroIn: 224,
};

// Screenshot frame: the crop is 1800x1248.
const MAP = {left: SAFE.left, top: 150, height: 790};
const MAP_W = Math.round((MAP.height * 1800) / 1248);
const COL = {left: 1360, width: 1778 - 1360};

export const AtlasScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const detail = interpolate(frame, [T.detailIn, T.detailIn + 12], [0, 1], clamp);

  return (
    <SceneFrame scene={scene} codePath="atlas_tree.py → GET /atlas/tree.json → sigma.js">
      {/* Screenshots of the running app (signed-out guest, light scheme). */}
      <div
        style={{
          position: 'absolute',
          left: MAP.left,
          top: MAP.top,
          width: MAP_W,
          height: MAP.height,
          borderRadius: RADIUS * 1.5,
          overflow: 'hidden',
          border: `1px solid ${COLORS.border}`,
          boxShadow: '0 1px 3px hsl(0 0% 0% / 0.10), 0 24px 60px hsl(0 0% 0% / 0.12)',
          backgroundColor: COLORS.background,
          opacity: interpolate(frame, [T.mapIn, T.mapIn + 12], [0, 1], clamp),
        }}
      >
        <CanvasImage
          name="Atlas overview"
          src={staticFile(OUTRO.atlas)}
          width={MAP_W}
          height={MAP.height}
          fit="cover"
          premountFor={fps}
          style={{
            position: 'absolute',
            inset: 0,
            scale: interpolate(frame, [0, T.detailIn + 12], [1, 1.06], clamp),
          }}
        />
        <CanvasImage
          name="Atlas detail"
          src={staticFile(OUTRO.detail)}
          width={MAP_W}
          height={MAP.height}
          fit="cover"
          premountFor={fps}
          style={{
            position: 'absolute',
            inset: 0,
            opacity: detail,
            scale: interpolate(frame, [T.detailIn, T.outroIn], [1, 1.04], clamp),
          }}
        />
      </div>

      {/* How the map reaches the browser. */}
      <ChainBox top={160} on={T.serverIn} frame={frame} title="atlas_tree.py" sub="FastAPI · radial tree" />
      <Wire top={320} on={T.wireIn} frame={frame} label="≈770 KB · gzip" />
      <ChainBox top={430} on={T.clientIn} frame={frame} title="sigma.js" sub="Next.js · graphology" />

      {/* Line styles by origin. */}
      <div
        style={{
          position: 'absolute',
          left: COL.left,
          top: 640,
          width: COL.width,
          padding: '24px 28px',
          boxSizing: 'border-box',
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.border}`,
          boxShadow: SHADOW,
          opacity: interpolate(frame, [T.legendIn, T.legendIn + 10], [0, 1], clamp),
        }}
      >
        {ORIGINS.map((o, i) => (
          <div
            key={o.origin}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 20,
              marginTop: i === 0 ? 0 : 22,
              opacity: interpolate(frame, [T.legendIn + i * 8, T.legendIn + 8 + i * 8], [0, 1], clamp),
            }}
          >
            <svg width={110} height={20}>
              <line
                x1={4}
                y1={10}
                x2={106}
                y2={10}
                stroke={COLORS.edgeDna}
                strokeWidth={6}
                strokeLinecap="round"
                strokeDasharray={o.dash === 'none' ? undefined : o.dash}
              />
            </svg>
            <span style={{fontFamily: MONO, fontSize: 28}}>{o.origin}</span>
          </div>
        ))}
      </div>

      <Outro frame={frame} />
    </SceneFrame>
  );
};

const ChainBox: React.FC<{
  readonly top: number;
  readonly on: number;
  readonly frame: number;
  readonly title: string;
  readonly sub: string;
}> = ({top, on, frame, title, sub}) => (
  <div
    style={{
      position: 'absolute',
      left: COL.left,
      top,
      width: COL.width,
      padding: '24px 28px',
      boxSizing: 'border-box',
      borderRadius: RADIUS * 1.5,
      backgroundColor: COLORS.card,
      border: `1px solid ${COLORS.border}`,
      boxShadow: SHADOW,
      opacity: interpolate(frame, [on, on + 10], [0, 1], clamp),
      translate: interpolate(frame, [on, on + 18], ['30px 0px', '0px 0px'], {...clamp, easing: ease}),
    }}
  >
    <div style={{fontFamily: MONO, fontSize: 34, fontWeight: 700}}>{title}</div>
    <div style={{fontSize: 26, color: COLORS.mutedForeground, marginTop: 8}}>{sub}</div>
  </div>
);

const Wire: React.FC<{
  readonly top: number;
  readonly on: number;
  readonly frame: number;
  readonly label: string;
}> = ({top, on, frame, label}) => {
  const p = interpolate(frame, [on, on + 16], [0, 1], {...clamp, easing: ease});
  return (
    <div style={{position: 'absolute', left: COL.left + 40, top, height: 96, opacity: p}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: 4,
          height: 96 * p,
          backgroundColor: COLORS.primary,
          borderRadius: 2,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 28,
          top: 30,
          whiteSpace: 'nowrap',
          fontFamily: MONO,
          fontSize: 26,
          color: COLORS.ring,
        }}
      >
        {label}
      </div>
    </div>
  );
};

const Outro: React.FC<{readonly frame: number}> = ({frame}) => {
  const {fps} = useVideoConfig();
  const p = interpolate(frame, [T.outroIn, T.outroIn + 10], [0, 1], clamp);
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: FONT,
        opacity: p,
      }}
    >
      <CanvasImage
        name="Logo"
        src={staticFile(OUTRO.logo)}
        width={260}
        height={260}
        fit="contain"
        premountFor={fps}
        style={{
          scale: interpolate(frame, [T.outroIn, T.outroIn + 24], [0.92, 1], {
            ...clamp,
            easing: ease,
            output: 'perceptual-scale',
          }),
        }}
      />
      <div style={{fontSize: 120, fontWeight: 700, lineHeight: 1, marginTop: 30, color: COLORS.foreground}}>
        {OUTRO.name}
      </div>
      <div style={{fontFamily: MONO, fontSize: 30, marginTop: 30, color: COLORS.mutedForeground}}>
        {OUTRO.footer}
      </div>
    </AbsoluteFill>
  );
};
