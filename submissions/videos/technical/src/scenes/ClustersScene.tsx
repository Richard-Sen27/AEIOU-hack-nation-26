import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {COUNTEREXAMPLE, SCENES} from '../content';
import {COLORS, FONT, MONO} from '../theme';

const scene = SCENES.clusters;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "a negative layer" 6-60,
// "one gene acts in opposite ways" 60-140, "pushed apart" 145-199,
// "the build fails if they still meet" 206-262.
const T = {
  geneIn: 8,
  diseasesIn: 22,
  negativeIn: 40,
  mechanismIn: 80,
  apart: [145, 190] as const,
  clustersIn: 165,
  checkIn: 212,
};

const GENE = {x: 960, y: 270, r: 72};
const START = {lof: 760, gof: 1160};
const END = {lof: 540, gof: 1380};
const Y = 650;
const HULL_R = 235;

// Deterministic member dots for a cluster hull.
// Dots under the disease's own labels are left out.
const members = (seed: number, n: number) =>
  Array.from({length: n}, (_, i) => {
    const a = (i * 2.399 + seed) % (Math.PI * 2);
    const r = 70 + ((Math.sin(i * 12.9898 + seed) * 43758.5453) % 1 + 1) % 1 * 140;
    return {dx: Math.cos(a) * r, dy: Math.sin(a) * r};
  }).filter((d) => !(d.dy > 30 && d.dy < 170 && Math.abs(d.dx) < 190));

const LOF_MEMBERS = members(1.3, 26);
const GOF_MEMBERS = members(4.1, 18);

