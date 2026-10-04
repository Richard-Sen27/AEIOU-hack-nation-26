import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {
  COMPUTED_LINK,
  DRAVET_SCN1A_ROWS,
  SCENES,
  TIER_WEIGHT,
  type Tier,
} from '../content';
import {COLORS, MONO, RADIUS, SAFE, SHADOW} from '../theme';

const scene = SCENES.confidence;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "arithmetic, not opinion" 6-86,
// "independent sources push it up" 93-144, "contradictions pull it down"
// 151-205, "a computed link is capped just below the top band" 209-307.
const T = {
  formulaIn: 6,
  rowsStart: 90,
  rowsEnd: 146,
  contraIn: 152,
  contraOut: 205,
  linkStart: 212,
  linkStop: 250,
  capLabel: 246,
};

const TIER_COLOR: Record<Tier, string> = {
  curated_db: COLORS.chart2,
  peer_reviewed: COLORS.chart3,
  review: `color-mix(in oklch, ${COLORS.chart3} 55%, ${COLORS.card})`,
};

// Same formula as compute_confidence in schemas/enums.py.
const confidence = (weights: readonly number[], contradictions: number) => {
  const remaining = weights.reduce((p, w) => p * (1 - w), 1);
  return Math.min(1, Math.max(0, 1 - remaining - 0.1 * contradictions));
};

const GRID = {left: SAFE.left, top: 400, cols: 8, tile: 72, gap: 10};
const GAUGE = {left: 960, width: 700, height: 60};

