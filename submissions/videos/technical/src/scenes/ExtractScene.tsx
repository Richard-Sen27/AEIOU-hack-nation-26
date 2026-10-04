import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {ABSTRACT, EXTRACTION, SCENES} from '../content';
import {COLORS, MONO, RADIUS, SAFE, SHADOW} from '../theme';

const scene = SCENES.extract;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "reads PubMed abstracts" 6-62,
// "quotes the sentence behind each relation" 62-160, "checks each quote word
// for word" 166-232, "drops what the model only guessed" 238-307.
const T = {
  abstractIn: 6,
  highlight: [60, 120],
  modelIn: 70,
  relationIn: 110,
  check: 175,
  verified: 200,
  dropStart: 238,
};

const LEFT = {left: SAFE.left, top: 160, width: 850};
const RIGHT = {left: 1080, width: 1920 - 1080 - SAFE.right};

export const ExtractScene: React.FC = () => {
  const frame = useCurrentFrame();
  const highlight = interpolate(frame, T.highlight, [0, 100], {...clamp, easing: Easing.inOut(Easing.quad)});
  const checkOn = interpolate(frame, [T.check, T.check + 10], [0, 1], clamp);

  return (
    <SceneFrame scene={scene} codePath="pipeline/extract · quote_in_text">
      {/* The source: a real abstract, with the sentence the model quoted. */}
      <div
        style={{
          position: 'absolute',
          left: LEFT.left,
          top: LEFT.top,
          width: LEFT.width,
          padding: '40px 44px',
          boxSizing: 'border-box',
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.border}`,
          boxShadow: SHADOW,
          opacity: interpolate(frame, [T.abstractIn, T.abstractIn + 12], [0, 1], clamp),
          translate: interpolate(frame, [T.abstractIn, T.abstractIn + 20], ['0px 30px', '0px 0px'], {
            ...clamp,
            easing: ease,
          }),
        }}
      >
        <div style={{fontFamily: MONO, fontSize: 26, color: COLORS.mutedForeground}}>
          {ABSTRACT.id} · {ABSTRACT.journal}
        </div>
        <div style={{fontSize: 34, fontWeight: 700, lineHeight: 1.25, marginTop: 18}}>
          {ABSTRACT.title}
        </div>
        <div style={{fontSize: 30, lineHeight: 1.5, marginTop: 26, color: COLORS.foreground}}>
          <span
            style={{
              backgroundImage: `linear-gradient(90deg, color-mix(in oklch, ${COLORS.primary} 45%, transparent) ${highlight}%, transparent ${highlight}%)`,
              boxDecorationBreak: 'clone',
              WebkitBoxDecorationBreak: 'clone',
              borderRadius: 4,
              padding: '2px 0',
            }}
          >
            {ABSTRACT.quote}
          </span>{' '}
          <span style={{color: COLORS.mutedForeground}}>{ABSTRACT.rest}</span>
        </div>
      </div>

      {/* The model call. */}
      <div
        style={{
          position: 'absolute',
          left: RIGHT.left,
          top: 160,
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '14px 24px',
          borderRadius: 999,
          backgroundColor: COLORS.foreground,
          color: COLORS.card,
          fontSize: 28,
          fontWeight: 600,
          opacity: interpolate(frame, [T.modelIn, T.modelIn + 10], [0, 1], clamp),
        }}
      >
        OpenAI
        <span style={{fontFamily: MONO, fontWeight: 400, fontSize: 24, opacity: 0.75}}>
          structured output
        </span>
      </div>

      {/* The extracted relation, then the check against the source text. */}
      <div
        style={{
          position: 'absolute',
          left: RIGHT.left,
          top: 260,
          width: RIGHT.width,
          padding: '30px 32px',
          boxSizing: 'border-box',
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `2px solid color-mix(in oklch, ${COLORS.secondary} ${Math.round(checkOn * 100)}%, ${COLORS.border})`,
          boxShadow: SHADOW,
          opacity: interpolate(frame, [T.relationIn, T.relationIn + 12], [0, 1], clamp),
          translate: interpolate(frame, [T.relationIn, T.relationIn + 22], ['-40px 0px', '0px 0px'], {
            ...clamp,
            easing: ease,
          }),
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap'}}>
          <NodeChip color={COLORS.nodeDisease} label={EXTRACTION.subject} />
          <span style={{fontFamily: MONO, fontSize: 26, color: COLORS.edgeDna}}>
            {EXTRACTION.relation} →
          </span>
          <NodeChip color={COLORS.nodeGene} label={EXTRACTION.object} />
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 26,
            lineHeight: 1.4,
            color: COLORS.mutedForeground,
            fontStyle: 'italic',
          }}
        >
          “Heterozygous loss-of-function SCN1A mutations cause Dravet syndrome, …”
        </div>
        <div style={{display: 'flex', gap: 14, marginTop: 24, alignItems: 'center'}}>
          <div
            style={{
              fontFamily: MONO,
              fontSize: 26,
              padding: '8px 16px',
              borderRadius: 999,
              color: checkOn > 0.5 ? COLORS.secondaryForeground : COLORS.mutedForeground,
              backgroundColor: `color-mix(in oklch, ${COLORS.secondary} ${Math.round(checkOn * 100)}%, ${COLORS.muted})`,
            }}
          >
            quote_in_text {checkOn > 0.5 ? '✓' : '…'}
          </div>
          <div
            style={{
              fontFamily: MONO,
              fontSize: 26,
              padding: '8px 16px',
              borderRadius: 999,
              backgroundColor: COLORS.accent,
              color: COLORS.accentForeground,
              opacity: interpolate(frame, [T.verified, T.verified + 10], [0, 1], clamp),
            }}
          >
            {EXTRACTION.tier} · 0.7
          </div>
        </div>
      </div>

      {/* Counter of verbatim quotes in this data version. */}
      <div
        style={{
          position: 'absolute',
          left: RIGHT.left,
          top: 650,
          display: 'flex',
          alignItems: 'baseline',
          gap: 16,
          opacity: interpolate(frame, [T.verified, T.verified + 12], [0, 1], clamp),
        }}
      >
        <span style={{fontSize: 64, fontWeight: 700, fontVariantNumeric: 'tabular-nums'}}>
          {Math.round(
            interpolate(frame, [T.verified, T.verified + 30], [0, EXTRACTION.quotesPassed], {
              ...clamp,
              easing: ease,
            }),
          ).toLocaleString('en-US')}
        </span>
        <span style={{fontSize: 34, color: COLORS.mutedForeground}}>
          / {EXTRACTION.quotesChecked.toLocaleString('en-US')} verbatim
        </span>
      </div>

      {/* At the check, the stored quote is tied back to the source sentence. */}
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <path
          d={`M ${RIGHT.left} 470 C ${RIGHT.left - 50} 470, ${LEFT.left + LEFT.width + 50} 470, ${LEFT.left + LEFT.width - 4} 470`}
          stroke={COLORS.secondary}
          strokeWidth={4}
          fill="none"
          pathLength={1}
          strokeDasharray="1 1"
          strokeDashoffset={1 - checkOn}
        />
        <circle cx={LEFT.left + LEFT.width - 4} cy={470} r={8} fill={COLORS.secondary} opacity={checkOn} />
        <circle cx={RIGHT.left} cy={470} r={8} fill={COLORS.secondary} opacity={checkOn} />
      </svg>

      <DropBin frame={frame} />
    </SceneFrame>
  );
};

const NodeChip: React.FC<{readonly color: string; readonly label: string}> = ({color, label}) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 12,
      padding: '8px 18px',
      borderRadius: 999,
      border: `2px solid ${color}`,
      fontSize: 32,
      fontWeight: 600,
    }}
  >
    <span style={{width: 18, height: 18, borderRadius: 9, backgroundColor: color}} />
    {label}
  </span>
);

// Relations the model marked inferred fall into a bin instead of the graph.
const BIN = {top: 790, height: 170};
const PILE = [
  {x: 1450, y: 856, rot: -7},
  {x: 1545, y: 826, rot: 5},
  {x: 1500, y: 886, rot: 2},
];

const DropBin: React.FC<{readonly frame: number}> = ({frame}) => {
  const appear = interpolate(frame, [T.dropStart - 8, T.dropStart + 4], [0, 1], clamp);

  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: RIGHT.left,
          top: BIN.top,
          width: RIGHT.width,
          height: BIN.height,
          boxSizing: 'border-box',
          borderRadius: `0 0 ${RADIUS * 1.5}px ${RADIUS * 1.5}px`,
          border: `2px solid ${COLORS.border}`,
          borderTop: `4px solid ${COLORS.mutedForeground}`,
          backgroundColor: `color-mix(in srgb, ${COLORS.muted} 70%, transparent)`,
          display: 'flex',
          alignItems: 'baseline',
          gap: 18,
          padding: '40px 36px 0',
          opacity: appear,
        }}
      >
        <span
          style={{
            fontSize: 72,
            fontWeight: 700,
            color: COLORS.mutedForeground,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {Math.round(
            interpolate(frame, [T.dropStart + 10, T.dropStart + 50], [0, EXTRACTION.inferredDropped], {
              ...clamp,
              easing: ease,
            }),
          )}
        </span>
        <span style={{fontFamily: MONO, fontSize: 28, color: COLORS.mutedForeground}}>
          excluded
        </span>
      </div>
      {PILE.map((c, i) => {
        const start = T.dropStart + i * 10;
        const fall = interpolate(frame, [start, start + 22], [0, 1], {
          ...clamp,
          easing: Easing.in(Easing.quad),
        });
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: c.x,
              top: c.y,
              fontFamily: MONO,
              fontSize: 22,
              padding: '8px 12px',
              borderRadius: 10,
              border: `1.5px dashed ${COLORS.mutedForeground}`,
              backgroundColor: COLORS.card,
              color: COLORS.mutedForeground,
              whiteSpace: 'nowrap',
              opacity: interpolate(frame, [start - 4, start + 2], [0, 1], clamp),
              translate: `0px ${(1 - fall) * -110}px`,
              rotate: `${c.rot * fall}deg`,
            }}
          >
            inferred: true
          </div>
        );
      })}
    </>
  );
};
