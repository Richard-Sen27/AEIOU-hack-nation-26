/**
 * Presentation metadata for the nine Atlas category trees. A lens changes
 * the words, never what is shown. Colours come from the theme's node-type
 * tokens, so light and dark both work.
 */
import type { LabelStyle } from "@/lib/graph/meta";
import { NODE_TYPE_META } from "@/lib/graph/meta";
import type { GraphTheme } from "@/lib/graph/style";
import type { NodeType } from "@/lib/graph/types";

import type { AtlasCategory } from "./tree-model";

export type AtlasCategoryMeta = {
  id: AtlasCategory;
  /** Category name per label style (from the lens). */
  label: Record<LabelStyle, string>;
  /** Node type whose theme colour the category borrows. */
  colorType: NodeType;
  /** CSS custom property of that colour, for DOM overlays. */
  colorVar: `--node-${string}`;
};

/** The nine categories clockwise from 12 o'clock (same order as the backend). */
export const ATLAS_CATEGORIES: readonly AtlasCategory[] = [
  "researchers",
  "institutions",
  "literature",
  "community",
  "pathways",
  "genes",
  "diseases",
  "symptoms",
  "doctors",
];

const meta = (
  id: AtlasCategory,
  label: Record<LabelStyle, string>,
  colorType: NodeType,
): AtlasCategoryMeta => ({ id, label, colorType, colorVar: NODE_TYPE_META[colorType].colorVar });

export const CATEGORY_META: Record<AtlasCategory, AtlasCategoryMeta> = {
  researchers: meta(
    "researchers",
    { plain: "Researchers", clinical: "Researchers", technical: "Researchers" },
    "researcher",
  ),
  institutions: meta(
    "institutions",
    { plain: "Hospitals & universities", clinical: "Hospitals & universities", technical: "Institutions" },
    "institution",
  ),
  literature: meta(
    "literature",
    { plain: "Articles, studies & funding", clinical: "Publications, trials & grants", technical: "Literature" },
    "paper",
  ),
  community: meta(
    "community",
    { plain: "Patient groups & registries", clinical: "Patient organizations & registries", technical: "Community" },
    "patient_org",
  ),
  pathways: meta(
    "pathways",
    { plain: "Body processes", clinical: "Pathways", technical: "Pathways" },
    "pathway",
  ),
  genes: meta(
    "genes",
    { plain: "Genes & gene changes", clinical: "Genes & variants", technical: "Genes" },
    "gene",
  ),
  diseases: meta(
    "diseases",
    { plain: "Conditions", clinical: "Diseases", technical: "Diseases" },
    "disease",
  ),
  symptoms: meta(
    "symptoms",
    { plain: "Symptoms", clinical: "Clinical features", technical: "Phenotypes" },
    "phenotype",
  ),
  doctors: meta(
    "doctors",
    { plain: "Doctors", clinical: "Clinicians", technical: "Clinicians" },
    "doctor",
  ),
};

/** Category label for the current lens. */
export function categoryLabel(category: AtlasCategory, labelStyle: LabelStyle): string {
  return CATEGORY_META[category].label[labelStyle];
}

/** Resolved category colour for canvas renderers (Sigma needs hex/rgb). */
export function categoryColor(category: AtlasCategory, theme: GraphTheme): string {
  return theme.node[CATEGORY_META[category].colorType] ?? theme.muted;
}

/**
 * Short category names per lens, for small canvases where the full name would have to be
 * drawn too small to read inside the space the layout reserves for it.
 */
export const CATEGORY_SHORT_LABEL: Record<AtlasCategory, Record<LabelStyle, string>> = {
  researchers: { plain: "Researchers", clinical: "Researchers", technical: "Researchers" },
  institutions: { plain: "Hospitals", clinical: "Hospitals", technical: "Institutions" },
  literature: { plain: "Articles", clinical: "Publications", technical: "Literature" },
  community: { plain: "Patient groups", clinical: "Patient groups", technical: "Community" },
  pathways: { plain: "Processes", clinical: "Pathways", technical: "Pathways" },
  genes: { plain: "Genes", clinical: "Genes", technical: "Genes" },
  diseases: { plain: "Conditions", clinical: "Diseases", technical: "Diseases" },
  symptoms: { plain: "Symptoms", clinical: "Features", technical: "Phenotypes" },
  doctors: { plain: "Doctors", clinical: "Clinicians", technical: "Clinicians" },
};

/** Short category label for the current lens. */
export function categoryShortLabel(category: AtlasCategory, labelStyle: LabelStyle): string {
  return CATEGORY_SHORT_LABEL[category][labelStyle];
}

/** Longest name of a category across lenses, in characters (the layout reserves room for it). */
export function categoryLabelChars(category: AtlasCategory): number {
  return Math.max(...Object.values(CATEGORY_META[category].label).map((l) => l.length));
}
