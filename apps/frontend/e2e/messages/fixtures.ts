/**
 * Mocked messaging routes with state, so a test can send, accept, block and
 * see the result. Bodies and names here are test data only.
 */
import { errorEnvelope, signedInSession } from "../helpers";

export type Req = { url: string; method: string; body: unknown };

export const CARD_ID = "11111111-1111-4111-8111-111111111111";
export const SECRET = "my seizures got worse after the switch";

type Counterpart = { name: string | null; is_professional: boolean; card_id: string | null; deleted: boolean };
type Msg = { id: string; mine: boolean; body: string | null; created_at: string };
type ThreadState = {
  id: string;
  origin: "card" | "signup";
  status: "requested" | "open" | "declined" | "closed" | "blocked";
  my_role: "opener" | "recipient";
  counterpart: Counterpart;
  created_at: string;
  last_message_at: string | null;
  unread_count: number;
  can_send: boolean;
  can_respond: boolean;
  blocked_by_me: boolean;
  guardian_agreement_needed: boolean;
  hidden?: boolean;
  messages: Msg[];
};

const T0 = "2026-10-03T09:00:00Z";
const pro = (name: string | null, deleted = false): Counterpart => ({ name, is_professional: true, card_id: deleted ? null : CARD_ID, deleted });
const patient = (name: string | null, deleted = false): Counterpart => ({ name, is_professional: false, card_id: null, deleted });

export function thread(id: string, extra: Partial<ThreadState> = {}): ThreadState {
  return {
    id,
    origin: "card",
    status: "open",
    my_role: "opener",
    counterpart: pro("Dr. Anna Berg"),
    created_at: T0,
    last_message_at: T0,
    unread_count: 0,
    can_send: true,
    can_respond: false,
    blocked_by_me: false,
    guardian_agreement_needed: false,
    messages: [],
    ...extra,
  };
}

const msg = (id: string, mine: boolean, body: string | null, at = T0): Msg => ({ id, mine, body, created_at: at });

/** The patient's side: one of every status, plus a deleted counterpart. */
export function patientThreads(): ThreadState[] {
  return [
    thread("a0000000-0000-4000-8000-000000000001", {
      unread_count: 2,
      last_message_at: "2026-10-04T08:00:00Z",
      messages: [
        msg("m1", true, "Hello, my son has Dravet syndrome."),
        msg("m2", false, "Thanks for writing. Visit https://example.org/trial for the study.", "2026-10-04T07:50:00Z"),
        msg("m3", false, "Line one\nLine two", "2026-10-04T08:00:00Z"),
      ],
    }),
    thread("a0000000-0000-4000-8000-000000000002", {
      status: "requested",
      counterpart: pro("Prof. Jonas Weber"),
      can_send: false,
      messages: [msg("m4", true, "Could you tell me about your SCN1A study?")],
    }),
    thread("a0000000-0000-4000-8000-000000000003", { status: "declined", counterpart: pro("Dr. Kim Lee"), can_send: false }),
    thread("a0000000-0000-4000-8000-000000000004", { status: "closed", counterpart: pro("Dr. Omar Haddad"), can_send: false }),
    thread("a0000000-0000-4000-8000-000000000005", { status: "blocked", counterpart: pro("Dr. Spam"), can_send: false, blocked_by_me: true }),
    thread("a0000000-0000-4000-8000-000000000006", { status: "closed", counterpart: pro(null, true), can_send: false }),
  ];
}

/** The expert's side: one waiting request and one open conversation. */
export function expertThreads(): ThreadState[] {
  return [
    thread("b0000000-0000-4000-8000-000000000001", {
      status: "requested",
      my_role: "recipient",
      counterpart: patient("Maria"),
      can_send: false,
      can_respond: true,
      unread_count: 1,
      messages: [msg("e1", false, "My daughter has STXBP1. Is your registry open?")],
    }),
    thread("b0000000-0000-4000-8000-000000000002", {
      my_role: "recipient",
      counterpart: patient("Leo's dad"),
      messages: [msg("e2", false, "Thank you!"), msg("e3", true, "You're welcome.")],
    }),
  ];
}

