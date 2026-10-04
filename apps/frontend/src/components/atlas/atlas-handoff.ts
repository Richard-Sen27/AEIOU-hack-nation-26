/**
 * In-memory handoff from a Dr. Wu answer on `/chat` to the Atlas.
 *
 * Ids derived from a conversation about someone's health must not reach a
 * URL or browser storage (docs/compliance.md). The chat sets the finds here
 * and navigates client-side to plain `/atlas`; the Atlas takes them once on
 * mount. A full page load (or a new tab) starts empty, which is intended.
 */
import type { WuFound } from "./atlas-props";

let pending: WuFound | null = null;

/** Hand Dr. Wu's finds to the next Atlas mount (replaces any earlier handoff). */
export function setAtlasHandoff(found: WuFound): void {
  pending = { nodeIds: [...found.nodeIds], edgeIds: [...found.edgeIds], names: found.names ? { ...found.names } : undefined };
}

/** Take the pending finds once; returns null when there are none. */
export function takeAtlasHandoff(): WuFound | null {
  const out = pending;
  pending = null;
  return out;
}

/**
 * Click handler for a plain `/atlas` link: hands the finds over only for a
 * same-tab click (a modified click opens a new tab, which starts empty, so
 * nothing is left behind for a later visit).
 */
export function atlasHandoffClick(found: WuFound) {
  return (e: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    setAtlasHandoff(found);
  };
}
