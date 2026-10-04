import { search, unwrap } from "@/lib/api";
import type { SearchHit, SearchResponse } from "@/lib/api/types";

/**
 * `GET /search?q=` puts the query in a URL, so only short, entity-like
 * queries may go there (a disease, gene, symptom, group or mechanism name).
 * Free-text sentences can contain health details and belong in a POST to
 * Dr. Wu instead (docs/compliance.md: no health data in URLs).
 */
export const SEARCH_MAX_CHARS = 60;
export const SEARCH_MAX_WORDS = 6;

export function isEntityQuery(q: string): boolean {
  const t = q.trim();
  if (t.length < 2 || t.length > SEARCH_MAX_CHARS) return false;
  if (t.split(/\s+/).length > SEARCH_MAX_WORDS) return false;
  // Sentence punctuation or first-person phrasing reads like a story, not a name.
  if (/[.!?;]\s|[.!?]$/.test(t)) return false;
  if (/\b(my|our|i|i'm|im|we|he|she|daughter|son|child|baby|diagnosed|years? old)\b/i.test(t)) {
    return false;
  }
  return true;
}

/** Typeahead against the API. Throws `ApiError` (quietly, no global toast). */
export async function searchEntities(q: string, signal?: AbortSignal): Promise<SearchHit[]> {
  if (!isEntityQuery(q)) return [];
  const res: SearchResponse | SearchHit[] = await unwrap(search({ query: { q: q.trim() }, signal, meta: { quiet: true } }));
  return Array.isArray(res) ? res : (res?.results ?? []);
}
