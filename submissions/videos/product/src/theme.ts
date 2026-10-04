import {loadFont} from '@remotion/google-fonts/Archivo';

// Same palette as the team intro video (submissions/videos/intro/src/theme.ts),
// so the two submissions read as one set.
export const COLORS = {
  background: '#0c0e13',
  surface: '#161a22',
  text: '#f5f3ee',
  muted: '#9aa3b2',
  accent: '#f59e0b',
};

const FONT_FALLBACK =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

// Archivo is the web app's font, so on-screen text matches the recordings.
const {fontFamily: archivo} = loadFont('normal', {
  weights: ['400', '500', '600', '700'],
  subsets: ['latin'],
});

export const FONT = `${archivo}, ${FONT_FALLBACK}`;

// The recording frame: 16:9, centred, inside the safe area of a 1920x1080
// canvas (at least 142px from the sides and 100px from top and bottom).
export const FRAME = {
  left: 180,
  top: 101,
  width: 1560,
  height: 878,
};