export const ClustersScene: React.FC = () => {
  const frame = useCurrentFrame();
  const apart = interpolate(frame, T.apart, [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const lofX = START.lof + (END.lof - START.lof) * apart;
  const gofX = START.gof + (END.gof - START.gof) * apart;
  const diseasesOn = interpolate(frame, [T.diseasesIn, T.diseasesIn + 14], [0, 1], clamp);
  const negOn = interpolate(frame, [T.negativeIn, T.negativeIn + 20], [0, 1], clamp);
  const hulls = interpolate(frame, [T.clustersIn, T.clustersIn + 25], [0, 1], {...clamp, easing: ease});
  const mech = interpolate(frame, [T.mechanismIn, T.mechanismIn + 14], [0, 1], clamp);

  return (
    <SceneFrame scene={scene} codePath="pipeline/analytics.py · cluster_diseases">
      <div
        style={{
          position: 'absolute',
          right: 142,
          top: 100,
          fontFamily: MONO,
          fontSize: 26,
          color: COLORS.mutedForeground,
          opacity: negOn,
        }}
      >
        Leiden · layer_weights [1, −1]
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0, fontFamily: FONT}}>
        {/* Cluster hulls form as the two diseases separate. */}
        {[
          {x: END.lof, id: COUNTEREXAMPLE.lof.cluster, dots: LOF_MEMBERS},
          {x: END.gof, id: COUNTEREXAMPLE.gof.cluster, dots: GOF_MEMBERS},
        ].map((h) => (
          <g key={h.id} opacity={hulls}>
            <circle
              cx={h.x}
              cy={Y}
              r={HULL_R * (0.85 + 0.15 * hulls)}
              fill={`color-mix(in oklch, ${COLORS.nodeCluster} 8%, transparent)`}
              stroke={COLORS.nodeCluster}
              strokeOpacity={0.5}
              strokeWidth={2}
            />
            {h.dots.map((d, i) => (
              <circle
                key={i}
                cx={h.x + d.dx}
                cy={Y + d.dy}
                r={7}
                fill={COLORS.nodeDisease}
                opacity={0.3}
              />
            ))}
            <text
              x={h.x}
              y={Y - HULL_R - 16}
              textAnchor="middle"
              fontFamily={MONO}
              fontSize={30}
              fontWeight={700}
              fill={COLORS.mutedForeground}
            >
              {h.id}
            </text>
          </g>
        ))}

        {/* Cited gene links. */}
        {[lofX, gofX].map((x, i) => (
          <line
            key={i}
            x1={GENE.x}
            y1={GENE.y}
            x2={x}
            y2={Y}
            stroke={COLORS.edgeDna}
            strokeWidth={4}
            opacity={diseasesOn}
          />
        ))}

        {/* The negative link: same gene, different mechanism. */}
        <line
          x1={lofX + 40}
          y1={Y}
          x2={gofX - 40}
          y2={Y}
          stroke={COLORS.destructive}
          strokeWidth={4}
          strokeDasharray="16 11"
          opacity={negOn}
        />
        <g opacity={negOn}>
          <circle cx={(lofX + gofX) / 2} cy={Y} r={22} fill={COLORS.card} stroke={COLORS.destructive} strokeWidth={3} />
          <text
            x={(lofX + gofX) / 2}
            y={Y + 11}
            textAnchor="middle"
            fontSize={34}
            fontWeight={700}
            fill={COLORS.destructive}
          >
            −
          </text>
        </g>
        <text
          x={(lofX + gofX) / 2}
          y={Y - 40}
          textAnchor="middle"
          fontFamily={MONO}
          fontSize={26}
          fill={COLORS.destructive}
          opacity={hulls}
        >
          {COUNTEREXAMPLE.relation}
        </text>

        {/* The gene. */}
        <g
          opacity={interpolate(frame, [T.geneIn, T.geneIn + 10], [0, 1], clamp)}
          transform={`translate(${GENE.x} ${GENE.y}) scale(${interpolate(frame, [T.geneIn, T.geneIn + 18], [0.6, 1], {...clamp, easing: ease})})`}
        >
          <circle r={GENE.r} fill={COLORS.nodeGene} />
          <text y={11} textAnchor="middle" fontSize={32} fontWeight={700} fill={COLORS.card}>
            {COUNTEREXAMPLE.gene}
          </text>
        </g>

        {/* The two diseases. */}
        {[
          {x: lofX, d: COUNTEREXAMPLE.lof, arrow: '↓', lines: [COUNTEREXAMPLE.lof.label]},
          {x: gofX, d: COUNTEREXAMPLE.gof, arrow: '↑', lines: ['migraine, familial', 'hemiplegic, 3']},
        ].map(({x, d, arrow, lines}) => (
          <g key={d.label} opacity={diseasesOn}>
            <circle cx={x} cy={Y} r={36} fill={COLORS.nodeDisease} stroke={COLORS.card} strokeWidth={5} />
            {lines.map((line, i) => (
              <text
                key={line}
                x={x}
                y={Y + 88 + i * 42}
                textAnchor="middle"
                fontSize={36}
                fontWeight={600}
                fill={COLORS.foreground}
              >
                {line}
              </text>
            ))}
            <text
              x={x}
              y={Y + 134 + (lines.length - 1) * 42}
              textAnchor="middle"
              fontFamily={MONO}
              fontSize={28}
              fill={COLORS.edgeDna}
              opacity={mech}
            >
              {arrow} {d.mechanism}
            </text>
          </g>
        ))}
      </svg>

      {/* The validation check that guards this case. */}
      <div
        style={{
          position: 'absolute',
          left: 960,
          top: 905,
          translate: '-50% 0',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '12px 26px',
          borderRadius: 999,
          backgroundColor: COLORS.secondary,
          color: COLORS.secondaryForeground,
          fontFamily: MONO,
          fontSize: 28,
          opacity: interpolate(frame, [T.checkIn, T.checkIn + 10], [0, 1], clamp),
          scale: interpolate(frame, [T.checkIn, T.checkIn + 16], [0.9, 1], {
            ...clamp,
            easing: ease,
            output: 'perceptual-scale',
          }),
        }}
      >
        check_counterexamples ✓
      </div>
    </SceneFrame>
  );
};