export const card = (extra: Record<string, unknown> = {}) => ({
  card_id: CARD_ID,
  role: "doctor",
  role_self_declared: true,
  name: "Dr. Anna Berg",
  name_source: "orcid",
  institutions: [{ node_id: null, label: "Charité Berlin" }],
  orcid_id: "0000-0002-1825-0097",
  orcid_url: "https://orcid.org/0000-0002-1825-0097",
  atlas_node_id: null,
  atlas_node_label: null,
  headline: "Paediatric epilepsy",
  accepts_patient_messages: true,
  verification: { method: "orcid", label: "ORCID iD confirmed", simulated: false },
  ...extra,
});

export const connectTexts = {
  guardian_text: "A parent or guardian knows about this and agrees that I share it with {recipient}.",
  guardian_text_version: "guardian-2026-10-04",
  report_authorization_text: "I ask the Amber team to read this conversation to review my report. Every access is logged.",
  report_authorization_version: "report-2026-10-04",
};

type Opts = {
  role?: "patient" | "doctor" | "researcher";
  threads?: ThreadState[];
  consents?: string[];
  ageGroup?: "18_plus" | "16_17" | null;
  blocks?: Array<{ id: string; name: string | null; created_at: string }>;
  /** Override the POST /me/threads response (e.g. an error envelope). */
  open?: (r: Req) => unknown;
  send?: (r: Req) => unknown;
};

const summary = (t: ThreadState) => {
  const rest: Partial<ThreadState> = { ...t };
  delete rest.messages;
  delete rest.hidden;
  return rest;
};

