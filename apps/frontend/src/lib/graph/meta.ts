/**
 * Presentation metadata for node types, edge families and relations.
 * A lens changes words, never what is shown (system spec, "Role lenses").
 */
import {
  Activity,
  Boxes,
  Coins,
  Cog,
  Database,
  Diff,
  Dna,
  FileText,
  FlaskConical,
  HeartHandshake,
  Hospital,
  type LucideIcon,
  Microscope,
  Network,
  PersonStanding,
  Quote,
  Stethoscope,
  Workflow,
} from "lucide-react";

import type { EdgeFamily, NodeType, Origin, Relation, Role } from "./types";

/** How things are worded: guest & patient → plain, doctor → clinical, researcher → technical. */
export type LabelStyle = "plain" | "clinical" | "technical";

export const LABEL_STYLE_BY_ROLE: Record<Role, LabelStyle> = {
  guest: "plain",
  patient: "plain",
  doctor: "clinical",
  researcher: "technical",
};

type Worded = Record<LabelStyle, string>;
const same = (s: string): Worded => ({ plain: s, clinical: s, technical: s });

export type NodeTypeMeta = {
  type: NodeType;
  /** Singular label per style. */
  label: Worded;
  /** Plural label per style. */
  plural: Worded;
  icon: LucideIcon;
  /** CSS custom property holding the colour, e.g. `--node-disease`. */
  colorVar: `--node-${string}`;
  /** Tailwind-friendly colour utility suffix: `bg-node-disease`, `text-node-disease`. */
  colorClass: string;
  /** Which chain of the hierarchy it belongs to (system spec, "Hierarchies"). */
  group: "biology" | "research" | "clinical" | "community" | "cluster";
};

const node = (
  type: NodeType,
  label: Worded,
  plural: Worded,
  icon: LucideIcon,
  group: NodeTypeMeta["group"],
): NodeTypeMeta => {
  const slug = type.replace(/_/g, "-");
  return {
    type,
    label,
    plural,
    icon,
    group,
    colorVar: `--node-${slug}`,
    colorClass: `node-${slug}`,
  };
};