export const ConfidenceScene: React.FC = () => {
  const frame = useCurrentFrame();
  const shown = Math.floor(
    interpolate(frame, [T.rowsStart, T.rowsEnd], [0, DRAVET_SCN1A_ROWS.length], clamp),
  );
  const penalty = interpolate(frame, [T.contraIn, T.contraIn + 10, T.contraOut - 10, T.contraOut], [0, 1, 1, 0], clamp);
  const weights = DRAVET_SCN1A_ROWS.slice(0, shown).map((t) => TIER_WEIGHT[t]);
  const cited = shown === 0 ? 0 : confidence(weights, 0) - 0.1 * penalty;
  const computed = interpolate(frame, [T.linkStart, T.linkStop], [0, COMPUTED_LINK.cap], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });

  return (
    <SceneFrame scene={scene} codePath="schemas/enums.py · compute_confidence">
      {/* The formula. */}
      <div
        style={{
          position: 'absolute',
          left: SAFE.left,
          top: 150,
          padding: '26px 40px',
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.border}`,
          boxShadow: SHADOW,
          fontFamily: MONO,
          fontSize: 46,
          fontWeight: 500,
          opacity: interpolate(frame, [T.formulaIn, T.formulaIn + 12], [0, 1], clamp),
          translate: interpolate(frame, [T.formulaIn, T.formulaIn + 22], ['0px 24px', '0px 0px'], {
            ...clamp,
            easing: ease,
          }),
        }}
      >
        1 − ∏(1 − w<sub style={{fontSize: 30}}>i</sub>) −{' '}
        <span style={{color: COLORS.destructive}}>0.1 × n_contradicting</span>
      </div>

      {/* The 40 evidence rows of Dravet syndrome → SCN1A, in API order. */}
      <div
        style={{
          position: 'absolute',
          left: GRID.left,
          top: GRID.top - 64,
          fontFamily: MONO,
          fontSize: 26,
          color: COLORS.mutedForeground,
          opacity: interpolate(frame, [T.rowsStart - 10, T.rowsStart], [0, 1], clamp),
        }}
      >
        e_da7bfb96736c · evidence
      </div>
      {DRAVET_SCN1A_ROWS.map((tier, i) => {
        const col = i % GRID.cols;
        const row = Math.floor(i / GRID.cols);
        const on = i < shown;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: GRID.left + col * (GRID.tile + GRID.gap),
              top: GRID.top + row * (GRID.tile * 0.78 + GRID.gap),
              width: GRID.tile,
              height: GRID.tile * 0.78,
              borderRadius: 8,
              backgroundColor: TIER_COLOR[tier],
              color: tier === 'review' ? COLORS.foreground : COLORS.card,
              fontFamily: MONO,
              fontSize: 22,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: on ? 1 : 0,
              scale: on ? 1 : 0.6,
            }}
          >
            {TIER_WEIGHT[tier]}
          </div>
        );
      })}
      {/* An illustrative contradicting row (this edge has none). */}
      <div
        style={{
          position: 'absolute',
          left: GRID.left,
          top: GRID.top + 5 * (GRID.tile * 0.78 + GRID.gap) + 12,
          height: GRID.tile * 0.78,
          padding: '0 18px',
          borderRadius: 8,
          border: `2px solid ${COLORS.destructive}`,
          color: COLORS.destructive,
          backgroundColor: COLORS.card,
          fontFamily: MONO,
          fontSize: 24,
          display: 'flex',
          alignItems: 'center',
          opacity: penalty,
        }}
      >
        − 0.1
      </div>
      <Legend frame={frame} />

      {/* Gauges: one cited edge, one computed link. */}
      <Gauge
        top={350}
        label="Dravet syndrome → SCN1A"
        sub="observed"
        value={cited}
        dashed={false}
        ticks={[0.5, 0.8]}
        opacity={interpolate(frame, [T.rowsStart - 10, T.rowsStart], [0, 1], clamp)}
      />
      <Gauge
        top={680}
        label={COMPUTED_LINK.relation}
        sub="inferred · e_9a02d642ad28"
        value={computed}
        dashed
        ticks={[0.5]}
        opacity={interpolate(frame, [T.linkStart - 10, T.linkStart], [0, 1], clamp)}
      >
        {/* Where the score would go without the cap. */}
        <Marker
          at={COMPUTED_LINK.basis}
          label={`basis ${COMPUTED_LINK.basis.toFixed(2)}`}
          color={COLORS.mutedForeground}
          dashed
          side="right"
          opacity={interpolate(frame, [T.linkStart, T.linkStart + 10], [0, 1], clamp)}
        />
        <Marker
          at={COMPUTED_LINK.cap}
          label={`cap ${COMPUTED_LINK.cap}`}
          color={COLORS.foreground}
          dashed={false}
          side="left"
          opacity={interpolate(frame, [T.capLabel, T.capLabel + 8], [0, 1], clamp)}
        />
      </Gauge>
    </SceneFrame>
  );
};

const Legend: React.FC<{readonly frame: number}> = ({frame}) => {
  const tiers: Tier[] = ['curated_db', 'peer_reviewed', 'review'];
  const counts = tiers.map((t) => DRAVET_SCN1A_ROWS.filter((r) => r === t).length);
  return (
    <div
      style={{
        position: 'absolute',
        left: GRID.left,
        top: 860,
        display: 'flex',
        gap: 30,
        fontFamily: MONO,
        fontSize: 24,
        opacity: interpolate(frame, [T.rowsEnd - 10, T.rowsEnd + 4], [0, 1], clamp),
      }}
    >
      {tiers.map((t, i) => (
        <div key={t} style={{display: 'flex', alignItems: 'center', gap: 10}}>
          <span style={{width: 22, height: 22, borderRadius: 5, backgroundColor: TIER_COLOR[t]}} />
          {t} ×{counts[i]}
        </div>
      ))}
    </div>
  );
};

const BANDS = [
  {from: 0, to: 0.5, label: 'Low', color: COLORS.confidenceLow},
  {from: 0.5, to: 0.8, label: 'Medium', color: COLORS.confidenceMedium},
  {from: 0.8, to: 1, label: 'High', color: COLORS.confidenceHigh},
];

const levelOf = (v: number) => (v >= 0.8 ? 'High' : v >= 0.5 ? 'Medium' : 'Low');

const Gauge: React.FC<{
  readonly top: number;
  readonly label: string;
  readonly sub: string;
  readonly value: number;
  readonly dashed: boolean;
  readonly opacity: number;
  readonly ticks: readonly number[];
  readonly children?: React.ReactNode;
}> = ({top, label, sub, value, dashed, opacity, ticks, children}) => {
  const band = BANDS.find((b) => value >= b.from && value <= b.to) ?? BANDS[0];
  return (
    <div style={{position: 'absolute', left: GAUGE.left, top, width: GAUGE.width, opacity}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end'}}>
        <div>
          <div style={{fontFamily: dashed ? MONO : undefined, fontSize: dashed ? 27 : 34, fontWeight: 600}}>
            {label}
          </div>
          <div style={{fontFamily: MONO, fontSize: 24, color: COLORS.mutedForeground, marginTop: 6}}>
            {sub}
          </div>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
          <span
            style={{
              fontSize: 24,
              fontWeight: 600,
              padding: '4px 14px',
              borderRadius: 999,
              color: band.color,
              border: `1.5px solid ${band.color}`,
            }}
          >
            {levelOf(value)}
          </span>
          <span style={{fontFamily: MONO, fontSize: 44, fontWeight: 700, fontVariantNumeric: 'tabular-nums'}}>
            {value.toFixed(3)}
          </span>
        </div>
      </div>
      <div
        style={{
          position: 'relative',
          marginTop: 20,
          height: GAUGE.height,
          borderRadius: 10,
          overflow: 'visible',
        }}
      >
        {BANDS.map((b) => (
          <div
            key={b.label}
            style={{
              position: 'absolute',
              left: b.from * GAUGE.width,
              width: (b.to - b.from) * GAUGE.width,
              top: 0,
              bottom: 0,
              backgroundColor: `color-mix(in srgb, ${b.color} 16%, ${COLORS.card})`,
              borderLeft: b.from > 0 ? `2px solid color-mix(in srgb, ${b.color} 60%, ${COLORS.card})` : undefined,
            }}
          />
        ))}
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 10,
            bottom: 10,
            width: value * GAUGE.width,
            borderRadius: 6,
            backgroundColor: dashed ? `color-mix(in srgb, ${COLORS.edgeDna} 30%, ${COLORS.card})` : COLORS.edgeDna,
            border: dashed ? `3px dashed ${COLORS.edgeDna}` : undefined,
            boxSizing: 'border-box',
          }}
        />
        {children}
      </div>
      <div style={{position: 'relative', height: 30, marginTop: 8, fontFamily: MONO, fontSize: 22, color: COLORS.mutedForeground}}>
        {ticks.map((t) => (
          <span key={t} style={{position: 'absolute', left: t * GAUGE.width - 18}}>
            {t}
          </span>
        ))}
      </div>
    </div>
  );
};

// A vertical line across the gauge with its label below the bar, on the
// given side of the line.
const Marker: React.FC<{
  readonly at: number;
  readonly label: string;
  readonly color: string;
  readonly dashed: boolean;
  readonly side: 'left' | 'right';
  readonly opacity: number;
}> = ({at, label, color, dashed, side, opacity}) => (
  <div style={{position: 'absolute', left: at * GAUGE.width - 1, top: -14, bottom: -14, opacity}}>
    <div
      style={{
        position: 'absolute',
        inset: 0,
        width: 0,
        borderLeft: `3px ${dashed ? 'dashed' : 'solid'} ${color}`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        top: '100%',
        right: side === 'left' ? 10 : undefined,
        left: side === 'right' ? 12 : undefined,
        whiteSpace: 'nowrap',
        fontFamily: MONO,
        fontSize: 26,
        fontWeight: side === 'left' ? 700 : 400,
        color,
        paddingTop: 2,
      }}
    >
      {label}
    </div>
  </div>
);
