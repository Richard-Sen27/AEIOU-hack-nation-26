// Light-mode tokens of the app (apps/frontend/src/app/globals.css, first :root block).
export const COLORS = {
  background: 'oklch(0.9270 0.0035 247.8604)', // --background
  surface: 'oklch(1.0000 0 0)', // --card
  text: 'oklch(0.2676 0.0135 163.7439)', // --foreground
  muted: 'oklch(0.5205 0.0163 155.2593)', // --muted-foreground
  accent: 'oklch(0.7336 0.1688 61.9983)', // --primary
  border: 'oklch(0.8585 0.0060 239.8331)', // --border
};

// --radius is 0.75rem (12 px in the app); doubled for the 1080p canvas.
export const RADIUS = 24;

export const FONT_FALLBACK =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";
