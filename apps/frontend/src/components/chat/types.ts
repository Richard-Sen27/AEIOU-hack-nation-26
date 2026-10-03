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
  /** In-memory copy of the question, for "Try again". Never persisted. */
  request?: string;
  followUpDone?: boolean;
};

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

export function toTurnChips(chips: Chip[], previous: TurnChip[] = []): TurnChip[] {
  return chips.map((c, i) => {
    const prev = previous[i];
    if (prev && prev.id === c.id && prev.label === c.label) return { ...c, state: prev.state, saving: prev.saving };
    return { ...c, state: c.confirmed ? "confirmed" : "pending" };
  });
}

/**
 * The contract has no explicit emergency flag. An emergency reply (agent
 * spec: "call emergency services, no graph answer") is a finished reply
 * with no graph content whose summary points to emergency services.
 */
export function isEmergencyReply(turn: AssistantTurn): boolean {
  if (turn.phase === "streaming" && !turn.final) return false;
  const r = turn.reply;
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
