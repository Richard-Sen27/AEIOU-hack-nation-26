import type { Schemas } from "@/lib/api";

export type { Schemas };

export type AgentReply = Schemas.AgentReply;
export type Chip = Schemas.Chip;
export type Claim = Schemas.Claim;
export type Card = Schemas.Card;
export type Action = Schemas.Action;
export type FollowUp = Schemas.FollowUp;
export type ChatEvent = Schemas.ChatEvent;
export type ChatSession = Schemas.ChatSession;
export type ChatMessage = Schemas.ChatMessage;
export type PatientProfile = Schemas.PatientProfile;
export type EdgeEvidence = Schemas.EdgeEvidence;
export type NodeDetail = Schemas.NodeDetail;

export type ChipState = "pending" | "confirmed" | "removed";

/** A chip plus what the user decided about it. */
export type TurnChip = Chip & { state: ChipState; saving?: boolean };

export type StatusLine = { tool?: string | null; message: string };

export type TurnErrorCode =
  | "rate_limited"
  | "reauth_required"
  | "sign_in_required"
  | "timeout"
  | "network_error"
  | "interrupted"
  | "not_implemented"
  | (string & {});

export type TurnError = { code: TurnErrorCode; message: string };

export type TurnPhase = "streaming" | "done" | "stopped" | "error";

/** The reply as it builds up from stream events; every list starts empty. */
export type PartialReply = Omit<AgentReply, "chips"> & { chips: TurnChip[] };

export type UserTurn = { id: string; kind: "user"; text: string };

export type AssistantTurn = {
  id: string;
  kind: "assistant";
  phase: TurnPhase;
  statuses: StatusLine[];
  reply: PartialReply;
  /** True once the authoritative `final` reply arrived (or it was loaded from history). */
  final: boolean;
  error?: TurnError;
  /** The question, for "Try again": an in-memory copy, or the stored (redacted) message. */
  request?: string;
  /** The stored user message of this turn (from the `turn` event or history): a retry sends it as `retry_message_id`, so the message is not stored twice. */
  userMessageId?: string;
  followUpDone?: boolean;
  /** What the user decided about each `profile_hints` item of this reply. */
  hintState?: Partial<Record<HintKey, HintDecision>>;
  /** The "is this about a child?" offer was answered or dismissed. */
  childOfferDone?: boolean;
  /** Arrived live in this tab (sent, retried or attached to a running run): its text is revealed smoothly. A stored reply shows at once. */
  live?: boolean;
};

/** Profile hints from a reply (age, onset, country), confirmed or dismissed one by one. */
export type HintKey = "age" | "onset" | "country";
export type HintDecision = "saving" | "confirmed" | "dismissed";

export type Turn = UserTurn | AssistantTurn;

export function emptyReply(): PartialReply {
  return {
    summary: "",
    uncertainty: null,
    chips: [],
    claims: [],
    contradictions: [],
    missing_evidence: [],
    cards: [],
    graph_focus: null,
    actions: [],
    follow_up: null,
  };
}

const CHIP_NODE_TYPE: Record<Chip["type"], string> = {
  disease: "disease",
  gene: "gene",
  variant: "variant",
  symptom: "phenotype",
};

/** A name and node type for an id, as the reply itself carries it. */
export type ReplyName = { label: string; type: string };

/**
 * Names the reply already carries for its ids (resolved chips and the symptom-overlap
 * ranking), so lists of its finds need no request per id.
 */
export function replyNames(reply: Pick<PartialReply, "chips" | "symptom_match">): Record<string, ReplyName> {
  const out: Record<string, ReplyName> = {};
  for (const c of reply.chips) if (c.id && !out[c.id]) out[c.id] = { label: c.label, type: CHIP_NODE_TYPE[c.type] ?? "disease" };
  for (const i of reply.symptom_match?.items ?? []) out[i.id] = { label: i.label, type: "disease" };
  return out;
}

/** Ids of the symptom-overlap ranking, best first (empty when the reply has none). */
export function rankedIds(reply: Pick<PartialReply, "symptom_match">): string[] {
  return reply.symptom_match?.items.map((i) => i.id) ?? [];
}

export function toTurnChips(chips: Chip[], previous: TurnChip[] = []): TurnChip[] {
  return chips.map((c, i) => {
    const prev = previous[i];
    if (prev && prev.id === c.id && prev.label === c.label) return { ...c, state: prev.state, saving: prev.saving };
    return { ...c, state: c.confirmed ? "confirmed" : "pending" };
  });
}

/**
 * Emergency replies (agent spec: "call emergency services, no graph answer")
 * carry `kind: "emergency"`. Replies stored before `kind` existed have no
 * flag; for those only, fall back to the old heuristic: a finished reply with
 * no graph content whose summary points to emergency services.
 */
export function isEmergencyReply(turn: AssistantTurn): boolean {
  const r = turn.reply;
  if (r.kind === "emergency") return true;
  if (r.kind != null) return false;
  if (turn.phase === "streaming" && !turn.final) return false;
  const noGraph =
    r.chips.length === 0 &&
    r.claims.length === 0 &&
    r.cards.length === 0 &&
    r.actions.length === 0 &&
    !r.graph_focus &&
    !r.follow_up;
  return (
    noGraph &&
    /emergency (services|number|room|department)|\b(112|911|999|000)\b|ambulance|notruf|urgences|emergencias/i.test(r.summary)
  );
}
