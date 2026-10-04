import type { Schemas } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";

/**
 * Sign-ups to calls (connect stage 4). A sign-up is the patient's own act and
 * an authorization for one disclosure: exactly the ticked items, a chosen name
 * and an optional note go to the call's publisher. Nothing shared ever goes
 * into a URL, the page title, browser storage or a log.
 */

export type SignupOptions = Schemas.SignupOptions;
export type SignupOption = Schemas.SignupOption;
export type SignupAvailability = Schemas.SignupAvailability;
export type MySignup = Schemas.MySignup;
export type ReceivedSignup = Schemas.ReceivedSignup;
export type SignupStatus = Schemas.SignupStatus;
export type SharedItems = Schemas.SharedItems;

export const MAX_NAME = 60;
export const SIGNUPS_HREF = "/calls/signups";

export function threadHref(id: string) {
  return `/messages/${encodeURIComponent(id)}`;
}

export const SIGNUP_STATUS_LABEL: Record<SignupStatus, string> = {
  active: "Signed up",
  withdrawn: "Withdrawn",
  declined: "Declined by the team",
  call_closed: "Call closed",
};

/** The publisher's word for a status. */
export const RECEIVED_STATUS_LABEL: Record<SignupStatus, string> = {
  active: "Active",
  withdrawn: "Withdrew",
  declined: "Declined",
  call_closed: "Call closed",
};

/** What was shared, as short labels in a fixed order. */
export function sharedLabels(s: SharedItems): string[] {
  const one = (i: Schemas.SharedItem) => (i.detail ? `${i.label} (${i.detail})` : i.label);
  return [
    ...(s.diagnoses ?? []).map(one),
    ...(s.genes ?? []).map(one),
    ...(s.variants ?? []).map(one),
    ...(s.symptoms ?? []).map(one),
    ...(s.age_range ? [`Age range ${s.age_range}`] : []),
    ...(s.country ? [`Country ${s.country}`] : []),
  ];
}

/** The authorization text with the ticked items where `{items}` stands. */
export function authorizationText(options: SignupOptions, ticked: string[], withNote: boolean): string {
  const labels = options.options.filter((o) => ticked.includes(o.key)).map((o) => o.label);
  if (withNote) labels.push("your note");
  const items = labels.length ? labels.join(", ") : "your name only";
  return options.authorization_text.replace("{items}", items);
}

/** The field a 422 names ("Invalid request fields: display_name"). */
function invalidField(message: string): string {
  const m = message.match(/Invalid request fields: ([a-z_]+)/);
  return m?.[1] ?? "";
}

/**
 * One short message per sign-up error. Never echoes what the user typed.
 * 409s share one code; the backend's message tells them apart.
 */
export function signupErrorText(e: unknown, { conversation = false }: { conversation?: boolean } = {}): string {
  const err = e instanceof ApiError ? e : null;
  const msg = err?.message ?? "";
  switch (err?.code) {
    case "consent_required":
      return "Your consent is needed first.";
    case "age_group_required":
      return "Tell us your age group first.";
    case "guardian_agreement_required":
      return "Tick the parent or guardian box to send.";
    case "forbidden":
      return /adults/i.test(msg) ? "This call is for adults." : "Only patients and caregivers can sign up.";
    case "not_found":
      return "This call is closed or no longer listed.";
    case "conflict":
      if (/all the sign-ups/i.test(msg)) return "This call is full.";
      if (/already signed up/i.test(msg)) return "You have already signed up.";
      if (/declined/i.test(msg)) return "The study team declined your earlier sign-up.";
      if (/own call/i.test(msg)) return "This is your own call.";
      if (/open on|not opened/i.test(msg)) return "Sign-ups have not opened yet.";
      if (/cannot receive/i.test(msg)) return "The study team cannot take sign-ups right now.";
      if (/closed/i.test(msg)) return "This call has closed.";
      return "Signing up is not possible right now.";
    case "validation_error": {
      const field = invalidField(msg);
      if (field === "display_name") return "Check your name (1 to 60 characters).";
      if (field === "note") return "Check the note (plain text, up to 1,000 characters).";
      if (field === "items") return "Some items can no longer be shared. Reload the page.";
      if (field === "authorized") return "Tick the box to agree.";
      if (field === "authorization_version") return "The text changed. Reload the page.";
      if (field === "parental_responsibility_confirmed") return "Confirm parental responsibility in your profile first.";
      return "Check the form.";
    }
    case "rate_limited":
      return conversation
        ? "You can open 5 new conversations a day. Send without one, or try tomorrow."
        : "Too many sign-ups today. Try again tomorrow.";
    case "network_error":
      return "Amber's server is not reachable. Please try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}
