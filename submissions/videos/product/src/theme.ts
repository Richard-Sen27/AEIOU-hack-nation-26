import {loadFont} from '@remotion/google-fonts/Archivo';

// The web app's light-mode tokens (apps/frontend/src/app/globals.css, :root),
// the same palette as the intro and technical videos.
export const COLORS = {
  background: 'oklch(0.9270 0.0035 247.8604)',
  surface: 'oklch(1 0 0)',
  text: 'oklch(0.2676 0.0135 163.7439)',
  muted: 'oklch(0.5205 0.0163 155.2593)',
  accent: 'oklch(0.7336 0.1688 61.9983)',
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
