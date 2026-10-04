import { ClipboardList, FlaskConical, Microscope, type LucideIcon } from "lucide-react";

import type { Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

/**
 * Calls (connect stage 3): surveys, studies and trials looking for
 * participants. Wording rule for every screen: calls are about finding
 * research to take part in, never about getting a treatment.
 */

export type Call = Schemas.Call;
export type OwnCall = Schemas.OwnCall;
export type CallKind = Schemas.CallKind;
export type CallStatus = Schemas.CallStatus;
export type CallInput = Schemas.CallInput;
export type RequestedField = Schemas.RequestedField;

export const CALL_KINDS: CallKind[] = ["survey", "study", "trial"];

export const KIND_META: Record<CallKind, { label: string; plural: string; icon: LucideIcon }> = {
  survey: { label: "Survey", plural: "Surveys", icon: ClipboardList },
  study: { label: "Study", plural: "Studies", icon: Microscope },
  trial: { label: "Trial", plural: "Trials", icon: FlaskConical },
};

export const STATUS_META: Record<CallStatus, { label: string; tone: "muted" | "wait" | "live" | "bad" }> = {
  draft: { label: "Draft", tone: "muted" },
  pending_review: { label: "In review", tone: "wait" },
  published: { label: "Published", tone: "live" },
  closed: { label: "Closed", tone: "muted" },
  withdrawn: { label: "Withdrawn", tone: "muted" },
  rejected: { label: "Not approved", tone: "bad" },
};

export const REQUESTED_FIELD_LABELS: Record<RequestedField, string> = {
  diagnosis: "Diagnosis",
  genetic_findings: "Genetic findings",
  symptoms: "Symptoms",
  age_range: "Age range",
  country: "Country",
};

/** Form field names as the API names them in a 422, mapped to the label shown. */
export const FIELD_LABELS: Record<string, string> = {
  kind: "Kind",
  title: "Title",
  summary: "What it is about",
  participation: "What taking part involves",
  eligibility_text: "Who can take part",
  disease_ids: "Diseases",
  gene_ids: "Genes",
  phenotype_ids: "Symptoms",
  min_age: "Minimum age",
  max_age: "Maximum age",
  countries: "Countries",
  run_by_label: "Run by",
  run_by_node_id: "Run by",
  ethics_body: "Ethics committee",
  ethics_reference: "Ethics approval reference",
  registry_id: "Registry number",
  external_url: "Link",
  opens_at: "Opens",
  closes_at: "Closes",
  max_signups: "Most sign-ups",
  requested_fields: "Shared on sign-up",
  call: "Call",
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field.split(".")[0]] ?? field.replace(/_/g, " ");
}

/** "For adults", "Ages 4 to 17", "From 2", "Up to 12" or null. */
export function ageText(call: Pick<Call, "min_age" | "max_age" | "adults_only">): string | null {
  const { min_age: min, max_age: max } = call;
  if (call.adults_only && max == null) return "For adults";
  if (min != null && max != null) return `Ages ${min} to ${max}`;
  if (min != null) return `From age ${min}`;
  if (max != null) return `Up to age ${max}`;
  return null;
}

let regionNames: Intl.DisplayNames | null | undefined;
export function countryName(code: string): string {
  if (regionNames === undefined) {
    try {
      regionNames = new Intl.DisplayNames(["en"], { type: "region" });
    } catch {
      regionNames = null;
    }
  }
  try {
    return regionNames?.of(code) ?? code;
  } catch {
    return code;
  }
}

export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "Run by" as text: the atlas organisation or the free-text label. */
export function runByText(call: Pick<Call, "run_by_node" | "run_by_label">): string | null {
  return call.run_by_node?.label ?? call.run_by_label ?? null;
}

/**
 * Whether a submitted call waits for the Amber team (`true`) or goes live at
 * once after the wording check (`false`, the default).
 */
export function reviewRequired(list: object | null | undefined): boolean {
  return (list as { review_required?: boolean } | null | undefined)?.review_required === true;
}

export function callHref(id: string) {
  return `/calls/${encodeURIComponent(id)}`;
}

export function personHref(cardId: string) {
  return `/people/${encodeURIComponent(cardId)}`;
}

/** Short message for a failed call request (never echoes what was sent). */
export function callErrorText(error: ApiError | null | undefined, openLimit = 10): string {
  switch (error?.code) {
    case "network_error":
      return "Amber's server is not reachable. Try again in a moment.";
    case "rate_limited":
      return "Too many requests. Try again later.";
    case "forbidden":
      return "Only verified doctors and researchers with a visible card can publish.";
    case "not_found":
      return "This call no longer exists.";
    case "conflict":
      return error.message.includes("at most") ? `You can have ${openLimit} open calls at a time.` : "This call can no longer be changed.";
    case "validation_error":
      return validationText(error.message);
    default:
      return "That did not work. Try again in a moment.";
  }
}

/**
 * A 422 names the field ("Invalid request fields: ethics_reference") or, from
 * the wording check, the field and rule ("… Rephrase: summary ('cure')").
 */
export function validationText(message: string): string {
  const wording = message.match(/Rephrase: (.+)$/);
  if (wording) {
    const parts = wording[1].split(/,\s(?=[a-z_]+ \(')/).map((p) => {
      const m = p.match(/^([a-z_]+) \('(.+)'\)$/);
      return m ? `${fieldLabel(m[1])} ("${m[2]}")` : p;
    });
    return `Calls look for participants and must not offer, promise or price a treatment. Rephrase: ${parts.join(", ")}.`;
  }
  const fields = message.match(/Invalid request fields: (.+)$/);
  if (fields) {
    const names = [...new Set(fields[1].split(/,\s*/).map(fieldLabel))];
    return `Check: ${names.join(", ")}.`;
  }
  return "Some fields are not valid. Check them.";
}

/** The field names a 422 points at (for highlighting inputs). */
export function invalidFields(message: string): string[] {
  const wording = message.match(/Rephrase: (.+)$/);
  if (wording) return [...wording[1].matchAll(/([a-z_]+) \('/g)].map((m) => m[1]);
  const fields = message.match(/Invalid request fields: (.+)$/);
  if (fields) return fields[1].split(/,\s*/).map((f) => f.split(".")[0]);
  return [];
}
