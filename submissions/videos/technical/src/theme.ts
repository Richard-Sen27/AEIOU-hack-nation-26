import {loadFont as loadArchivo} from '@remotion/google-fonts/Archivo';
import {loadFont as loadMono} from '@remotion/google-fonts/JetBrainsMono';

// The web app's light colour scheme, copied from
// apps/frontend/src/app/globals.css: the first :root block (base tokens) and
// the second :root block (graph tokens). Values are kept as written there;
// oklch() and color-mix() render natively in Remotion's Chromium.
const base = {
  background: 'oklch(0.9270 0.0035 247.8604)',
  foreground: 'oklch(0.2676 0.0135 163.7439)',
  card: 'oklch(1.0000 0 0)',
  primary: 'oklch(0.7336 0.1688 61.9983)',
  primaryForeground: 'oklch(0.2253 0.0339 80.4838)',
  secondary: 'oklch(0.5168 0.1115 153.0001)',
  secondaryForeground: 'oklch(1.0000 0 0)',
  muted: 'oklch(0.9533 0.0025 165.0741)',
  mutedForeground: 'oklch(0.5205 0.0163 155.2593)',
  accent: 'oklch(0.9574 0.0150 151.7697)',
  accentForeground: 'oklch(0.5168 0.1115 153.0001)',
  destructive: 'oklch(0.5320 0.1657 24.7626)',
  border: 'oklch(0.8585 0.0060 239.8331)',
  ring: 'oklch(0.4855 0.1232 52.9958)',
  chart1: 'oklch(0.7336 0.1688 61.9983)',
  chart2: 'oklch(0.5168 0.1115 153.0001)',
  chart3: 'oklch(0.5159 0.0517 251.7732)',
  chart4: 'oklch(0.5879 0.0893 319.6071)',
  chart5: 'oklch(0.5726 0.1295 41.2494)',
} as const;

const mix = (a: string, pct: number, b: string) =>
  `color-mix(in oklch, ${a} ${pct}%, ${b})`;

export const COLORS = {
  ...base,
  // Edge families.
  edgeDna: base.chart2,
  edgeSymptoms: base.chart5,
  edgeResearch: base.chart3,
  edgeCommunity: base.chart4,
  // Node types, same formulas as the app.
  nodeDisease: base.chart1,
  nodeGene: base.chart2,
  nodeVariant: mix(base.chart2, 60, base.foreground),
  nodeMechanism: mix(base.chart2, 55, base.chart3),
  nodePathway: mix(base.chart2, 45, base.chart1),
  nodePhenotype: base.chart5,
  nodePaper: base.chart3,
  nodeClaim: mix(base.chart3, 65, base.foreground),
  nodeResearcher: mix(base.chart3, 60, base.chart4),
  nodeTrial: mix(base.chart4, 50, base.chart5),
  nodePatientOrg: mix(base.chart5, 55, base.chart4),
  nodeCluster: base.mutedForeground,
  // Trust layer.
  confidenceHigh: base.chart2,
  confidenceMedium: base.chart1,
  confidenceLow: base.destructive,
  graphHighlight: base.primary,
  graphDim: mix(base.mutedForeground, 35, 'transparent'),
  gridLine: mix(base.foreground, 6, 'transparent'),
} as const;

// --radius: 0.75rem.
export const RADIUS = 12;

const {fontFamily: archivo} = loadArchivo('normal', {
  weights: ['400', '500', '600', '700'],
  subsets: ['latin'],
});
const {fontFamily: jetbrains} = loadMono('normal', {
  weights: ['400', '500', '700'],
  subsets: ['latin'],
});

export const FONT = `${archivo}, ui-sans-serif, system-ui, sans-serif`;
export const MONO = `${jetbrains}, ui-monospace, monospace`;

// Safe area of the 1920x1080 canvas: 80px per 1080px of width on the sides
// (142px) and at least 100px at top and bottom (video-layout.md).
export const SAFE = {left: 142, right: 142, top: 100, bottom: 100} as const;

// Card shadow: --shadow-md.
export const SHADOW =
  '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 2px 4px -1px hsl(0 0% 0% / 0.10)';
