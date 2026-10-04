/**
 * Mocks for verification and the public card ("Reachable in Amber"):
 * `GET/PUT /me/professional/card`, ORCID start, the manual request, `GET /people`.
 */
import { signedInSession } from "../helpers";

export type Req = { url: string; method: string; body: unknown };

export const CARD_ID = "22222222-2222-4222-8222-222222222222";

export const LABELS = {
  orcid: "ORCID iD confirmed",
  orcid_simulated: "Demo, verification simulated (no real ORCID check)",
  institutional_email: "Identity checked by the Amber team (institutional e-mail)",
  manual_simulated: "Demo, verification simulated (no real identity check)",
} as const;
export type Method = keyof typeof LABELS;

export const verification = (method: Method) => ({
  method,
  label: LABELS[method],
  simulated: method.endsWith("_simulated"),
});

/** A public card as `GET /people/{card_id}` returns it. */
export function publicCard(extra: Record<string, unknown> = {}) {
  return {
    card_id: CARD_ID,
    role: "researcher",
    role_self_declared: true,
    name: "Maria Example",
    name_source: "orcid",
    institutions: [
      { node_id: "INST:bch", label: "Boston Children's Hospital" },
      { node_id: null, label: "St. Jude Research" },
    ],
    orcid_id: "0000-0002-1825-0097",
    orcid_url: "https://orcid.org/0000-0002-1825-0097",
    atlas_node_id: "RES:0001",
    atlas_node_label: "Maria Example",
    headline: "Synaptic epilepsies, STXBP1 natural history",
    accepts_patient_messages: true,
    verification: verification("orcid"),
    ...extra,
  };
}

/** The work details (`GET /me/professional`) of a researcher. */
export const WORK = {
  first_name: "Maria",
  last_name: "Example",
  institutions: [
    { node_id: "INST:bch", label: "Boston Children's Hospital" },
    { node_id: null, label: "St. Jude Research" },
  ],
  orcid_id: "0000-0002-1825-0097",
  atlas_node_id: null,
  linked_entry: null,
  linked_entry_missing: false,
  updated_at: "2026-10-03T09:00:00Z",
  suggested: { first_name: "Maria", last_name: "Example", source: "chatgpt" },
};

type CardState = {
  verified: boolean;
  method: Method | null;
  orcidConfirmed: boolean;
  atlasLinkVerified: boolean;
  request: null | { status: "pending" | "rejected"; institutional_email?: string; profile_url?: string; decided_at?: string };
  orcidAvailable: boolean;
  orcidSimulated: boolean;
  hasName: boolean;
  visible: boolean;
  headline: string | null;
  accepts: boolean;
  showInst: boolean;
  showAtlas: boolean;
  cardId: string | null;
};

const unverified: CardState = {
  verified: false,
  method: null,
  orcidConfirmed: false,
  atlasLinkVerified: false,
  request: null,
  orcidAvailable: true,
  orcidSimulated: false,
  hasName: true,
  visible: false,
  headline: null,
  accepts: false,
  showInst: true,
  showAtlas: true,
  cardId: null,
};