export const NODE_TYPE_META: Record<NodeType, NodeTypeMeta> = {
  disease: node(
    "disease",
    { plain: "Condition", clinical: "Disease", technical: "Disease (MONDO)" },
    { plain: "Conditions", clinical: "Diseases", technical: "Diseases (MONDO)" },
    Activity,
    "biology",
  ),
  gene: node(
    "gene",
    { plain: "Gene", clinical: "Gene", technical: "Gene (HGNC)" },
    { plain: "Genes", clinical: "Genes", technical: "Genes (HGNC)" },
    Dna,
    "biology",
  ),
  variant: node(
    "variant",
    { plain: "Gene change", clinical: "Variant", technical: "Variant (ClinVar)" },
    { plain: "Gene changes", clinical: "Variants", technical: "Variants (ClinVar)" },
    Diff,
    "biology",
  ),
  mechanism: node(
    "mechanism",
    { plain: "How it goes wrong", clinical: "Mechanism", technical: "Mechanism" },
    { plain: "Ways it goes wrong", clinical: "Mechanisms", technical: "Mechanisms" },
    Cog,
    "biology",
  ),
  pathway: node(
    "pathway",
    { plain: "Body process", clinical: "Pathway", technical: "Pathway (Reactome/GO)" },
    { plain: "Body processes", clinical: "Pathways", technical: "Pathways (Reactome/GO)" },
    Workflow,
    "biology",
  ),
  phenotype: node(
    "phenotype",
    { plain: "Symptom", clinical: "Clinical feature", technical: "Phenotype (HPO)" },
    { plain: "Symptoms", clinical: "Clinical features", technical: "Phenotypes (HPO)" },
    PersonStanding,
    "biology",
  ),
  paper: node(
    "paper",
    { plain: "Study article", clinical: "Publication", technical: "Paper (PMID)" },
    { plain: "Study articles", clinical: "Publications", technical: "Papers (PMID)" },
    FileText,
    "research",
  ),
  claim: node(
    "claim",
    { plain: "Finding", clinical: "Claim", technical: "Claim" },
    { plain: "Findings", clinical: "Claims", technical: "Claims" },
    Quote,
    "research",
  ),
  researcher: node(
    "researcher",
    same("Researcher"),
    same("Researchers"),
    Microscope,
    "research",
  ),
  doctor: node(
    "doctor",
    { plain: "Doctor", clinical: "Clinician", technical: "Clinician" },
    { plain: "Doctors", clinical: "Clinicians", technical: "Clinicians" },
    Stethoscope,
    "clinical",
  ),
  institution: node(
    "institution",
    { plain: "Hospital or lab", clinical: "Center", technical: "Institution" },
    { plain: "Hospitals and labs", clinical: "Centers", technical: "Institutions" },
    Hospital,
    "clinical",
  ),
  network: node(
    "network",
    { plain: "Expert network", clinical: "Reference network", technical: "Reference network" },
    { plain: "Expert networks", clinical: "Reference networks", technical: "Reference networks" },
    Network,
    "clinical",
  ),
  grant: node(
    "grant",
    { plain: "Research funding", clinical: "Grant", technical: "Grant (RePORTER)" },
    { plain: "Research funding", clinical: "Grants", technical: "Grants (RePORTER)" },
    Coins,
    "research",
  ),
  trial: node(
    "trial",
    { plain: "Clinical study", clinical: "Clinical trial", technical: "Trial (NCT)" },
    { plain: "Clinical studies", clinical: "Clinical trials", technical: "Trials (NCT)" },
    FlaskConical,
    "clinical",
  ),
  patient_org: node(
    "patient_org",
    { plain: "Patient group", clinical: "Patient organization", technical: "Patient organization" },
    { plain: "Patient groups", clinical: "Patient organizations", technical: "Patient organizations" },
    HeartHandshake,
    "community",
  ),
  registry: node(
    "registry",
    { plain: "Patient registry", clinical: "Registry / natural history study", technical: "Registry" },
    { plain: "Patient registries", clinical: "Registries", technical: "Registries" },
    Database,
    "community",
  ),
  cluster: node(
    "cluster",
    { plain: "Group of related conditions", clinical: "Disease cluster", technical: "Cluster (Leiden)" },
    { plain: "Groups of related conditions", clinical: "Disease clusters", technical: "Clusters (Leiden)" },
    Boxes,
    "cluster",
  ),
};

export function nodeTypeMeta(type: string): NodeTypeMeta {
  return NODE_TYPE_META[type as NodeType] ?? NODE_TYPE_META.disease;
}

export type EdgeFamilyMeta = {
  family: EdgeFamily;
  label: Worded;
  /** Short explanation for legends and tooltips. */
  description: Worded;
  colorVar: `--edge-${EdgeFamily}`;
  colorClass: `edge-${EdgeFamily}`;
};

export const EDGE_FAMILY_META: Record<EdgeFamily, EdgeFamilyMeta> = {
  dna: {
    family: "dna",
    label: { plain: "Shared biology", clinical: "Genetic / mechanism link", technical: "DNA (gene, mechanism, pathway)" },
    description: {
      plain: "Linked through the same gene or the same process in the body.",
      clinical: "Shared causal gene, mechanism or pathway.",
      technical: "Gene, mechanism and pathway relations, incl. same/different-mechanism disease pairs.",
    },
    colorVar: "--edge-dna",
    colorClass: "edge-dna",
  },
  symptoms: {
    family: "symptoms",
    label: { plain: "Similar symptoms", clinical: "Phenotypic overlap", technical: "Symptoms (HPO similarity)" },
    description: {
      plain: "Similar experience, possibly a different cause.",
      clinical: "Overlapping clinical features; aetiology may differ.",
      technical: "pyhpo best-match-average similarity above threshold; shared HPO terms stored.",
    },
    colorVar: "--edge-symptoms",
    colorClass: "edge-symptoms",
  },
  research: {
    family: "research",
    label: { plain: "Shared research", clinical: "Research link", technical: "Research (papers, grants, people)" },
    description: {
      plain: "The same researchers, studies or funding.",
      clinical: "Shared investigators, publications or grants.",
      technical: "authored / asserts / pi_of / funds_research_on / shared_researcher.",
    },
    colorVar: "--edge-research",
    colorClass: "edge-research",
  },
  community: {
    family: "community",
    label: { plain: "Patient & care community", clinical: "Community & clinical link", technical: "Community and clinical" },
    description: {
      plain: "Patient groups, registries, hospitals and studies.",
      clinical: "Patient organizations, registries, centers and trials.",
      technical: "serves / runs / studies / investigator_of / affiliated_with.",
    },
    colorVar: "--edge-community",
    colorClass: "edge-community",
  },
};

