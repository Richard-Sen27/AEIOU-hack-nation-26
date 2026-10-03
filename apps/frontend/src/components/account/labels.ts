import type {
  AgeRange,
  AssetType,
  DocType,
  ProfileSource,
  VariantClassification,
  Zygosity,
} from "@/lib/api/generated/types.gen";

export const LANGUAGES: Array<{ code: string; label: string }> = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
  { code: "it", label: "Italiano" },
  { code: "pt", label: "Português" },
  { code: "nl", label: "Nederlands" },
];

export const SELECTABLE_ROLES = ["patient", "doctor", "researcher"] as const;
export type SelectableRole = (typeof SELECTABLE_ROLES)[number];

export const ROLE_COPY: Record<SelectableRole, { label: string; start: string }> = {
  patient: {
    label: "Patient or family",
    start: "Start at your condition, with similar diseases and patient communities, in plain language.",
  },
  doctor: {
    label: "Doctor",
    start: "Start with the symptom profile, centres of expertise and variant classifications, in clinical terms.",
  },
  researcher: {
    label: "Researcher",
    start: "Start with mechanism clusters, pathways, papers and funding, with IDs shown.",
  },
};

export const SOURCE_LABEL: Record<ProfileSource, string> = {
  chat: "From chat",
  document: "From a document",
  manual: "Added by you",
};

export const DOC_TYPE_LABEL: Record<DocType, string> = {
  genetic_report: "Genetic report",
  clinical_letter: "Clinical letter",
  research_paper: "Research paper",
  registry_document: "Registry or study document",
};

export const ZYGOSITY_LABEL: Record<Zygosity, string> = {
  heterozygous: "Heterozygous",
  homozygous: "Homozygous",
  hemizygous: "Hemizygous",
  compound_heterozygous: "Compound heterozygous",
  mosaic: "Mosaic",
  unknown: "Unknown",
};

export const CLASSIFICATION_LABEL: Record<VariantClassification, string> = {
  pathogenic: "Pathogenic",
  likely_pathogenic: "Likely pathogenic",
  uncertain_significance: "Uncertain significance (VUS)",
  likely_benign: "Likely benign",
  benign: "Benign",
};

export const AGE_RANGES: AgeRange[] = ["0-1", "1-5", "6-12", "13-17", "18-39", "40-64", "65+"];

export const AGE_RANGE_LABEL: Record<AgeRange, string> = {
  "0-1": "Under 1 year",
  "1-5": "1 to 5 years",
  "6-12": "6 to 12 years",
  "13-17": "13 to 17 years",
  "18-39": "18 to 39 years",
  "40-64": "40 to 64 years",
  "65+": "65 or older",
};

/** HPO onset terms (HP:0003674 "Onset" subtree, the common ones). */
export const ONSETS: Array<{ id: string; label: string }> = [
  { id: "HP:0030674", label: "Before birth (antenatal)" },
  { id: "HP:0003577", label: "At birth (congenital)" },
  { id: "HP:0003623", label: "First 4 weeks (neonatal)" },
  { id: "HP:0003593", label: "Infancy (1 to 12 months)" },
  { id: "HP:0011463", label: "Childhood (1 to 5 years)" },
  { id: "HP:0003621", label: "Juvenile (5 to 15 years)" },
  { id: "HP:0003581", label: "Adult (16 years or later)" },
];

export const ASSET_TYPE_LABEL: Record<AssetType, string> = {
  registry: "Patient registry",
  natural_history_study: "Natural history study",
  model: "Disease model",
  biomarker: "Biomarker",
  other: "Other resource",
};

/** ISO 3166-1 alpha-2 codes; names come from Intl.DisplayNames. */
export const COUNTRY_CODES =
  "AD AE AF AG AL AM AO AR AT AU AZ BA BB BD BE BF BG BH BI BJ BN BO BR BS BT BW BY BZ CA CD CF CG CH CI CL CM CN CO CR CU CV CY CZ DE DJ DK DM DO DZ EC EE EG ER ES ET FI FJ FR GA GB GD GE GH GM GN GQ GR GT GW GY HK HN HR HT HU ID IE IL IN IQ IR IS IT JM JO JP KE KG KH KM KN KR KW KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MK ML MM MN MR MT MU MV MW MX MY MZ NA NE NG NI NL NO NP NZ OM PA PE PG PH PK PL PS PT PY QA RO RS RU RW SA SB SC SD SE SG SI SK SL SM SN SO SR SS SV SY SZ TD TG TH TJ TL TM TN TO TR TT TW TZ UA UG US UY UZ VA VC VE VN VU WS YE ZA ZM ZW".split(
    " ",
  );

export function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function formatDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}
