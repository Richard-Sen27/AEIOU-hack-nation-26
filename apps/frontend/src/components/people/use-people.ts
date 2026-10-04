"use client";

import { useEffect, useState } from "react";

import { useSession } from "@/components/providers/session-provider";
import { getPersonCard, listPeople, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

type PublicCard = Schemas.PublicCard;

export type Loaded<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; error: ApiError };

// In memory, per signed-in user; cards are public to signed-in users, nothing here is health data.
const cards = new Map<string, Promise<PublicCard | ApiError>>();
let cacheUser: string | null = null;

function cached(userId: string, cardId: string): Promise<PublicCard | ApiError> {
  if (cacheUser !== userId) {
    cards.clear();
    cacheUser = userId;
  }
  let p = cards.get(cardId);
  if (!p) {
    p = getPersonCard({ path: { card_id: cardId }, meta: { quiet: true } }).then(({ data, error }) =>
      data ? data : (error as unknown as ApiError),
    );
    cards.set(cardId, p);
    // Failures are not kept: the next view asks again.
    void p.then((r) => {
      if (!("card_id" in r)) cards.delete(cardId);
    });
  }
  return p;
}

/** Forget a card (after the owner changed it), so the next view fetches it fresh. */
export function forgetCard(cardId: string | null | undefined) {
  if (cardId) cards.delete(cardId);
}

/**
 * One public card. Only for signed-in users who confirmed the minimum age (the
 * API refuses everyone else); stays `idle` otherwise so the caller shows the gate.
 */
export function usePersonCard(cardId: string | null | undefined, { fresh = false } = {}): Loaded<PublicCard> {
  const { user } = useSession();
  const userId = user?.age_confirmed ? user.id : null;
  const [state, setState] = useState<{ key: string; value: Loaded<PublicCard> } | null>(null);
  const key = userId && cardId ? `${userId}:${cardId}` : null;

  useEffect(() => {
    if (!key || !userId || !cardId) return;
    let alive = true;
    if (fresh) forgetCard(cardId);
    void cached(userId, cardId).then((r) => {
      if (!alive) return;
      setState({ key, value: "card_id" in r ? { kind: "ready", data: r } : { kind: "error", error: r } });
    });
    return () => {
      alive = false;
    };
  }, [key, userId, cardId, fresh]);

  if (!key) return { kind: "idle" };
  return state?.key === key ? state.value : { kind: "loading" };
}

/** Verified, visible cards of doctors and researchers for one atlas disease. Professionals only. */
export function usePeopleForDisease(diseaseId: string | null): Loaded<PublicCard[]> {
  const { user } = useSession();
  const userId = user?.age_confirmed ? user.id : null;
  const [state, setState] = useState<{ key: string; value: Loaded<PublicCard[]> } | null>(null);
  const key = userId && diseaseId ? `${userId}:${diseaseId}` : null;

  useEffect(() => {
    if (!key || !diseaseId) return;
    let alive = true;
    void listPeople({ query: { disease: diseaseId }, meta: { quiet: true } }).then(({ data, error }) => {
      if (!alive) return;
      setState({ key, value: data ? { kind: "ready", data: data.items } : { kind: "error", error: error as unknown as ApiError } });
    });
    return () => {
      alive = false;
    };
  }, [key, diseaseId]);

  if (!key) return { kind: "idle" };
  return state?.key === key ? state.value : { kind: "loading" };
}