export function messagingMocks(opts: Opts = {}) {
  const calls: Req[] = [];
  const state = {
    consents: opts.consents ?? ["health_data", "connect"],
    ageGroup: opts.ageGroup === undefined ? ("18_plus" as string | null) : opts.ageGroup,
    threads: opts.threads ?? patientThreads(),
    blocks: opts.blocks ?? [],
  };
  const log = (r: Req) => (calls.push(r), r);
  const find = (url: string) => {
    const id = new URL(url).pathname.split("/")[3];
    return state.threads.find((t) => t.id === id);
  };
  const visible = () => state.threads.filter((t) => !t.hidden);
  const unread = () => visible().reduce((n, t) => n + t.unread_count, 0);
  const waiting = () => visible().filter((t) => t.can_respond).length;
  const connectStatus = () => ({
    consent_active: state.consents.includes("connect"),
    age_group: state.ageGroup,
    age_group_set_at: state.ageGroup ? T0 : null,
    ...connectTexts,
  });

  const mocks: Record<string, unknown> = {
    "GET /auth/session": () => ({ json: signedInSession({ role: opts.role ?? "patient", consents: state.consents }) }),
    "GET /notifications/unread-count": { count: 0 },
    "GET /consents": () => ({
      json: state.consents.map((c) => ({
        id: `c-${c}`,
        consent_type: c,
        version: `${c}-2026-10-04`,
        granted_at: T0,
        revoked_at: null,
        about_child: false,
        parental_responsibility_confirmed: false,
        active: true,
      })),
    }),
    "POST /consents": (r: Req) => {
      log(r);
      const type = (r.body as { consent_type: string }).consent_type;
      state.consents = [...state.consents, type];
      return { status: 201, json: { id: `c-${type}`, consent_type: type, active: true, granted_at: new Date().toISOString() } };
    },
    "DELETE /consents/*": (r: Req) => {
      log(r);
      const type = new URL(r.url).pathname.split("/").pop()!;
      state.consents = state.consents.filter((c) => c !== type);
      if (type === "connect") {
        state.ageGroup = null;
        state.threads = state.threads.map((t) => ({ ...t, status: "closed", can_send: false, can_respond: false, messages: t.messages.filter((m) => !m.mine) }));
      }
      return { status: 204, body: "" };
    },
    "GET /me/connect": (r: Req) => (log(r), { json: connectStatus() }),
    "PUT /me/connect/age-group": (r: Req) => {
      log(r);
      if (!state.consents.includes("connect")) return errorEnvelope(403, "consent_required");
      state.ageGroup = (r.body as { age_group: string }).age_group;
      return { json: connectStatus() };
    },
    "GET /me/threads/unread-count": (r: Req) => (log(r), { json: { count: unread(), requests_waiting: waiting() } }),
    "GET /me/threads": (r: Req) => (log(r), { json: { items: visible().map(summary), unread_total: unread(), requests_waiting: waiting() } }),
    "POST /me/threads": (r: Req) => {
      log(r);
      if (opts.open) return opts.open(r);
      const b = r.body as { body: string; display_name: string; guardian_agreed: boolean };
      if (state.ageGroup === "16_17" && !b.guardian_agreed) return errorEnvelope(403, "guardian_agreement_required");
      const t = thread("c0000000-0000-4000-8000-000000000001", {
        status: "requested",
        can_send: false,
        messages: [msg("n1", true, b.body, new Date().toISOString())],
      });
      state.threads = [t, ...state.threads];
      return { status: 201, json: { thread: summary(t), messages: t.messages } };
    },
    "GET /me/threads/*": (r: Req) => {
      log(r);
      const t = find(r.url);
      if (!t) return errorEnvelope(404, "not_found");
      t.unread_count = 0;
      return { json: { thread: summary(t), messages: t.messages } };
    },
    "POST /me/threads/*/accept": (r: Req) => {
      log(r);
      const t = find(r.url)!;
      Object.assign(t, { status: "open", can_respond: false, can_send: true });
      return { json: { thread: summary(t), messages: t.messages } };
    },
    "POST /me/threads/*/decline": (r: Req) => {
      log(r);
      const t = find(r.url)!;
      Object.assign(t, { status: "declined", can_respond: false, can_send: false });
      return { json: { thread: summary(t), messages: t.messages } };
    },
    "POST /me/threads/*/messages": (r: Req) => {
      log(r);
      if (opts.send) return opts.send(r);
      const t = find(r.url)!;
      const b = r.body as { body: string; guardian_agreed: boolean };
      if (t.guardian_agreement_needed && !b.guardian_agreed) return errorEnvelope(403, "guardian_agreement_required");
      const m = msg(`s${t.messages.length + 1}`, true, b.body, new Date().toISOString());
      t.messages = [...t.messages, m];
      t.guardian_agreement_needed = false;
      return { status: 201, json: m };
    },
    "DELETE /me/threads/*/messages/*": (r: Req) => {
      log(r);
      const t = find(r.url)!;
      const mid = new URL(r.url).pathname.split("/").pop();
      t.messages = t.messages.filter((m) => m.id !== mid);
      return { status: 204, body: "" };
    },
    "POST /me/threads/*/hide": (r: Req) => {
      log(r);
      find(r.url)!.hidden = true;
      return { status: 204, body: "" };
    },
    "POST /me/threads/*/block": (r: Req) => {
      log(r);
      const t = find(r.url)!;
      Object.assign(t, { status: "blocked", blocked_by_me: true, can_send: false });
      state.blocks = [...state.blocks, { id: `blk-${t.id.slice(-1)}`, name: t.counterpart.name, created_at: T0 }];
      return { status: 204, body: "" };
    },
    "POST /me/threads/*/report": (r: Req) => {
      log(r);
      return { status: 201, json: { id: "r1", thread_id: null, message_id: null, reason: "spam", authorization_version: "report-2026-10-04", created_at: T0, reviewed_at: null } };
    },
    "GET /me/blocks": (r: Req) => (log(r), { json: { items: state.blocks } }),
    "DELETE /me/blocks/*": (r: Req) => {
      log(r);
      const id = new URL(r.url).pathname.split("/").pop();
      state.blocks = state.blocks.filter((b) => b.id !== id);
      return { status: 204, body: "" };
    },
    "GET /people/*": () => ({ json: card() }),
  };
  return { mocks, calls, state };
}
