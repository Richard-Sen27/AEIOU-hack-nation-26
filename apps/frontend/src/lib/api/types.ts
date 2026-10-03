/**
 * Convenience names for the shapes the foundation itself uses, taken from
 * the generated schemas (regenerate with `pnpm gen:api`).
 */
import type {
  ConsentType as GenConsentType,
  SearchResponse as GenSearchResponse,
  SearchResult,
  SessionInfo as GenSessionInfo,
  SessionUser as GenSessionUser,
} from "./generated/types.gen";

export type ConsentType = GenConsentType;
export type SessionUser = GenSessionUser;
export type SessionInfo = GenSessionInfo;
export type SearchHit = SearchResult;
export type SearchResponse = GenSearchResponse;

export function hasConsent(user: SessionUser | null | undefined, type: ConsentType) {
  return !!user?.consents?.includes(type);
}