/** Relation labels per style. Direction reads source → target. */
export const RELATION_LABELS: Record<Relation, Worded> = {
  caused_by_variant_in: { plain: "is caused by changes in", clinical: "caused by variants in", technical: "caused_by_variant_in" },
  acts_via: { plain: "goes wrong through", clinical: "acts via", technical: "acts_via" },
  participates_in: { plain: "takes part in", clinical: "participates in", technical: "participates_in" },
  has_phenotype: { plain: "can cause", clinical: "presents with", technical: "has_phenotype" },
  same_gene_same_mechanism: { plain: "same gene, same way of going wrong", clinical: "same gene, same mechanism", technical: "same_gene_same_mechanism" },
  same_gene_different_mechanism: { plain: "same gene, but it goes wrong differently", clinical: "same gene, different mechanism", technical: "same_gene_different_mechanism" },
  shared_pathway: { plain: "affects the same body process", clinical: "shares a pathway with", technical: "shared_pathway" },
  similar_symptoms: { plain: "similar experience, possibly different cause", clinical: "phenotypically similar to", technical: "similar_symptoms" },
  shared_researcher: { plain: "studied by the same researchers as", clinical: "shares investigators with", technical: "shared_researcher" },
  asserts: { plain: "reports", clinical: "asserts", technical: "asserts" },
  authored: { plain: "wrote", clinical: "authored", technical: "authored" },
  pi_of: { plain: "leads", clinical: "principal investigator of", technical: "pi_of" },
  funds_research_on: { plain: "pays for research on", clinical: "funds research on", technical: "funds_research_on" },
  serves: { plain: "supports people with", clinical: "serves", technical: "serves" },
  runs: { plain: "runs", clinical: "runs", technical: "runs" },
  studies: { plain: "studies", clinical: "studies", technical: "studies" },
  investigator_of: { plain: "works on the study", clinical: "investigator of", technical: "investigator_of" },
  affiliated_with: { plain: "works at", clinical: "affiliated with", technical: "affiliated_with" },
  variant_of: { plain: "is a change in", clinical: "variant of", technical: "variant_of" },
  observed_in: { plain: "was seen in", clinical: "observed in", technical: "observed_in" },
  member_of: { plain: "belongs to", clinical: "member of", technical: "member_of" },
  about: { plain: "is about", clinical: "about", technical: "about" },
};

export function relationLabel(relation: string, style: LabelStyle): string {
  return RELATION_LABELS[relation as Relation]?.[style] ?? relation.replace(/_/g, " ");
}

export type OriginMeta = {
  origin: Origin;
  label: Worded;
  description: string;
  /** Line style used in every renderer and legend. */
  line: "solid" | "dashed" | "dotted";
};

export const ORIGIN_META: Record<Origin, OriginMeta> = {
  observed: {
    origin: "observed",
    label: same("Data"),
    description: "Observed in a cited source.",
    line: "solid",
  },
  inferred: {
    origin: "inferred",
    label: same("Hypothesis"),
    description: "Inferred by analysis; not directly observed in a source.",
    line: "dashed",
  },
  patient_reported: {
    origin: "patient_reported",
    label: same("Patient-reported"),
    description: "Shared by patients or families; kept separate from cited evidence.",
    line: "dotted",
  },
  user_contributed: {
    origin: "user_contributed",
    label: same("User-contributed"),
    description: "Contributed by a signed-in user; pending review.",
    line: "dotted",
  },
};

export type ConfidenceLevel = "high" | "medium" | "low";

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.5) return "medium";
  return "low";
}

export const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};
