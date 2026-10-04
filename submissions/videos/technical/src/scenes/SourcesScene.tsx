import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {SCENES, SOURCES, STAGES, TOTALS, VOICE_DELAY} from '../content';
import {COLORS, MONO, RADIUS, SAFE, SHADOW} from '../theme';

const scene = SCENES.sources;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "thirteen public sources" ~20-80,
// "one typed graph" ~80-150, "every link keeps the records" ~155-226.
const T = {
  sourcesIn: VOICE_DELAY,
  linesIn: 40,
  stagesStart: 70,
  stageStep: 11,
  countersIn: 140,
  edgeIn: 160,
  rowsIn: 172,
};

const CHIP = {left: SAFE.left, top: 150, width: 340, height: 50, gap: 11};
const BOX = {left: 640, top: 190, width: 400, height: 96 + 7 * 78 + 24};
const STAGE_ROW = {top: BOX.top + 96, height: 78};
const RIGHT = 1200;

const chipCenterY = (i: number) => CHIP.top + i * (CHIP.height + CHIP.gap) + CHIP.height / 2;

export const SourcesScene: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <SceneFrame scene={scene} codePath="apps/pipeline · atlas-pipeline all">
      {/* Lines from every source into the pipeline. */}
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {SOURCES.map((s, i) => {
          const y0 = chipCenterY(i);
          const x0 = CHIP.left + CHIP.width;
          const x1 = BOX.left;
          const y1 = STAGE_ROW.top + STAGE_ROW.height / 2;
          const d = `M ${x0} ${y0} C ${x0 + 140} ${y0}, ${x1 - 140} ${y1}, ${x1} ${y1}`;
          const p = interpolate(frame, [T.linesIn + i * 2, T.linesIn + 30 + i * 2], [0, 1], {
            ...clamp,
            easing: ease,
          });
          return (
            <path
              key={s}
              d={d}
              fill="none"
              stroke={COLORS.mutedForeground}
              strokeOpacity={0.45}
              strokeWidth={2}
              pathLength={1}
              strokeDasharray="1 1"
              strokeDashoffset={1 - p}
            />
          );
        })}
        {/* Pipeline to outputs. */}
        <path
          d={`M ${BOX.left + BOX.width} ${BOX.top + BOX.height / 2} C ${BOX.left + BOX.width + 80} ${BOX.top + BOX.height / 2}, ${RIGHT - 90} 420, ${RIGHT - 24} 420`}
          fill="none"
          stroke={COLORS.primary}
          strokeWidth={3}
          pathLength={1}
          strokeDasharray="1 1"
          strokeDashoffset={interpolate(frame, [T.countersIn - 15, T.countersIn + 10], [1, 0], clamp)}
        />
      </svg>

      {/* The 13 public sources. */}
      {SOURCES.map((s, i) => (
        <div
          key={s}
          style={{
            position: 'absolute',
            left: CHIP.left,
            top: CHIP.top + i * (CHIP.height + CHIP.gap),
            width: CHIP.width,
            height: CHIP.height,
            borderRadius: RADIUS,
            backgroundColor: COLORS.card,
            border: `1px solid ${COLORS.border}`,
            boxShadow: SHADOW,
            display: 'flex',
            alignItems: 'center',
            paddingLeft: 20,
            fontSize: 28,
            fontWeight: 500,
            boxSizing: 'border-box',
            opacity: interpolate(frame, [T.sourcesIn + i * 2.5, T.sourcesIn + 10 + i * 2.5], [0, 1], clamp),
            translate: interpolate(
              frame,
              [T.sourcesIn + i * 2.5, T.sourcesIn + 16 + i * 2.5],
              ['-30px 0px', '0px 0px'],
              {...clamp, easing: ease},
            ),
          }}
        >
          {s}
        </div>
      ))}

      {/* The pipeline with its stages lighting up in order. */}
      <div
        style={{
          position: 'absolute',
          left: BOX.left,
          top: BOX.top,
          width: BOX.width,
          height: BOX.height,
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.border}`,
          boxShadow: SHADOW,
          opacity: interpolate(frame, [20, 40], [0, 1], clamp),
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 32,
            top: 30,
            fontFamily: MONO,
            fontSize: 30,
            fontWeight: 700,
          }}
        >
          atlas-pipeline
        </div>
        {STAGES.map((stage, i) => {
          const on = T.stagesStart + i * T.stageStep;
          const active = interpolate(frame, [on, on + 8], [0, 1], clamp);
          return (
            <div
              key={stage}
              style={{
                position: 'absolute',
                left: 24,
                right: 24,
                top: STAGE_ROW.top - BOX.top + i * STAGE_ROW.height,
                height: STAGE_ROW.height - 12,
                borderRadius: RADIUS,
                display: 'flex',
                alignItems: 'center',
                gap: 18,
                paddingLeft: 20,
                fontFamily: MONO,
                fontSize: 30,
                backgroundColor: `color-mix(in srgb, ${COLORS.primary} ${Math.round(active * 22)}%, ${COLORS.muted})`,
                color: COLORS.foreground,
              }}
            >
              <div
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 8,
                  backgroundColor: `color-mix(in srgb, ${COLORS.primary} ${Math.round(active * 100)}%, ${COLORS.border})`,
                }}
              />
              {stage}
            </div>
          );
        })}
      </div>

      {/* What comes out: totals counting up. */}
      {TOTALS.map((t, i) => {
        const start = T.countersIn + i * 6;
        const p = interpolate(frame, [start, start + 40], [0, 1], {...clamp, easing: ease});
        return (
          <div
            key={t.label}
            style={{
              position: 'absolute',
              left: RIGHT,
              top: 190 + i * 150,
              opacity: interpolate(frame, [start, start + 8], [0, 1], clamp),
            }}
          >
            <div
              style={{
                fontSize: 88,
                fontWeight: 700,
                lineHeight: 1,
                fontVariantNumeric: 'tabular-nums',
                color: i === 2 ? COLORS.ring : COLORS.foreground,
              }}
            >
              {Math.round(t.value * p).toLocaleString('en-US')}
            </div>
            <div style={{fontSize: 34, color: COLORS.mutedForeground, marginTop: 8}}>
              {t.label}
            </div>
          </div>
        );
      })}

      {/* One edge with its evidence rows stacking underneath. */}
      <EdgeWithRows frame={frame} />
    </SceneFrame>
  );
};

const EdgeWithRows: React.FC<{readonly frame: number}> = ({frame}) => {
  const top = 690;
  const a = {x: RIGHT + 30, y: top + 40};
  const b = {x: RIGHT + 470, y: top + 40};
  const appear = interpolate(frame, [T.edgeIn, T.edgeIn + 12], [0, 1], clamp);
  const rows = [0, 1, 2, 3];

  return (
    <svg
      width={1920}
      height={1080}
      style={{position: 'absolute', inset: 0, opacity: appear}}
    >
      <line
        x1={a.x}
        y1={a.y}
        x2={b.x}
        y2={b.y}
        stroke={COLORS.edgeDna}
        strokeWidth={5}
      />
      <line
        x1={(a.x + b.x) / 2}
        y1={a.y + 4}
        x2={(a.x + b.x) / 2}
        y2={a.y + 46}
        stroke={COLORS.mutedForeground}
        strokeWidth={2}
        strokeDasharray="4 5"
        opacity={interpolate(frame, [T.rowsIn, T.rowsIn + 8], [0, 1], clamp)}
      />
      <circle cx={a.x} cy={a.y} r={24} fill={COLORS.nodeDisease} />
      <circle cx={b.x} cy={b.y} r={24} fill={COLORS.nodeGene} />
      {rows.map((r) => {
        const start = T.rowsIn + r * 9;
        const p = interpolate(frame, [start, start + 12], [0, 1], {...clamp, easing: ease});
        const y = a.y + 46 + r * 44;
        return (
          <g key={r} opacity={p} transform={`translate(0 ${(1 - p) * -24})`}>
            <rect
              x={a.x + 70}
              y={y}
              width={b.x - a.x - 140}
              height={32}
              rx={8}
              fill={COLORS.card}
              stroke={COLORS.border}
            />
            <rect x={a.x + 82} y={y + 10} width={60 + r * 30} height={12} rx={6} fill={COLORS.muted} />
            <rect
              x={b.x - 160}
              y={y + 8}
              width={78}
              height={16}
              rx={8}
              fill={r < 2 ? COLORS.secondary : COLORS.chart3}
              opacity={0.75}
            />
          </g>
        );
      })}
    </svg>
  );
};
