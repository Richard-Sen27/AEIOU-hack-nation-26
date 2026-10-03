/**
 * Role presentation hints for the node view. The server sends them with
 * every neighbourhood (`hints`); these are the fallback when it does not, and
 * mirror the spec ("Hierarchies"): the lens decides where you start and how
 * things are worded, never what is shown.
 */
import type { Schemas } from "@/lib/api";
import type { Role } from "@/lib/graph/types";

export type LayoutHints = Schemas.LayoutHints;

export const FALLBACK_HINTS: Record<Role, LayoutHints> = {
  guest: {
    start_layout: "ring",
    label_style: "plain",
    highlight_family: ["symptoms", "community"],
    highlight_node_types: ["disease", "patient_org"],
    show_ids: false,
  },
  patient: {
    start_layout: "ring",
    label_style: "plain",
    highlight_family: ["symptoms", "community"],
    highlight_node_types: ["disease", "patient_org", "registry"],
    show_ids: false,
  },
  doctor: {
    start_layout: "ring",
    label_style: "clinical",
    highlight_family: ["symptoms", "community"],
    highlight_node_types: ["phenotype", "institution", "trial", "variant"],
    show_ids: false,
  },
  researcher: {
    start_layout: "force",
    label_style: "technical",
    highlight_family: ["dna", "research"],
    highlight_node_types: ["variant", "pathway", "paper", "grant", "mechanism"],
    show_ids: true,
  },
};

export function resolveHints(server: LayoutHints | null | undefined, role: Role): LayoutHints {
  const fb = FALLBACK_HINTS[role];
  if (!server) return fb;
  return {
    ...fb,
    ...server,
    highlight_family: server.highlight_family?.length ? server.highlight_family : fb.highlight_family,
    highlight_node_types: server.highlight_node_types?.length ? server.highlight_node_types : fb.highlight_node_types,
  };
}