/** Mirrors `people._my_card`: blocked reason, visibility and the preview built with the card rules. */
export function myCard(s: CardState) {
  const blocked = !s.verified || !s.method ? "not_verified" : !s.hasName ? "no_name" : null;
  const cardId = s.cardId ?? CARD_ID;
  return {
    verification: {
      verified: s.verified,
      method: s.verified ? s.method : null,
      label: s.verified && s.method ? LABELS[s.method] : null,
      simulated: !!s.method?.endsWith("_simulated") && s.verified,
      verified_at: s.verified ? "2026-10-04T08:00:00Z" : null,
      orcid_id_confirmed: s.orcidConfirmed,
      atlas_link_verified: s.atlasLinkVerified,
      request: s.request ? { requested_at: "2026-10-04T07:00:00Z", decided_at: null, ...s.request } : null,
      orcid_available: s.orcidAvailable,
      orcid_simulated: s.orcidSimulated,
    },
    settings: {
      visible: s.visible && blocked === null,
      visible_since: s.visible ? "2026-10-04T08:30:00Z" : null,
      headline: s.headline,
      accepts_patient_messages: s.accepts,
      show_institutions: s.showInst,
      show_atlas_entry: s.showAtlas,
    },
    card_id: s.cardId,
    can_show: blocked === null,
    blocked_reason: blocked,
    preview:
      blocked === null
        ? publicCard({
            card_id: cardId,
            headline: s.headline,
            accepts_patient_messages: s.accepts,
            institutions: s.showInst ? WORK.institutions : [],
            orcid_id: s.orcidConfirmed ? WORK.orcid_id : null,
            orcid_url: s.orcidConfirmed ? `https://orcid.org/${WORK.orcid_id}` : null,
            atlas_node_id: s.atlasLinkVerified && s.showAtlas ? "RES:0001" : null,
            atlas_node_label: s.atlasLinkVerified && s.showAtlas ? "Maria Example" : null,
            name_source: s.method === "manual_simulated" ? "self_declared" : s.method === "institutional_email" ? "reviewed" : "orcid",
            verification: verification(s.method as Method),
          })
        : null,
  };
}

/**
 * A stateful card backend for one test. `state` is mutable, `calls` logs every
 * card-related request; `opts.autoApprove` mimics ORCID_MOCK (requests approved
 * at once as `manual_simulated`).
 */
export function cardBackend(initial: Partial<CardState> = {}, opts: { role?: string; autoApprove?: boolean } = {}) {
  const state: CardState = { ...unverified, ...initial };
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const log = (r: Req) => calls.push({ method: r.method, path: new URL(r.url).pathname, body: r.body });
  const error = (status: number, code: string, message = code) => ({ status, json: { error: { code, message } } });
  const mocks: Record<string, unknown> = {
    "GET /auth/session": () => ({ json: signedInSession({ role: opts.role ?? "researcher", role_verified: state.verified }) }),
    "GET /profile": { diseases: [], genes: [], variants: [], phenotypes: [], updated_at: null },
    "GET /consents": [],
    "GET /contributions": [],
    "GET /me/follows": { items: [], limit: 50 },
    "GET /notifications/unread-count": { count: 0 },
    "GET /me/professional": () => ({ json: { ...WORK, first_name: state.hasName ? WORK.first_name : null, last_name: state.hasName ? WORK.last_name : null } }),
    "GET /me/professional/card": (r: Req) => (log(r), { json: myCard(state) }),
    "PUT /me/professional/card": (r: Req) => {
      log(r);
      const b = r.body as { visible: boolean; headline: string | null; accepts_patient_messages: boolean; show_institutions: boolean; show_atlas_entry: boolean };
      if (b.visible && (!state.verified || !state.method)) return error(409, "conflict", "Confirm your identity first.");
      if (b.visible && !state.hasName) return error(409, "conflict", "Add your name in your work details first.");
      if (b.headline && /@|https?:\/\//.test(b.headline)) return error(422, "validation_error");
      Object.assign(state, {
        visible: b.visible,
        headline: b.headline,
        accepts: b.accepts_patient_messages,
        showInst: b.show_institutions,
        showAtlas: b.show_atlas_entry,
        cardId: b.visible ? (state.cardId ?? CARD_ID) : state.cardId,
      });
      return { json: myCard(state) };
    },
    "POST /me/professional/verification-request": (r: Req) => {
      log(r);
      if (state.verified) return error(409, "conflict", "Your identity is already confirmed.");
      const b = r.body as { institutional_email: string; profile_url: string };
      if (opts.autoApprove) Object.assign(state, { verified: true, method: "manual_simulated", request: null });
      else state.request = { status: "pending", institutional_email: b.institutional_email, profile_url: b.profile_url };
      return { json: myCard(state) };
    },
    "DELETE /me/professional/verification-request": (r: Req) => {
      log(r);
      state.request = null;
      return { status: 204, body: "" };
    },
    "GET /people/*": () => ({ json: myCard(state).preview ?? publicCard() }),
  };
  return { state, calls, mocks };
}
